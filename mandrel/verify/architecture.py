"""Structural verifier for the S2 Architecture block diagram.

Deterministic checks only — semantic correctness (right MCU? right peripherals?)
is left to the human checkpoint.
"""

from __future__ import annotations

from mandrel.core.state import Architecture, VerifierResult, Violation


class ArchitectureVerifier:
    """Check structural integrity of an Architecture block diagram."""

    def check(self, arch: Architecture) -> VerifierResult:
        violations: list[Violation] = []
        block_ids = {b.id for b in arch.blocks}

        # 1. No dangling connection endpoints
        for conn in arch.connections:
            for endpoint, attr in [(conn.from_block, "from_block"), (conn.to_block, "to_block")]:
                if endpoint not in block_ids:
                    violations.append(Violation(
                        code="DANGLING_CONNECTION",
                        message=f"Connection {attr}={endpoint!r} references unknown block id.",
                        severity="error",
                        location=f"{conn.from_block}->{conn.to_block}:{conn.signal}",
                    ))

        # 2. No duplicate block IDs
        seen: set[str] = set()
        for block in arch.blocks:
            if block.id in seen:
                violations.append(Violation(
                    code="DUPLICATE_BLOCK_ID",
                    message=f"Block id {block.id!r} appears more than once.",
                    severity="error",
                    location=block.id,
                ))
            seen.add(block.id)

        # 3. At least one MCU block
        has_mcu = any(
            "mcu" in b.id.lower()
            or "mcu" in b.label.lower()
            or "rp2" in b.label.lower()
            or "microcontroller" in b.label.lower()
            for b in arch.blocks
        )
        if not has_mcu and arch.blocks:
            violations.append(Violation(
                code="NO_MCU_BLOCK",
                message=(
                    "Architecture contains no MCU block. "
                    "Add a block whose id or label includes 'mcu'."
                ),
                severity="error",
            ))

        # 4. At least one power-supply block
        has_power = any(
            any(kw in b.label.lower() for kw in ("ldo", "regulator", "power", "3.3v", "5v"))
            for b in arch.blocks
        )
        if not has_power and len(arch.blocks) > 1:
            violations.append(Violation(
                code="NO_POWER_BLOCK",
                message="Architecture has no power-supply block (LDO/regulator).",
                severity="warning",
            ))

        errors = [v for v in violations if v.severity == "error"]
        passed = len(errors) == 0
        score = 1.0 if passed else max(0.0, 1.0 - len(errors) * 0.25)
        return VerifierResult(passed=passed, score=score, violations=violations)
