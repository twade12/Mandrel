"""Distributor client protocol — ground every part against real stock.

No Part may enter DesignState unless its MPN has been confirmed via one of
these clients. Responses are cached locally per-user; never redistributed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mandrel.core.state import DistributorRef, Part


@runtime_checkable
class DistributorClient(Protocol):
    distributor: str  # "digikey" | "mouser" | "octopart" | "lcsc"

    async def search(self, mpn: str) -> list[DistributorRef]:
        """Search for an MPN; return distributor refs with stock and price."""
        ...

    async def confirm_stock(self, sku: str, qty: int = 1) -> bool:
        """Return True if the SKU has at least qty units available."""
        ...

    async def ground_part(self, part: Part) -> Part:
        """Resolve Part.mpn to real stock; return Part with in_stock=True or raise."""
        ...
