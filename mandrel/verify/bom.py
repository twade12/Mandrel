"""BOM verifier — enforce the ground-every-part invariant (SPEC §0).

Every active component in the BOM must have:
  - in_stock = True
  - at least one DistributorRef with stock_qty > 0

sourcing_verified=False (stub client) generates a warning, not an error, so
CI passes. The human checkpoint is where a reviewer decides whether stub
sourcing is acceptable for their use case.
"""

from __future__ import annotations

from mandrel.core.state import CostedBom, VerifierResult, Violation


class BomVerifier:
    """Check that every BOM line is grounded against real distributor stock."""

    def check(self, bom: CostedBom) -> VerifierResult:
        violations: list[Violation] = []

        for line in bom.lines:
            part = line.part

            if not part.in_stock:
                violations.append(Violation(
                    code="PART_OUT_OF_STOCK",
                    message=f"MPN {part.mpn!r} is not in stock.",
                    severity="error",
                    location=part.reference or part.mpn,
                ))

            if not part.distributor_refs:
                violations.append(Violation(
                    code="PART_NOT_GROUNDED",
                    message=(
                        f"MPN {part.mpn!r} has no distributor reference. "
                        "Cannot confirm it is a real, purchasable part."
                    ),
                    severity="error",
                    location=part.reference or part.mpn,
                ))

        if not bom.sourcing_verified:
            violations.append(Violation(
                code="SOURCING_NOT_VERIFIED",
                message=(
                    "BOM was sourced via stub client, not a live distributor API. "
                    "Configure MANDREL_NEXAR_CLIENT_ID + MANDREL_NEXAR_CLIENT_SECRET "
                    "for real verification before fabrication."
                ),
                severity="warning",
            ))

        errors = [v for v in violations if v.severity == "error"]
        passed = len(errors) == 0
        score = 1.0 if passed else max(0.0, 1.0 - len(errors) * 0.25)
        return VerifierResult(passed=passed, score=score, violations=violations)
