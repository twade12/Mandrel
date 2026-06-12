"""Nexar / Octopart GraphQL distributor client.

Requires MANDREL_NEXAR_CLIENT_ID and MANDREL_NEXAR_CLIENT_SECRET.
Register at https://nexar.com to get credentials (free tier available).

Authentication: OAuth2 client credentials → bearer token.
API endpoint: https://api.nexar.com/graphql
"""

from __future__ import annotations

import time

import httpx

from mandrel.core.state import DistributorRef, Part

_TOKEN_URL = "https://identity.nexar.com/connect/token"
_GRAPHQL_URL = "https://api.nexar.com/graphql"

# currency is a FIELD of SupPrice, not an argument (verified against the live
# schema); convertedPrice is the USD-converted value.
_SEARCH_QUERY = """
query SearchMPN($q: String!, $limit: Int) {
  supSearch(q: $q, limit: $limit) {
    results {
      part {
        mpn
        manufacturer { name }
        sellers(authorizedOnly: false) {
          company { name }
          offers {
            sku
            inventoryLevel
            prices { price currency quantity convertedPrice convertedCurrency }
          }
        }
      }
    }
  }
}
"""


class OctopartError(RuntimeError):
    """API-level failure (auth, quota, schema, network) — not a sourcing verdict."""


def _usd_price(prices: list[dict]) -> float | None:
    """Lowest-quantity USD price; falls back to the converted price."""
    for p in prices:
        if p.get("currency") == "USD" and p.get("price") is not None:
            return float(p["price"])
    for p in prices:
        if p.get("convertedCurrency") == "USD" and p.get("convertedPrice") is not None:
            return float(p["convertedPrice"])
    return None


class OctopartClient:
    """Live Nexar/Octopart client — requires nexar_client_id + nexar_client_secret."""

    distributor = "octopart"

    def __init__(self, client_id: str, client_secret: str, timeout: int = 15) -> None:
        self._client_id     = client_id
        self._client_secret = client_secret
        self._timeout       = timeout
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if resp.status_code != 200:
            raise OctopartError(
                f"Nexar auth failed ({resp.status_code}): {resp.text[:200]}"
            )
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + body.get("expires_in", 3600)
        return self._token

    # ── DistributorClient protocol ────────────────────────────────────────────

    async def search(self, mpn: str) -> list[DistributorRef]:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _GRAPHQL_URL,
                json={"query": _SEARCH_QUERY, "variables": {"q": mpn, "limit": 10}},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            raise OctopartError(
                f"Nexar GraphQL error ({resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        if "errors" in data:
            raise OctopartError(f"Nexar GraphQL errors: {data['errors']}")

        refs: list[DistributorRef] = []
        for result in data.get("data", {}).get("supSearch", {}).get("results", []):
            part_data = result.get("part", {})
            for seller in part_data.get("sellers", []):
                dist_name = seller.get("company", {}).get("name", "unknown")
                for offer in seller.get("offers", []):
                    sku = offer.get("sku", "")
                    stock = offer.get("inventoryLevel", 0) or 0
                    price = _usd_price(offer.get("prices") or [])
                    refs.append(DistributorRef(
                        distributor=dist_name.lower(),
                        sku=sku,
                        stock_qty=int(stock),
                        unit_price_usd=price,
                    ))
        return refs

    async def confirm_stock(self, sku: str, qty: int = 1) -> bool:
        refs = await self.search(sku)
        return any((r.stock_qty or 0) >= qty for r in refs)

    async def ground_part(self, part: Part) -> Part:
        refs = await self.search(part.mpn)
        in_stock_refs = [r for r in refs if (r.stock_qty or 0) > 0]
        if not in_stock_refs:
            raise ValueError(
                f"MPN {part.mpn!r} found no in-stock offers via Octopart."
            )
        best = min(in_stock_refs, key=lambda r: r.unit_price_usd or 999.0)
        return part.model_copy(update={
            "in_stock": True,
            "distributor_refs": in_stock_refs,
            "unit_price_usd": best.unit_price_usd,
        })
