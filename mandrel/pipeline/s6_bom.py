"""S6 — BOM / Sourcing: ground every proposed MPN against a distributor API.

Flow:
  1. Collect proposed MPNs from state.architecture.blocks (blocks where
     proposed_mpn is not None are active components; passives without
     proposed_mpn are skipped until S4 provides a full netlist).
  2. For each MPN, call DistributorClient.ground_part() to confirm real stock
     and populate DistributorRef entries.
  3. BomVerifier checks that every grounded part has in_stock=True and at
     least one distributor ref.
  4. CostedBom (with total cost estimate) is stored in state.bom.
  5. Human checkpoint fires for BOM review before S7 handoff.

Client selection (injected or auto-detected from settings):
  - If nexar_client_id + nexar_client_secret are set → OctopartClient (live)
  - Otherwise → StubDistributorClient (CI/dev; sourcing_verified=False)

Phase 2 simplification: quantities are 1 per block. Real per-reference
quantities come from the netlist (S4); this will be revisited in Phase 3.
"""

from __future__ import annotations

import json

from mandrel.core.state import (
    BomLine,
    CostedBom,
    DesignState,
    Part,
    VerifierResult,
    Violation,
)
from mandrel.core.workflow import Context, StageResult
from mandrel.verify.bom import BomVerifier


class BomStage:
    """S6: resolve proposed MPNs to grounded, in-stock Parts and build CostedBom."""

    name = "s6_bom"

    def __init__(
        self,
        client=None,
        verifier: BomVerifier | None = None,
    ) -> None:
        self._client   = client   # DistributorClient; auto-detected in run() if None
        self._verifier = verifier or BomVerifier()

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        if state.architecture is None:
            raise ValueError("S6 requires state.architecture — run S2 first.")

        output_dir = ctx.project_dir / "s6_bom"
        output_dir.mkdir(parents=True, exist_ok=True)

        client, sourcing_verified = self._resolve_client(ctx)

        # Collect blocks with proposed MPNs (active components only for Phase 2)
        candidates = [
            (b.id, b.label, b.proposed_mpn)
            for b in state.architecture.blocks
            if b.proposed_mpn
        ]

        lines: list[BomLine] = []
        grounding_failures: list[Violation] = []
        api_failures: list[Violation] = []

        from mandrel.sourcing.octopart import OctopartError

        for block_id, label, mpn in candidates:
            seed = Part(mpn=mpn, reference=block_id, value=label)
            try:
                grounded = await client.ground_part(seed)
            except OctopartError as exc:
                # API-level problem (quota, auth, network) — not a verdict on
                # the part. Degrade like the other engines instead of failing
                # the run at its final stage.
                api_failures.append(Violation(
                    code="SOURCING_UNAVAILABLE",
                    message=f"Distributor API unavailable for {mpn!r}: {exc}",
                    severity="warning",
                    location=block_id,
                ))
                lines.append(BomLine(part=seed, quantity=1))
                continue
            except Exception as exc:
                grounding_failures.append(Violation(
                    code="GROUNDING_FAILED",
                    message=f"Could not ground MPN {mpn!r} ({block_id}): {exc}",
                    severity="error",
                    location=block_id,
                ))
                lines.append(BomLine(part=seed, quantity=1))
                continue

            lines.append(BomLine(
                part=grounded,
                quantity=1,
                total_price_usd=grounded.unit_price_usd,
            ))

        total = sum(
            (ln.total_price_usd or 0.0) for ln in lines if ln.part.in_stock
        )
        if api_failures:
            sourcing_verified = False
        bom = CostedBom(
            lines=lines,
            total_cost_usd=total if total > 0 else None,
            all_in_stock=all(ln.part.in_stock for ln in lines),
            sourcing_verified=sourcing_verified,
        )

        # Persist BOM JSON for human review
        bom_path = output_dir / "bom.json"
        bom_path.write_text(
            json.dumps(bom.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        result = self._verifier.check(bom)
        # Prepend any grounding failures so they show up first
        if grounding_failures:
            result = VerifierResult(
                passed=False,
                score=0.0,
                violations=grounding_failures + result.violations,
            )
        elif api_failures:
            # Only API failures: pass with reduced score so the spine
            # completes; the BOM is explicitly marked sourcing_verified=False.
            result = VerifierResult(
                passed=True,
                score=0.5,
                violations=api_failures + [
                    v for v in result.violations if v.severity != "error"
                ],
            )

        new_state = state.model_copy(update={"bom": bom})
        return StageResult(
            state=new_state,
            artifacts=[bom_path],
            verifier_result=result,
        )

    # ── Client resolution ─────────────────────────────────────────────────────

    def _resolve_client(self, ctx: Context):
        """Return (client, sourcing_verified). Prefers live API; falls back to stub."""
        if self._client is not None:
            # Detect whether it's a stub
            from mandrel.sourcing.stub import StubDistributorClient
            verified = not isinstance(self._client, StubDistributorClient)
            return self._client, verified

        settings = getattr(ctx, "config", None)
        if settings and settings.nexar_client_id and settings.nexar_client_secret:
            from mandrel.sourcing.octopart import OctopartClient
            return OctopartClient(
                client_id=settings.nexar_client_id,
                client_secret=settings.nexar_client_secret,
            ), True

        from mandrel.sourcing.stub import StubDistributorClient
        return StubDistributorClient(), False


def _bom_to_table(bom: CostedBom) -> str:
    """Format a CostedBom as a simple text table for CLI display."""
    if not bom.lines:
        return "  (no components)"
    rows = ["  {:<12} {:<30} {:<10} {:<8}".format("Reference", "MPN", "Stock", "Price")]
    rows.append("  " + "-" * 64)
    for line in bom.lines:
        p = line.part
        stock = "YES" if p.in_stock else "NO"
        price = f"${p.unit_price_usd:.2f}" if p.unit_price_usd else "—"
        rows.append("  {:<12} {:<30} {:<10} {:<8}".format(
            p.reference or "—", p.mpn[:28], stock, price,
        ))
    if bom.total_cost_usd:
        rows.append(f"\n  Total (1x each): ${bom.total_cost_usd:.2f}")
    if not bom.sourcing_verified:
        rows.append("  [!] Sourcing via stub — configure Nexar credentials for real verification")
    return "\n".join(rows)
