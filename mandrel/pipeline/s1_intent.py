"""S1 — Intent capture: guided brief → ProductSpec.

The LLM performs a single-shot JSON extraction from the raw_brief.
A human checkpoint fires to confirm the spec before the pipeline proceeds.

Phase 1 simplification: single-shot (no multi-turn interview).
Phase 4 will add multi-turn questioning when the brief is ambiguous.
"""

from __future__ import annotations

import json
import re

from mandrel.core.state import (
    DesignState,
    PowerBudget,
    ProductSpec,
    VerifierResult,
)
from mandrel.core.workflow import Context, StageResult
from mandrel.llm.prompts import S1_BRIEF_TO_SPEC
from mandrel.llm.provider import LLMProvider, Message


class IntentStage:
    """S1: extract a validated ProductSpec from a raw natural-language brief."""

    name = "s1_intent"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        if state.spec is None or not state.spec.raw_brief.strip():
            raise ValueError(
                "S1 requires state.spec.raw_brief to be set before running. "
                "Pass --brief '...' on the CLI."
            )

        raw_brief = state.spec.raw_brief
        form_factor = state.constraints.form_factor.value if state.constraints else "unspecified"

        prompt = S1_BRIEF_TO_SPEC.format(
            raw_brief=raw_brief,
            form_factor=form_factor,
        )
        await ctx.progress(self.name, "LLM extracting structured spec from brief…")
        response = await self._llm.complete(
            [Message(role="user", content=prompt)],
            temperature=0.2,
        )

        await ctx.progress(self.name, "Parsing and validating spec…")
        spec = _parse_spec(response, raw_brief)

        new_state = state.model_copy(update={"spec": spec})
        return StageResult(
            state=new_state,
            artifacts=[],
            verifier_result=VerifierResult(passed=True, score=1.0),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_spec(llm_output: str, raw_brief: str) -> ProductSpec:
    """Extract and validate a ProductSpec from the LLM's JSON response."""
    data = _extract_json(llm_output)

    power_data = data.get("power")
    if power_data and isinstance(power_data, dict):
        power: PowerBudget | None = PowerBudget(
            supply_voltage_v=float(power_data.get("supply_voltage_v") or 3.3),
            max_current_ma=float(power_data.get("max_current_ma") or 200),
            battery_capacity_mah=(
                float(power_data["battery_capacity_mah"])
                if power_data.get("battery_capacity_mah") is not None
                else None
            ),
        )
    else:
        power = None

    return ProductSpec(
        title=str(data.get("title") or "Unnamed Design"),
        description=str(data.get("description") or ""),
        functions=list(data.get("functions") or []),
        interfaces=list(data.get("interfaces") or []),
        power=power,
        environment=data.get("environment") or None,
        target_cost_usd=(
            float(data["target_cost_usd"]) if data.get("target_cost_usd") is not None else None
        ),
        target_qty=(
            int(data["target_qty"]) if data.get("target_qty") is not None else None
        ),
        raw_brief=raw_brief,
    )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the LLM response (handles markdown fences)."""
    # Strip markdown code fences if present
    clean = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()
    # Find the first { ... } block
    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in LLM response:\n{text[:500]}")
    try:
        return json.loads(clean[start:end])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in LLM response: {exc}\n{clean[start:end][:500]}") from exc
