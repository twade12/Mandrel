"""Stub distributor client — deterministic, no API key required.

Used in CI and local dev when Nexar/Octopart credentials are not configured.
Passes the BOM verifier gate but sets sourcing_verified=False on CostedBom
so the human checkpoint can flag that real sourcing hasn't been confirmed.

An MPN containing "UNAVAILABLE" (case-insensitive) simulates an out-of-stock
part, which is useful for writing negative-path tests.
"""

from __future__ import annotations

from mandrel.core.state import DistributorRef, Part


class StubDistributorClient:
    """Deterministic in-memory distributor stub for testing and offline dev."""

    distributor = "stub"

    def __init__(self, always_in_stock: bool = True) -> None:
        self._always_in_stock = always_in_stock

    async def search(self, mpn: str) -> list[DistributorRef]:
        if not self._always_in_stock or "UNAVAILABLE" in mpn.upper():
            return []
        return [DistributorRef(
            distributor="stub",
            sku=f"STUB-{mpn}",
            stock_qty=9999,
            unit_price_usd=round(1.0 + len(mpn) * 0.05, 2),
        )]

    async def confirm_stock(self, sku: str, qty: int = 1) -> bool:
        return self._always_in_stock and "UNAVAILABLE" not in sku.upper()

    async def ground_part(self, part: Part) -> Part:
        refs = await self.search(part.mpn)
        if not refs:
            raise ValueError(
                f"Stub: MPN {part.mpn!r} marked unavailable — cannot ground."
            )
        return part.model_copy(update={
            "in_stock": True,
            "distributor_refs": refs,
            "unit_price_usd": refs[0].unit_price_usd,
        })
