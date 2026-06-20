"""Web source (Tier 2): fetch a URL and reduce it to readable text.

Uses httpx + a minimal stdlib HTML→text reduction (no heavy deps). If a
Firecrawl API key is configured, that cleaner extraction is used instead.
The caller is responsible for passing the correct license for the source.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

from ..base import RawDocument

_SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "svg"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.title = ""
        self._in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "div", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    text = re.sub(r"\n{3,}", "\n\n", "".join(p.parts))
    return p.title.strip(), text.strip()


def from_url(
    url: str,
    license: str,
    timeout: float = 20.0,
    firecrawl_key: str = "",
) -> RawDocument:
    """Fetch and reduce a URL to a RawDocument. `license` must be supplied by
    the caller (you must know the source's license before ingesting it)."""
    if firecrawl_key:
        return _from_firecrawl(url, license, firecrawl_key, timeout)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mandrel-KnowledgeIngest/0.1"})
    resp.raise_for_status()
    title, text = html_to_text(resp.text)
    return RawDocument(content=text, source=url, license=license,
                       title=title or url, kind="web", tier=2)


def _from_firecrawl(url: str, license: str, key: str, timeout: float) -> RawDocument:
    resp = httpx.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown"]},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return RawDocument(
        content=data.get("markdown", ""),
        source=url, license=license,
        title=(data.get("metadata") or {}).get("title", url),
        kind="web", tier=2,
    )
