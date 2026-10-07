"""Model calls: extract-then-check (with quotes) and the single-prompt baseline (spec §5.1).

All provider-specific code and prices live here, so swapping to a cheaper model is a one-file change.
Both prompts share the same rules; the only difference is that the checked prompt asks for quotes."""
import json
import time

from .check import RawField
from .contract import RunInfo
from .ingest import Page, render_for_prompt
from .schema import EXTRACTABLE

MODEL = "claude-opus-5-5"
PRICE_IN_PER_M = 4.00
PRICE_OUT_PER_M = 20.00
_IDS = [f.id for f in EXTRACTABLE]


class ExtractionError(Exception):
    pass


_COMMON = """You extract EU battery passport data from one manufacturer datasheet.
Return exactly one entry per field id listed.
"Not in the document" is a valid and expected answer: set found=false and leave the other values
empty. Never infer or calculate a value.
If the datasheet lists several variants, use the main/first model.
value: exactly as written (numbers as written, e.g. "3500"). unit: exactly as written next to the
value (e.g. "mAh"), or "" for text fields."""

CHECKED_SYSTEM = _COMMON + """
quote: a short verbatim span copied from the datasheet containing the value together with its label
(e.g. "Nominal Capacity 3500 mAh"). Copy characters exactly; do not paraphrase or fix typos.
page: the page number from the [pN L…] marker of the quoted line."""

BASELINE_SYSTEM = _COMMON


def _field_brief() -> str:
    lines = []
    for f in EXTRACTABLE:
        unit = f" [{f.unit}]" if f.unit else ""
        hint = f" - {f.hint}" if f.hint else ""
        lines.append(f"- {f.id}: {f.label}{unit}{hint}")
    return "\n".join(lines)


def _schema(with_quotes: bool) -> dict:
    props = {
        "id": {"type": "string", "enum": _IDS},
        "found": {"type": "boolean"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
    }
    if with_quotes:
        props["quote"] = {"type": "string"}
        props["page"] = {"type": "integer"}
    return {
        "type": "object",
        "properties": {"fields": {"type": "array", "items": {
            "type": "object", "properties": props,
            "required": list(props), "additionalProperties": False,
        }}},
        "required": ["fields"],
        "additionalProperties": False,
    }


def to_raw_fields(data: dict) -> dict[str, RawField]:
    out: dict[str, RawField] = {}
    for item in data.get("fields", []):
        fid = item.get("id")
        if fid not in _IDS or fid in out:
            continue
        out[fid] = RawField(id=fid, found=bool(item.get("found")), value=str(item.get("value", "")),
                            unit=str(item.get("unit", "")), quote=str(item.get("quote", "")),
                            page=item.get("page"))
    return out


def _call(client, system: str, pages: list[Page], with_quotes: bool, method: str):
    user = f"Fields:\n{_field_brief()}\n\nDatasheet (each line is prefixed [page line]):\n{render_for_prompt(pages)}"
    start = time.monotonic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema(with_quotes)}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    elapsed = time.monotonic() - start
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise ExtractionError(f"stop_reason={resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        raise ExtractionError("no text block in response")
    usage = resp.usage
    cost = usage.input_tokens * PRICE_IN_PER_M / 1e6 + usage.output_tokens * PRICE_OUT_PER_M / 1e6
    run = RunInfo(method=method, model=MODEL, served_model=getattr(resp, "model", MODEL),
                  elapsed_s=round(elapsed, 2), input_tokens=usage.input_tokens,
                  output_tokens=usage.output_tokens, cost_usd=round(cost, 6))
    return to_raw_fields(json.loads(text)), run, text


def extract_checked(client, pages: list[Page]):
    return _call(client, CHECKED_SYSTEM, pages, with_quotes=True, method="checked")


def extract_baseline(client, pages: list[Page]):
    return _call(client, BASELINE_SYSTEM, pages, with_quotes=False, method="baseline")
