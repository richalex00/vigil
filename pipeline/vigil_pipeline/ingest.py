"""PDF -> numbered page/line text. Scanned PDFs (no text layer) are detected, never OCR'd (spec §5.1)."""
from dataclasses import dataclass
from pathlib import Path

MIN_TEXT_CHARS = 200


@dataclass
class Page:
    number: int
    lines: list[str]


def pdf_to_pages(path: str | Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append(Page(i + 1, [ln.strip() for ln in text.splitlines() if ln.strip()]))
    return pages


def has_text(pages: list[Page]) -> bool:
    return sum(len(line) for p in pages for line in p.lines) >= MIN_TEXT_CHARS


def render_for_prompt(pages: list[Page]) -> str:
    return "\n".join(f"[p{p.number} L{i + 1}] {line}" for p in pages for i, line in enumerate(p.lines))


def pages_to_dicts(pages: list[Page]) -> list[dict]:
    return [{"number": p.number, "lines": p.lines} for p in pages]
