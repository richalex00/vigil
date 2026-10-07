"""Checks that a model-supplied quote really appears in the datasheet, and locates it.

Quotes shorter than MIN_QUOTE_CHARS are rejected: a bare "3.6 V" would match almost anywhere, so
the model must quote the value together with its label."""
import re
import unicodedata

from .ingest import Page

MIN_QUOTE_CHARS = 6


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def _dehyphen(s: str) -> str:
    return re.sub(r"(?<=[a-z])- (?=[a-z])", "", s)


def find_quote(quote: str, pages: list[Page], page_hint: int | None) -> tuple[int, int, int] | None:
    q = norm(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return None
    for page in sorted(pages, key=lambda p: p.number != page_hint):
        normed = [norm(line) for line in page.lines]
        offsets, pos = [], 0
        for line in normed:
            offsets.append(pos)
            pos += len(line) + 1
        joined = " ".join(normed)
        idx = joined.find(q)
        if idx >= 0:
            end = idx + len(q) - 1
            first = max(k for k, off in enumerate(offsets) if off <= idx)
            last = max(k for k, off in enumerate(offsets) if off <= end)
            return page.number, first + 1, last + 1
        if _dehyphen(q) in _dehyphen(joined):
            stem = _dehyphen(q).split(" ")[0][:4]
            first = next((k for k, ln in enumerate(normed) if stem in ln), 0)
            return page.number, first + 1, min(first + 2, len(normed))
    return None
