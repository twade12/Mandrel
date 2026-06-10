"""Mandrel CLI — Phase 1 entry point.

Usage:
    mandrel run --brief "I need a temp + motion sensor board" \\
                --form-factor feather \\
                [--project-dir ./my-project] \\
                [--auto-approve]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mandrel",
        description="Turn a product brief into a verified, manufacturable electronics design.",
    )
    sub = p.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run the Phase 1 pipeline (S1 → S3 → S5)")
    run.add_argument("--brief", required=True, help="Plain-English product description")
    run.add_argument(
        "--form-factor",
        default="feather",
        choices=["feather", "hat", "mikrobus", "arduino_shield", "din_rail", "custom"],
        help="Target form factor (default: feather)",
    )
    run.add_argument(
        "--project-dir",
        default=None,
        help="Output directory for artifacts (default: ./workspace/<project-id>)",
    )
    run.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip human checkpoints (useful for automated runs)",
    )
    run.add_argument(
        "--ollama-model",
        default=None,
        help="Override the Ollama model (default: from MANDREL_LLM_MODEL env var)",
    )

    return p


async def _run(args: argparse.Namespace) -> None:
    from mandrel.config import settings
    from mandrel.core.checkpoints import AutoApproveCheckpoint, CliCheckpoint
    from mandrel.core.state import Constraints, DesignState, FormFactor, ProductSpec
    from mandrel.core.workflow import Context, PipelineRunner
    from mandrel.llm.provider import OpenAICompatibleProvider
    from mandrel.pipeline.s1_intent import IntentStage
    from mandrel.pipeline.s3_schematic import SchematicStage
    from mandrel.pipeline.s5_enclosure import EnclosureStage

    # LLM provider
    model = args.ollama_model or settings.llm_model
    llm = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=model,
        api_key=settings.llm_api_key,
    )

    # Initial state
    form_factor = FormFactor(args.form_factor)
    state = DesignState(
        spec=ProductSpec(raw_brief=args.brief),
        constraints=Constraints(form_factor=form_factor),
    )

    # Project directory
    project_dir = (
        Path(args.project_dir)
        if args.project_dir
        else settings.workspace_dir / state.project_id
    )
    project_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nProject ID : {state.project_id}")
    print(f"Output dir : {project_dir}\n")

    # Checkpoints
    if args.auto_approve:
        checkpoints: dict = {
            "s1_intent":    AutoApproveCheckpoint(),
            "s3_schematic": AutoApproveCheckpoint(),
            "s5_enclosure": AutoApproveCheckpoint(),
        }
    else:
        checkpoints = {
            "s1_intent":    CliCheckpoint("Review extracted product spec"),
            "s3_schematic": CliCheckpoint("Review schematic + ERC result"),
            "s5_enclosure": CliCheckpoint("Review enclosure clearance check"),
        }

    runner = PipelineRunner(
        stages=[
            IntentStage(llm=llm),
            SchematicStage(llm=llm),
            EnclosureStage(),
        ],
        checkpoints=checkpoints,
    )

    ctx = Context(project_dir=project_dir, config=settings)

    try:
        final_state = await runner.run(state, ctx)
    except RuntimeError as exc:
        print(f"\n[REJECTED] {exc}", file=sys.stderr)
        await llm.aclose()
        sys.exit(1)

    await llm.aclose()

    # Summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    if final_state.spec:
        print(f"Spec     : {final_state.spec.title}")
    if final_state.schematic:
        erc = final_state.schematic.erc_result
        status = "CLEAN" if (erc and erc.passed) else "FAILED"
        print(f"ERC      : {status}")
        if final_state.schematic.kicad_sch_path:
            print(f"Schematic: {final_state.schematic.kicad_sch_path}")
    if final_state.enclosure:
        cl = final_state.enclosure.clearance_result
        status = "PASS" if (cl and cl.passed) else "FAIL"
        print(f"Clearance: {status}")
        if final_state.enclosure.step_path:
            print(f"Enclosure: {final_state.enclosure.step_path}")
    print(f"\nStages run: {len(final_state.history)}")
    print("=" * 60)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(_run(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
