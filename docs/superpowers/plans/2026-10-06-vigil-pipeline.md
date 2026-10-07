# Vigil Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline Python pipeline. It turns public battery datasheets (PDF) into checked, passport-shaped field data, runs a single-prompt baseline for comparison, scores both against hand-made labels with honest metrics, and exports JSON files for the static demo app (Plan 2).

**Architecture:**
- **Ingest:** PDF → page/line text with pdfplumber.
- **Extract:** Claude returns every field as `value + unit + exact quote + page`, using JSON-schema structured output.
- **Check:** a deterministic checker assigns each field exactly one status (`verified-source`, `review`, `estimate`, `supplier`, `derived`) with a reason.
- **Baseline:** gets the same instructions, but without quotes or checks.
- **Eval:** compares three arms: (A) baseline, (B) quote prompt with checks ignored, (C) quote prompt with checks. B vs C isolates the value of the checks. It reports selective accuracy (precision of accepted fields), errors caught on wrong values only, present and absent fields separately, a blind-labelled subset, and bootstrap confidence intervals by sheet.
- **Contract:** the only interface with the app is the JSON in `pipeline/out/`, plus `schema.json`.

**Tech Stack:** Python 3.14 (venv + pip), `anthropic` SDK, `pdfplumber`, `pytest`. Model `claude-opus-5-5`.

**Spec:** `docs/superpowers/specs/2026-10-06-vigil-demo-design.md`

**Reviewed Tue 6 Oct 2026 by four reviewers** (code correctness, spec coverage, eval methodology, domain). This version includes their fixes.

## Global Constraints

- All pipeline code lives under `pipeline/`. Run commands from `pipeline/` with the venv active (`source .venv/bin/activate`).
- **Model:** `claude-opus-5-5`, a deliberate override of the spec's "current Sonnet". Set `output_config.effort` explicitly to `"medium"` and enable server-side fallbacks (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`). Record the model actually served in each `RunInfo.served_model`. If the checked and baseline runs of one sheet were served by different models, that sheet is marked `failed`.
- **Keep every model call and price inside `vigil_pipeline/extract.py`.** A later switch to a cheaper model (e.g. `gemini-2.5-flash`) should touch only that file, and the eval must be rerun afterwards.
- **Pricing for cost reporting:** Opus 5.5 is $4.00 per 1M input tokens and $20.00 per 1M output tokens.
- **No API key in code.** `Anthropic()` resolves credentials from the environment.
- **"Every field appears exactly once with a status. A run never silently drops a field."** (spec §7) One bad sheet never stops a run.
- **Checking is plain code with no AI.** Confidence comes from the checks.
- **Never plant or hand-edit errors in outputs** (spec §5.3).
- **Labels:** every row needs `checked=y`, every output sheet needs labels for all 20 source fields, and about 8 test sheets are labelled blind (with no prefill). Otherwise the eval refuses to run.
- **Freeze before labelling:** prompts, ranges and the checker are tuned only on the `dev` split (about 5 sheets). The headline numbers come from the `test` split.
- **Tests make no network calls.** The Claude client is always faked.
- **Field list:** 25 fields, 20 of them `source` (scored). It's a passport-shaped slice of the Annex XIII content. Small cells like 18650s are not themselves in passport scope, so the demo says "passport-shaped data".

## Review Focus

1. **PDF text with special characters** (Ω, °, µ, "ﬁ", "−") must still match the model's quote. Pinned by `test_quote_matches_after_unicode_normalisation` in Task 3.
2. **Decimal commas versus thousands separators, and hyphenated ranges.** Pinned by `test_numbers_in_handles_commas_and_ranges` in Task 2.
3. **The model returns a duplicate, unknown or missing field id.** Pinned by `test_to_raw_fields_dedupes_and_drops_unknown` in Task 5 and `test_check_all_covers_every_field_and_derives_energy` in Task 4.
4. **A corrupt PDF, malformed model JSON, or the models served differing between runs** marks that sheet `failed` and the run carries on. Pinned by `test_process_one_survives_corrupt_pdf` and `test_process_one_fails_on_served_model_mismatch` in Task 6.
5. **Label mistakes** (unknown field, duplicate, incomplete sheet, numeric value without a convertible unit, output without labels) make the eval refuse with a clear error. Pinned by the `test_load_labels_*` and `test_evaluate_refuses_*` tests in Task 8.

---

### Task 1: Scaffold, field schema and output contract

**Files:**
- Create: `pipeline/pyproject.toml`, `pipeline/.gitignore`, `pipeline/vigil_pipeline/__init__.py`, `pipeline/tests/__init__.py`
- Create: `pipeline/vigil_pipeline/schema.py`
- Create: `pipeline/vigil_pipeline/contract.py`
- Test: `pipeline/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `Field` (frozen dataclass: `id, label, cluster, kind, vtype, unit, min, max, hint, match`)
  - `FIELDS`, `FIELD_BY_ID`, `EXTRACTABLE` (all kinds except `derived`), `SOURCE_FIELDS`
  - `CLUSTERS`, `CLUSTER_LABELS`
  - `FieldResult` (with `line` and `line_end`), `RunInfo` (with `served_model`), `DatasheetResult.to_dict()`, `STATUSES`

- [ ] **Step 1: Create the project files**

`pipeline/pyproject.toml`:
```toml
[project]
name = "vigil-pipeline"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["anthropic>=0.70", "pdfplumber>=0.11"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`pipeline/.gitignore`:
```
.venv/
__pycache__/
out/
```

Create two empty files: `pipeline/vigil_pipeline/__init__.py` and `pipeline/tests/__init__.py`.

Run: `cd pipeline && python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
Expected: the install succeeds.

- [ ] **Step 2: Write the failing test**

`pipeline/tests/test_schema.py`:
```python
from vigil_pipeline.contract import DatasheetResult, FieldResult, RunInfo, STATUSES
from vigil_pipeline.schema import (CLUSTER_LABELS, CLUSTERS, EXTRACTABLE, FIELD_BY_ID, FIELDS,
                                   SOURCE_FIELDS)


def test_field_ids_unique_and_indexed():
    ids = [f.id for f in FIELDS]
    assert len(ids) == len(set(ids)) == 25
    assert set(FIELD_BY_ID) == set(ids)
    assert len(SOURCE_FIELDS) == 20


def test_fields_are_well_formed():
    assert set(CLUSTER_LABELS) == set(CLUSTERS)
    for f in FIELDS:
        assert f.cluster in CLUSTERS
        assert f.kind in ("source", "derived", "estimate", "supplier")
        assert f.match in ("exact", "tokens")
        if f.vtype == "number":
            assert f.unit and f.min is not None and f.max is not None and f.min < f.max
        else:
            assert f.unit is None


def test_extractable_excludes_derived():
    assert all(f.kind != "derived" for f in EXTRACTABLE)
    assert FIELD_BY_ID["rated_energy"] not in EXTRACTABLE
    assert "production estimate" in FIELD_BY_ID["carbon_footprint"].label


def test_datasheet_result_to_dict_shape():
    fr = FieldResult(id="weight", label="Weight", cluster="general", kind="source",
                     status="verified-source", value=49.0, unit="g", raw_value="49", raw_unit="g",
                     quote="Weight 49 g max", page=1, line=4, line_end=4)
    run = RunInfo(method="checked", model="claude-opus-5-5", served_model="claude-opus-5-5",
                  elapsed_s=3.2, input_tokens=1000, output_tokens=500, cost_usd=0.014)
    d = DatasheetResult(id="x", title="X", source_file="x.pdf",
                        pages=[{"number": 1, "lines": ["Weight 49 g max"]}], fields=[fr], run=run).to_dict()
    assert d["fields"][0]["status"] in STATUSES and d["fields"][0]["line_end"] == 4
    assert d["run"]["served_model"] == "claude-opus-5-5"
    assert d["contract_version"] == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil_pipeline.contract'`

- [ ] **Step 4: Implement `schema.py` and `contract.py`**

`pipeline/vigil_pipeline/schema.py`:
```python
"""A passport-shaped slice of the EU battery passport (Reg. 2023/1542 Annex XIII), 25 fields.

Not every field is passport-mandated (e.g. max discharge current is a datasheet field kept for
context; UN 38.3 / EU declaration sit in conformity documentation)."""
from dataclasses import dataclass
from typing import Literal

Kind = Literal["source", "derived", "estimate", "supplier"]
VType = Literal["number", "text"]
Match = Literal["exact", "tokens"]

CLUSTERS = ("general", "performance", "materials", "carbon", "circularity", "compliance")
CLUSTER_LABELS = {
    "general": "General information",
    "performance": "Performance & durability",
    "materials": "Materials & composition",
    "carbon": "Carbon footprint",
    "circularity": "Circularity & safety",
    "compliance": "Compliance",
}


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    cluster: str
    kind: Kind
    vtype: VType
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    hint: str = ""
    match: Match = "exact"  # text fields only: exact (identifiers) or tokens (free text)


FIELDS: tuple[Field, ...] = (
    Field("manufacturer", "Manufacturer", "general", "source", "text"),
    Field("model_identifier", "Model identifier", "general", "source", "text"),
    Field("battery_category", "Battery category", "general", "source", "text",
          hint="portable, LMT, EV, industrial or SLI - only if the document states it"),
    Field("chemistry", "Chemistry", "general", "source", "text",
          hint="cathode chemistry, e.g. NMC, LFP, NCA"),
    Field("weight", "Weight", "general", "source", "number", "g", 1, 1_500_000),
    Field("manufacturing_date", "Manufacturing date", "general", "supplier", "text"),
    Field("rated_capacity", "Rated capacity", "performance", "source", "number", "Ah", 0.01, 2000,
          hint="nominal or rated capacity, not minimum capacity"),
    Field("nominal_voltage", "Nominal voltage", "performance", "source", "number", "V", 1, 1000),
    Field("min_voltage", "Minimum voltage", "performance", "source", "number", "V", 0.5, 1000,
          hint="discharge cut-off voltage"),
    Field("max_voltage", "Maximum voltage", "performance", "source", "number", "V", 1, 1000,
          hint="charge (end) voltage"),
    Field("max_discharge_current", "Max continuous discharge current", "performance", "source",
          "number", "A", 0.01, 5000),
    Field("internal_resistance", "Internal resistance", "performance", "source", "number",
          "mΩ", 0.01, 100_000, hint="AC or DC impedance; the quote must show which"),
    Field("expected_lifetime_cycles", "Expected lifetime", "performance", "source", "number",
          "cycles", 10, 100_000),
    Field("capacity_threshold_pct", "Capacity threshold for exhaustion", "performance", "source",
          "number", "%", 50, 100, hint="end-of-life capacity percentage the cycle life is rated to"),
    Field("operating_temp_min", "Min operating temperature", "performance", "source", "number",
          "°C", -60, 30, hint="lowest discharge temperature"),
    Field("operating_temp_max", "Max operating temperature", "performance", "source", "number",
          "°C", 20, 120, hint="highest discharge temperature"),
    Field("rated_energy", "Rated energy", "performance", "derived", "number", "Wh", 0.01, 2_000_000),
    Field("hazardous_substances", "Hazardous substances", "materials", "source", "text", match="tokens"),
    Field("critical_raw_materials", "Critical raw materials content", "materials", "supplier", "text",
          match="tokens"),
    Field("recycled_content_share", "Recycled content share", "materials", "supplier", "text",
          match="tokens"),
    Field("carbon_footprint", "Carbon footprint (production estimate)", "carbon", "estimate", "number",
          "kg CO2e/kWh", 10, 500),
    Field("dismantling_info", "Dismantling & removal information", "circularity", "source", "text",
          match="tokens"),
    Field("extinguishing_agent", "Extinguishing agent", "circularity", "source", "text", match="tokens"),
    Field("un38_3_test", "UN 38.3 transport test", "compliance", "source", "text", match="tokens"),
    Field("eu_declaration_ref", "EU declaration of conformity", "compliance", "source", "text",
          match="tokens"),
)

FIELD_BY_ID: dict[str, Field] = {f.id: f for f in FIELDS}
EXTRACTABLE: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind != "derived")
SOURCE_FIELDS: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind == "source")
```

`pipeline/vigil_pipeline/contract.py`:
```python
"""The JSON contract between the pipeline and the demo app. Plan 2 mirrors these shapes in TypeScript."""
from dataclasses import asdict, dataclass
from typing import Literal

Status = Literal["verified-source", "review", "estimate", "supplier", "derived"]
STATUSES = ("verified-source", "review", "estimate", "supplier", "derived")


@dataclass
class FieldResult:
    id: str
    label: str
    cluster: str
    kind: str
    status: Status
    value: float | str | None
    unit: str | None
    raw_value: str | None = None
    raw_unit: str | None = None
    quote: str | None = None
    page: int | None = None
    line: int | None = None
    line_end: int | None = None
    reason: str | None = None
    estimate_note: str | None = None


@dataclass
class RunInfo:
    method: Literal["checked", "baseline"]
    model: str
    served_model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class DatasheetResult:
    id: str
    title: str
    source_file: str
    pages: list[dict]
    fields: list[FieldResult]
    run: RunInfo
    contract_version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pipeline/
git commit -m "feat(pipeline): scaffold with field schema and output contract"
```

---

### Task 2: Units and number parsing

**Files:**
- Create: `pipeline/vigil_pipeline/units.py`
- Test: `pipeline/tests/test_units.py`

**Interfaces:**
- Produces:
  - `normalise_unit(raw: str) -> tuple[str, float] | None`
  - `allowed_units(canonical: str) -> list[str]`
  - `numbers_in(text: str) -> list[float]`
  - `parse_number(text: str) -> float | None`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_units.py`:
```python
import pytest

from vigil_pipeline.units import allowed_units, normalise_unit, numbers_in, parse_number


@pytest.mark.parametrize("raw,expected", [
    ("mAh", ("Ah", 0.001)), ("Ah", ("Ah", 1.0)), ("V", ("V", 1.0)), ("mV", ("V", 0.001)),
    ("A", ("A", 1.0)), ("mA", ("A", 0.001)), ("Wh", ("Wh", 1.0)), ("kWh", ("Wh", 1000.0)),
    ("mΩ", ("mΩ", 1.0)), ("mohm", ("mΩ", 1.0)), ("Ω", ("mΩ", 1000.0)), ("g", ("g", 1.0)),
    ("kg", ("g", 1000.0)), ("%", ("%", 1.0)), ("°C", ("°C", 1.0)), ("℃", ("°C", 1.0)),
    ("degC", ("°C", 1.0)), ("cycles", ("cycles", 1.0)), (" m A h ", ("Ah", 0.001)),
])
def test_normalise_unit(raw, expected):
    assert normalise_unit(raw) == expected


def test_normalise_unit_unknown():
    assert normalise_unit("furlongs") is None
    assert normalise_unit("") is None


def test_allowed_units():
    assert allowed_units("Ah") == ["Ah", "mAh"]
    assert allowed_units("mΩ") == ["mΩ", "Ω"]
    assert allowed_units("kg CO2e/kWh") == []


def test_numbers_in_handles_commas_and_ranges():
    assert numbers_in("3,500 mAh") == [3500.0]
    assert numbers_in("3,6 V") == [3.6]
    assert numbers_in("2.5-4.2V") == [2.5, 4.2]
    assert numbers_in("−20 ~ 60 °C") == [-20.0, 60.0]
    assert numbers_in("-20°C to 60°C") == [-20.0, 60.0]
    assert numbers_in("1 000 cycles") == [1000.0]
    assert numbers_in("no numbers") == []


def test_parse_number():
    assert parse_number("3500") == 3500.0
    assert parse_number("approx. 3.635") == 3.635
    assert parse_number("n/a") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_units.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `units.py`**

`pipeline/vigil_pipeline/units.py`:
```python
"""Unit normalisation and number parsing for datasheet values."""
import re
import unicodedata

_UNITS: dict[str, tuple[str, float]] = {
    "ah": ("Ah", 1.0), "mah": ("Ah", 0.001),
    "v": ("V", 1.0), "mv": ("V", 0.001),
    "a": ("A", 1.0), "ma": ("A", 0.001),
    "wh": ("Wh", 1.0), "kwh": ("Wh", 1000.0),
    "mω": ("mΩ", 1.0), "mohm": ("mΩ", 1.0), "milliohm": ("mΩ", 1.0),
    "ω": ("mΩ", 1000.0), "ohm": ("mΩ", 1000.0),
    "g": ("g", 1.0), "kg": ("g", 1000.0),
    "%": ("%", 1.0),
    "°c": ("°C", 1.0), "c": ("°C", 1.0), "degc": ("°C", 1.0),
    "cycles": ("cycles", 1.0), "cycle": ("cycles", 1.0), "cyc": ("cycles", 1.0),
}

# Units offered in the demo's "fix" input, in display order (canonical first).
_DISPLAY = {"ah": "Ah", "mah": "mAh", "v": "V", "mv": "mV", "a": "A", "ma": "mA", "wh": "Wh",
            "kwh": "kWh", "mω": "mΩ", "ω": "Ω", "g": "g", "kg": "kg", "%": "%", "°c": "°C",
            "cycles": "cycles"}

# A minus sign only counts when it isn't joining two numbers ("2.5-4.2" is a range).
_NUM_RE = re.compile(r"(?:(?<![\w.])-)?\d+(?:[ ,]\d{3})*(?:[.,]\d+)?")
_PARTS_RE = re.compile(r"(-?\d+(?:[ ,]\d{3})*)([.,]\d+)?")


def normalise_unit(raw: str) -> tuple[str, float] | None:
    key = unicodedata.normalize("NFKC", raw or "").casefold()
    key = re.sub(r"\s+", "", key).replace("º", "°")
    return _UNITS.get(key)


def allowed_units(canonical: str) -> list[str]:
    return [label for key, label in _DISPLAY.items() if _UNITS[key][0] == canonical]


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-").replace("–", "-")


def _to_float(token: str) -> float:
    m = _PARTS_RE.fullmatch(token)
    integer = re.sub(r"[ ,]", "", m.group(1))
    frac = (m.group(2) or "").replace(",", ".")
    return float(integer + frac)


def numbers_in(text: str) -> list[float]:
    return [_to_float(t) for t in _NUM_RE.findall(_clean(text))]


def parse_number(text: str) -> float | None:
    nums = numbers_in(text)
    return nums[0] if nums else None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_units.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/vigil_pipeline/units.py pipeline/tests/test_units.py
git commit -m "feat(pipeline): unit normalisation and number parsing"
```

---

### Task 3: PDF ingest and quote matching

**Files:**
- Create: `pipeline/vigil_pipeline/ingest.py`
- Create: `pipeline/vigil_pipeline/quotes.py`
- Test: `pipeline/tests/test_quotes.py`

**Interfaces:**
- Produces:
  - `Page` (dataclass `number, lines`)
  - `pdf_to_pages(path)`, `has_text(pages)`, `render_for_prompt(pages)`, `pages_to_dicts(pages)`
  - `norm(s)`, `MIN_QUOTE_CHARS = 6`
  - `find_quote(quote, pages, page_hint) -> tuple[int, int, int] | None`, which returns 1-indexed `(page, line, line_end)`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_quotes.py`:
```python
from vigil_pipeline.ingest import Page, has_text, pages_to_dicts, render_for_prompt
from vigil_pipeline.quotes import find_quote, norm

PAGES = [
    Page(1, ["LG Chem", "Model INR18650 MJ1", "Nominal Capacity  3500 mAh", "Weight 49.0 g max"]),
    Page(2, ["Operating temperature −20 ℃ ~ 60 ℃", "AC impedance ≤ 35 mΩ", "manu-",
             "facturer: LG Energy Solution", "Charge voltage", "4.2 V"]),
]


def test_find_quote_exact_and_whitespace():
    assert find_quote("Nominal Capacity 3500 mAh", PAGES, 1) == (1, 3, 3)


def test_quote_matches_after_unicode_normalisation():
    assert find_quote("Operating temperature -20 °C ~ 60 °C", PAGES, 2) == (2, 1, 1)
    assert find_quote("ac impedance ≤ 35 mΩ", PAGES, 2) == (2, 2, 2)


def test_find_quote_falls_back_to_other_pages():
    assert find_quote("Weight 49.0 g max", PAGES, 7) == (1, 4, 4)
    assert find_quote("Weight 49.0 g max", PAGES, None) == (1, 4, 4)


def test_find_quote_spanning_two_lines():
    assert find_quote("Charge voltage 4.2 V", PAGES, 2) == (2, 5, 6)


def test_find_quote_across_hyphenated_line_break():
    assert find_quote("manufacturer: LG Energy Solution", PAGES, 2) == (2, 3, 4)


def test_find_quote_rejects_invented_and_short_quotes():
    assert find_quote("Nominal Capacity 3600 mAh", PAGES, 1) is None
    assert find_quote("4.2 V", PAGES, 2) is None


def test_norm_casefolds_and_collapses():
    assert norm("  Nominal\tCAPACITY  ") == "nominal capacity"


def test_has_text_and_render():
    assert not has_text([Page(1, ["x"])])
    assert has_text([Page(1, ["word " * 60])])
    assert render_for_prompt(PAGES).splitlines()[0] == "[p1 L1] LG Chem"
    assert pages_to_dicts(PAGES)[1]["number"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_quotes.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `ingest.py` and `quotes.py`**

`pipeline/vigil_pipeline/ingest.py`:
```python
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
```

`pipeline/vigil_pipeline/quotes.py`:
```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_quotes.py -v`
Expected: all pass

- [ ] **Step 5: Smoke-test ingest on one real PDF**

Download one public cell datasheet (e.g. a Molicel or Samsung 21700 spec sheet) into `pipeline/datasheets/`, then run:
```bash
python -c "from vigil_pipeline.ingest import *; p=pdf_to_pages('datasheets/<file>.pdf'); print(has_text(p)); print(render_for_prompt(p)[:800])"
```
Expected: `True`, then readable numbered lines.

- [ ] **Step 6: Commit**

```bash
git add pipeline/vigil_pipeline/ingest.py pipeline/vigil_pipeline/quotes.py pipeline/tests/test_quotes.py
git commit -m "feat(pipeline): PDF ingest and quote matching"
```

---

### Task 4: Estimates and the checker

**Files:**
- Create: `pipeline/vigil_pipeline/estimates.py`
- Create: `pipeline/vigil_pipeline/check.py`
- Test: `pipeline/tests/test_check.py`

**Interfaces:**
- Consumes:
  - `FIELDS`, `FIELD_BY_ID`, `Field`, `FieldResult` (Task 1)
  - `normalise_unit`, `numbers_in`, `parse_number` (Task 2)
  - `Page`, `find_quote`, `norm` (Task 3)
- Produces:
  - `RawField` (`id, found, value, unit, quote, page`)
  - `check_field(field, raw, pages) -> FieldResult`
  - `check_all(raw: dict[str, RawField], pages) -> list[FieldResult]`, one result per item in `FIELDS`, in `FIELDS` order
  - `CARBON_ESTIMATE`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_check.py`:
```python
from vigil_pipeline.check import RawField, check_all, check_field
from vigil_pipeline.ingest import Page
from vigil_pipeline.schema import FIELD_BY_ID, FIELDS

PAGES = [Page(1, [
    "Model INR18650 MJ1", "Nominal Capacity 3500 mAh", "Nominal Voltage 3.635 V",
    "Charge voltage 4.2 V", "Cathode: NMC", "Weight 49.0 g max",
])]


def raw(id, value, unit="", quote="", page=1, found=True):
    return RawField(id=id, found=found, value=value, unit=unit, quote=quote, page=page)


def test_verified_number_is_converted():
    r = check_field(FIELD_BY_ID["rated_capacity"],
                    raw("rated_capacity", "3500", "mAh", "Nominal Capacity 3500 mAh"), PAGES)
    assert (r.status, r.value, r.unit, r.page, r.line, r.line_end, r.reason) == \
        ("verified-source", 3.5, "Ah", 1, 2, 2, None)


def test_invented_quote_goes_to_review_but_keeps_value():
    r = check_field(FIELD_BY_ID["rated_capacity"],
                    raw("rated_capacity", "3600", "mAh", "Nominal Capacity 3600 mAh"), PAGES)
    assert r.status == "review" and r.reason == "quote not found in document" and r.value == 3.6


def test_value_not_in_quote():
    r = check_field(FIELD_BY_ID["nominal_voltage"],
                    raw("nominal_voltage", "3.7", "V", "Nominal Voltage 3.635 V"), PAGES)
    assert r.status == "review" and r.reason == "value not in quote"


def test_unconvertible_unit():
    r = check_field(FIELD_BY_ID["weight"], raw("weight", "49.0", "oz", "Weight 49.0 g max"), PAGES)
    assert r.status == "review" and r.reason.startswith("unit 'oz'")


def test_out_of_range():
    r = check_field(FIELD_BY_ID["max_voltage"], raw("max_voltage", "4.2", "mV", "Charge voltage 4.2 V"), PAGES)
    assert r.status == "review" and r.reason == "value outside plausible range"


def test_text_field_verified_and_value_in_quote():
    ok = check_field(FIELD_BY_ID["chemistry"], raw("chemistry", "NMC", quote="Cathode: NMC"), PAGES)
    bad = check_field(FIELD_BY_ID["chemistry"], raw("chemistry", "LFP", quote="Cathode: NMC"), PAGES)
    assert ok.status == "verified-source" and ok.value == "NMC"
    assert bad.status == "review" and bad.reason == "value not in quote"


def test_not_found_statuses_by_kind():
    assert check_field(FIELD_BY_ID["manufacturer"], None, PAGES).reason == "not found in document"
    assert check_field(FIELD_BY_ID["manufacturer"], None, PAGES).status == "review"
    assert check_field(FIELD_BY_ID["recycled_content_share"], None, PAGES).status == "supplier"
    est = check_field(FIELD_BY_ID["carbon_footprint"], raw("carbon_footprint", "", found=False), PAGES)
    assert est.status == "estimate" and est.value == 83.5
    assert "IVL" in est.estimate_note and "cradle-to-gate" in est.estimate_note


def test_check_all_covers_every_field_and_derives_energy():
    results = check_all({
        "rated_capacity": raw("rated_capacity", "3500", "mAh", "Nominal Capacity 3500 mAh"),
        "nominal_voltage": raw("nominal_voltage", "3.635", "V", "Nominal Voltage 3.635 V"),
        "bogus_id": raw("bogus_id", "x"),
    }, PAGES)
    assert [r.id for r in results] == [f.id for f in FIELDS]
    energy = next(r for r in results if r.id == "rated_energy")
    assert energy.status == "derived" and abs(energy.value - 12.7225) < 1e-6


def test_derived_depends_on_unverified():
    results = check_all({
        "rated_capacity": raw("rated_capacity", "3600", "mAh", "Nominal Capacity 3600 mAh"),
        "nominal_voltage": raw("nominal_voltage", "3.635", "V", "Nominal Voltage 3.635 V"),
    }, PAGES)
    energy = next(r for r in results if r.id == "rated_energy")
    assert energy.status == "review" and energy.reason == "depends on unverified field"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_check.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `estimates.py` and `check.py`**

`pipeline/vigil_pipeline/estimates.py`:
```python
"""Industry-average defaults for estimable fields (spec §5.1 'estimate').

Source: IVL Swedish Environmental Research Institute, report C444 (Emilsson & Dahllöf, 2019),
"Lithium-Ion Vehicle Battery Production" - 61-106 kg CO2e per kWh of battery capacity, production
only (cradle-to-gate). The regulation's passport carbon footprint is a life-cycle value with a
different functional unit, so this is shown as a labelled stand-in, never as a declared value."""
CARBON_ESTIMATE = {
    "value": 83.5,
    "unit": "kg CO2e/kWh",
    "note": ("Estimate, not a declared value: midpoint of the 61-106 kg CO2e per kWh of battery "
             "capacity range for production (cradle-to-gate) in IVL report C444 (2019). The "
             "passport's own figure is a life-cycle value."),
}
```

`pipeline/vigil_pipeline/check.py`:
```python
"""Deterministic checks (no AI). Every field ends with exactly one status (spec §5.1, §7)."""
import math
from dataclasses import dataclass

from .contract import FieldResult
from .estimates import CARBON_ESTIMATE
from .ingest import Page
from .quotes import find_quote, norm
from .schema import FIELDS, Field
from .units import normalise_unit, numbers_in, parse_number


@dataclass
class RawField:
    id: str
    found: bool
    value: str
    unit: str
    quote: str
    page: int | None


def _base(field: Field, **kw) -> FieldResult:
    return FieldResult(id=field.id, label=field.label, cluster=field.cluster, kind=field.kind,
                       unit=field.unit, **kw)


def check_field(field: Field, raw: RawField | None, pages: list[Page]) -> FieldResult:
    if raw is None or not raw.found:
        if field.kind == "estimate":
            return _base(field, status="estimate", value=CARBON_ESTIMATE["value"],
                         estimate_note=CARBON_ESTIMATE["note"], reason="not in document; industry average")
        if field.kind == "supplier":
            return _base(field, status="supplier", value=None, reason="not in document; held by supplier")
        return _base(field, status="review", value=None, reason="not found in document")

    loc = find_quote(raw.quote, pages, raw.page)
    page, line, line_end = loc if loc else (raw.page, None, None)
    reasons: list[str] = []
    if loc is None:
        reasons.append("quote not found in document")

    value: float | str | None
    if field.vtype == "text":
        value = raw.value.strip()
        if loc is not None and norm(value) not in norm(raw.quote):
            reasons.append("value not in quote")
    else:
        number = parse_number(raw.value)
        converted = normalise_unit(raw.unit)
        if number is None:
            value = None
            reasons.append("value is not a number")
        elif converted is None or converted[0] != field.unit:
            value = None
            reasons.append(f"unit '{raw.unit}' not convertible to {field.unit}")
        else:
            value = round(number * converted[1], 9)
            if loc is not None and not any(math.isclose(number, n, rel_tol=1e-6) for n in numbers_in(raw.quote)):
                reasons.append("value not in quote")
            if not (field.min <= value <= field.max):
                reasons.append("value outside plausible range")

    return _base(field, status="review" if reasons else "verified-source", value=value,
                 raw_value=raw.value, raw_unit=raw.unit or None, quote=raw.quote, page=page,
                 line=line, line_end=line_end, reason=reasons[0] if reasons else None)


def _derive_energy(field: Field, by_id: dict[str, FieldResult]) -> FieldResult:
    cap, volt = by_id["rated_capacity"], by_id["nominal_voltage"]
    value = None
    if isinstance(cap.value, float) and isinstance(volt.value, float):
        value = round(cap.value * volt.value, 6)
    if cap.status == "verified-source" and volt.status == "verified-source":
        return _base(field, status="derived", value=value, reason=None)
    return _base(field, status="review", value=value, reason="depends on unverified field")


def check_all(raw: dict[str, RawField], pages: list[Page]) -> list[FieldResult]:
    by_id: dict[str, FieldResult] = {}
    for field in FIELDS:
        if field.kind != "derived":
            by_id[field.id] = check_field(field, raw.get(field.id), pages)
    for field in FIELDS:
        if field.kind == "derived":
            by_id[field.id] = _derive_energy(field, by_id)
    return [by_id[f.id] for f in FIELDS]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_check.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/vigil_pipeline/estimates.py pipeline/vigil_pipeline/check.py pipeline/tests/test_check.py
git commit -m "feat(pipeline): deterministic checker with status rules"
```

---

### Task 5: Claude extraction and baseline

**Files:**
- Create: `pipeline/vigil_pipeline/extract.py`
- Test: `pipeline/tests/test_extract.py`

**Interfaces:**
- Consumes:
  - `EXTRACTABLE`, `RunInfo` (Task 1)
  - `Page`, `render_for_prompt` (Task 3)
  - `RawField` (Task 4)
- Produces:
  - `MODEL`, `PRICE_IN_PER_M`, `PRICE_OUT_PER_M`, `ExtractionError`, `CHECKED_SYSTEM`, `BASELINE_SYSTEM`
  - `to_raw_fields(data) -> dict[str, RawField]`
  - `extract_checked(client, pages) -> tuple[dict[str, RawField], RunInfo, str]`
  - `extract_baseline(client, pages) -> tuple[dict[str, RawField], RunInfo, str]`
  - In both, the third element is the raw response text. Baseline `RawField`s have `quote=""` and `page=None`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_extract.py`:
```python
import json
from types import SimpleNamespace

import pytest

from vigil_pipeline.extract import (BASELINE_SYSTEM, CHECKED_SYSTEM, MODEL, ExtractionError,
                                    extract_baseline, extract_checked, to_raw_fields)
from vigil_pipeline.ingest import Page

PAGES = [Page(1, ["Nominal Capacity 3500 mAh"])]


class FakeClient:
    """Stands in for anthropic.Anthropic(). `served` may be a list to vary the model per call."""

    def __init__(self, payload, stop_reason="end_turn", served="claude-opus-5-5"):
        self.calls = []
        text = json.dumps(payload)
        served_list = served if isinstance(served, list) else [served]
        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                model = served_list[min(len(outer.calls), len(served_list)) - 1]
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                    model=model, usage=SimpleNamespace(input_tokens=10_000, output_tokens=2_000))

        self.beta = SimpleNamespace(messages=_Messages())


ONE = {"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh",
                   "quote": "Nominal Capacity 3500 mAh", "page": 1}]}


def test_extract_checked_request_cost_and_served_model():
    client = FakeClient(ONE, served="claude-opus-4-8")
    raw, run, text = extract_checked(client, PAGES)
    call = client.calls[0]
    assert call["model"] == MODEL == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["betas"] == ["server-side-fallback-2026-07-01"] and call["fallbacks"] == "default"
    assert "[p1 L1] Nominal Capacity 3500 mAh" in call["messages"][0]["content"]
    assert raw["rated_capacity"].quote == "Nominal Capacity 3500 mAh"
    assert run.method == "checked" and run.served_model == "claude-opus-4-8"
    assert run.cost_usd == pytest.approx(10_000 * 4 / 1e6 + 2_000 * 20 / 1e6)
    assert json.loads(text) == ONE


def test_baseline_gets_same_rules_but_no_quotes():
    for rule in ("Not in the document", "main/first model", "Never infer"):
        assert rule in CHECKED_SYSTEM and rule in BASELINE_SYSTEM
    client = FakeClient({"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh"}]})
    raw, run, _ = extract_baseline(client, PAGES)
    item = client.calls[0]["output_config"]["format"]["schema"]["properties"]["fields"]["items"]
    assert "quote" not in item["properties"]
    assert raw["rated_capacity"].quote == "" and raw["rated_capacity"].page is None
    assert run.method == "baseline"


def test_to_raw_fields_dedupes_and_drops_unknown():
    data = {"fields": [
        {"id": "weight", "found": True, "value": "49", "unit": "g", "quote": "a", "page": 1},
        {"id": "weight", "found": True, "value": "50", "unit": "g", "quote": "b", "page": 1},
        {"id": "made_up", "found": True, "value": "1", "unit": "", "quote": "c", "page": 1},
    ]}
    out = to_raw_fields(data)
    assert list(out) == ["weight"] and out["weight"].value == "49"


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reason_raises(stop):
    with pytest.raises(ExtractionError):
        extract_checked(FakeClient(ONE, stop_reason=stop), PAGES)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `extract.py`**

`pipeline/vigil_pipeline/extract.py`:
```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_extract.py -v`
Expected: all pass

- [ ] **Step 5: Live check on the smoke-test PDF (costs about $0.05)**

```bash
python -c "
import anthropic
from vigil_pipeline.ingest import pdf_to_pages
from vigil_pipeline.extract import extract_checked
raw, run, _ = extract_checked(anthropic.Anthropic(max_retries=4), pdf_to_pages('datasheets/<file>.pdf'))
print(run); print({k: (v.found, v.value, v.unit) for k, v in raw.items()})"
```
Expected: a `RunInfo` with tokens, cost and served model, plus plausible values. If the SDK rejects `betas=` or `fallbacks=` (an older SDK), run `pip install -U anthropic`. If it still rejects them, pass `extra_body={"fallbacks": "default"}` and `extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"}` on `client.messages.create` instead, and update the test to match.

- [ ] **Step 6: Commit**

```bash
git add pipeline/vigil_pipeline/extract.py pipeline/tests/test_extract.py
git commit -m "feat(pipeline): Claude extract-then-check and baseline calls"
```

---

### Task 6: Run command (whole folder → `out/`)

**Files:**
- Create: `pipeline/vigil_pipeline/sources.py`
- Create: `pipeline/vigil_pipeline/run.py`
- Create: `pipeline/datasheets/sources.csv`
- Test: `pipeline/tests/test_run.py`

**Interfaces:**
- Consumes:
  - `pdf_to_pages`, `has_text`, `pages_to_dicts` (Task 3)
  - `check_all` (Task 4)
  - `extract_checked`, `extract_baseline` (Task 5)
  - `DatasheetResult` (Task 1)
- Produces:
  - `read_sources(path) -> dict[str, dict]`, keyed by id. The CSV columns are `id,title,url,manufacturer,licence_note,split,notes`, where `split` is `dev` or `test`.
  - `process_one(pdf_path, title, client, out_dir, extract_pages=pdf_to_pages) -> "ok" | "skipped" | "failed"`
  - `main(argv=None)`, run as `python -m vigil_pipeline.run [--only ID ...] [--split dev|test]`
  - Output files:
    - `out/<id>.json`
    - `out/baseline/<id>.json`, as `{id, fields: [{id, found, value, unit}], run}`
    - `out/raw/<id>.checked.txt` and `out/raw/<id>.baseline.txt`
    - `out/run-log.json`, appended after every sheet

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_run.py`:
```python
import json

from tests.test_extract import FakeClient
from vigil_pipeline.ingest import Page
from vigil_pipeline.run import process_one
from vigil_pipeline.schema import FIELDS
from vigil_pipeline.sources import read_sources

TEXT_PAGES = [Page(1, ["Nominal Capacity 3500 mAh"] + ["filler text line " * 4] * 5)]
PAYLOAD = {"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh",
                       "quote": "Nominal Capacity 3500 mAh", "page": 1}]}


def _log(out):
    return json.loads((out / "run-log.json").read_text())


def test_process_one_writes_all_outputs(tmp_path):
    out = tmp_path / "out"
    status = process_one(tmp_path / "cell-a.pdf", "Cell A", FakeClient(PAYLOAD), out,
                         extract_pages=lambda p: TEXT_PAGES)
    assert status == "ok"
    data = json.loads((out / "cell-a.json").read_text())
    assert [f["id"] for f in data["fields"]] == [f.id for f in FIELDS]
    assert data["title"] == "Cell A" and data["pages"][0]["lines"][0] == "Nominal Capacity 3500 mAh"
    assert json.loads((out / "baseline" / "cell-a.json").read_text())["run"]["method"] == "baseline"
    assert (out / "raw" / "cell-a.checked.txt").exists() and (out / "raw" / "cell-a.baseline.txt").exists()
    assert _log(out)[-1]["status"] == "ok"


def test_process_one_skips_scanned_pdf(tmp_path):
    out = tmp_path / "out"
    assert process_one(tmp_path / "scan.pdf", "Scan", FakeClient(PAYLOAD), out,
                       extract_pages=lambda p: [Page(1, [])]) == "skipped"
    assert not (out / "scan.json").exists() and _log(out)[-1]["status"] == "skipped"


def test_process_one_marks_failed_on_refusal(tmp_path):
    out = tmp_path / "out"
    assert process_one(tmp_path / "x.pdf", "X", FakeClient(PAYLOAD, stop_reason="refusal"), out,
                       extract_pages=lambda p: TEXT_PAGES) == "failed"
    assert not (out / "x.json").exists()


def test_process_one_survives_corrupt_pdf(tmp_path):
    def boom(_):
        raise ValueError("bad xref table")
    out = tmp_path / "out"
    assert process_one(tmp_path / "bad.pdf", "Bad", FakeClient(PAYLOAD), out, extract_pages=boom) == "failed"
    process_one(tmp_path / "good.pdf", "Good", FakeClient(PAYLOAD), out, extract_pages=lambda p: TEXT_PAGES)
    assert [e["status"] for e in _log(out)] == ["failed", "ok"]


def test_process_one_fails_on_served_model_mismatch(tmp_path):
    client = FakeClient(PAYLOAD, served=["claude-opus-5-5", "claude-opus-4-8"])
    out = tmp_path / "out"
    assert process_one(tmp_path / "m.pdf", "M", client, out, extract_pages=lambda p: TEXT_PAGES) == "failed"
    assert "served models differ" in _log(out)[-1]["detail"]


def test_read_sources(tmp_path):
    p = tmp_path / "sources.csv"
    p.write_text("id,title,url,manufacturer,licence_note,split,notes\na,Cell A,http://x,LG,public,dev,\n")
    assert read_sources(p)["a"]["split"] == "dev"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil_pipeline.run'`

- [ ] **Step 3: Implement `sources.py`, `run.py` and the sources file**

`pipeline/datasheets/sources.csv`. Header only for now; Task 7 fills it in:
```csv
id,title,url,manufacturer,licence_note,split,notes
```

`pipeline/vigil_pipeline/sources.py`:
```python
"""datasheets/sources.csv: id,title,url,manufacturer,licence_note,split(dev|test),notes"""
import csv


def read_sources(path) -> dict[str, dict]:
    with open(path, newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}
```

`pipeline/vigil_pipeline/run.py`:
```python
"""python -m vigil_pipeline.run [--only ID ...] [--split dev|test]  - process datasheets/*.pdf into out/."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

import anthropic

from .check import check_all
from .contract import DatasheetResult
from .extract import extract_baseline, extract_checked
from .ingest import has_text, pages_to_dicts, pdf_to_pages
from .sources import read_sources

ROOT = Path(__file__).resolve().parent.parent
DATASHEETS = ROOT / "datasheets"
OUT = ROOT / "out"


def _log(out_dir: Path, id_: str, status: str, detail: str = "") -> str:
    """Append to out/run-log.json immediately, so a crash or a later --only run never loses history."""
    path = out_dir / "run-log.json"
    entries = json.loads(path.read_text()) if path.exists() else []
    entries.append({"id": id_, "status": status, "detail": detail})
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))
    print(f"{status:8} {id_} {detail}")
    return status


def process_one(pdf_path, title: str, client, out_dir, extract_pages=pdf_to_pages) -> str:
    id_, out_dir = Path(pdf_path).stem, Path(out_dir)
    try:
        pages = extract_pages(pdf_path)
    except Exception as exc:  # corrupt or encrypted PDF: log it and carry on with the next sheet
        return _log(out_dir, id_, "failed", f"unreadable PDF: {type(exc).__name__}: {exc}")
    if not has_text(pages):
        return _log(out_dir, id_, "skipped", "no text layer (scanned PDF?)")
    try:
        raw, run, raw_text = extract_checked(client, pages)
        base_raw, base_run, base_text = extract_baseline(client, pages)
    except Exception as exc:  # API errors, refusals, malformed JSON: one bad sheet never stops the run
        return _log(out_dir, id_, "failed", f"{type(exc).__name__}: {exc}")
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw" / f"{id_}.checked.txt").write_text(raw_text)
    (out_dir / "raw" / f"{id_}.baseline.txt").write_text(base_text)
    if run.served_model != base_run.served_model:
        return _log(out_dir, id_, "failed",
                    f"served models differ: {run.served_model} vs {base_run.served_model}")
    result = DatasheetResult(id=id_, title=title, source_file=Path(pdf_path).name,
                             pages=pages_to_dicts(pages), fields=check_all(raw, pages), run=run)
    (out_dir / "baseline").mkdir(parents=True, exist_ok=True)
    (out_dir / f"{id_}.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    baseline = {"id": id_, "fields": [{"id": r.id, "found": r.found, "value": r.value, "unit": r.unit}
                                      for r in base_raw.values()], "run": asdict(base_run)}
    (out_dir / "baseline" / f"{id_}.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
    return _log(out_dir, id_, "ok", f"${run.cost_usd + base_run.cost_usd:.3f}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="datasheet ids (file stems) to process")
    parser.add_argument("--split", choices=["dev", "test"], help="only process this split")
    args = parser.parse_args(argv)
    sources = read_sources(DATASHEETS / "sources.csv")
    client = anthropic.Anthropic(max_retries=4)
    for pdf in sorted(DATASHEETS.glob("*.pdf")):
        if args.only and pdf.stem not in set(args.only):
            continue
        row = sources.get(pdf.stem)
        if row is None:
            _log(OUT, pdf.stem, "failed", "missing from sources.csv")
            continue
        if args.split and row["split"] != args.split:
            continue
        process_one(pdf, row["title"], client, OUT)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/vigil_pipeline/sources.py pipeline/vigil_pipeline/run.py pipeline/datasheets/sources.csv pipeline/tests/test_run.py
git commit -m "feat(pipeline): run command with per-sheet error isolation and raw responses"
```

---

### Task 7: Datasheets, dev tuning freeze, and labelling (Richard does the hands-on part)

> **AMENDMENT (Wed 7 Oct 2026): model-assisted labelling. This overrides the steps below where they conflict (spec §5.3, revised).** The code for this is written when Task 7 is reached. The interfaces are fixed here:
> - **New `vigil_pipeline/assist.py`:** the second labeller. `python -m vigil_pipeline.assist` labels every non-blind sheet into `labels/assist/<id>.json` (`{"model": ..., "fields": {field_id: {"value", "unit"}}}`). It uses a **different model from the extractor** (default `gemini-2.5-flash`, configurable with `VIGIL_ASSIST_MODEL`; if no Gemini key is available, fall back to a different Claude model and record it). Its prompt is built from `labels/GUIDE.md` alone, and it **never reads `out/`**.
> - **`write_template(..., assist=None, audit_rate=0.15, seed=2026)`:** for non-blind rows, `value`/`unit` come from the assist labeller, and `prefill_value`/`prefill_unit` stay the extractor's output (so the edit rate keeps its meaning). It adds a column `queue`:
>   - `disagree`: the assist and extractor values differ after number/unit normalisation (`parse_number` + `normalise_unit`, else `norm` string compare)
>   - `audit`: a seeded random `audit_rate` share of the agreeing rows
>   - `blind`: blind sheets
>   - empty: anything else, written with `checked=auto`
> - **`pick_blind` default becomes `k=3`.**
> - **Richard checks every row whose `queue` is non-empty** against the PDF and types `y` in `checked`. When he changes an audit row, he types `y` and the edit is detected by comparing `value` against the assist value, which is stored in new columns `assist_value`/`assist_unit`.
> - **Task 8 changes:** `load_labels` accepts `checked` ∈ {`y`, `auto`}. `Label` gains `checked` and `queue`. `eval.json` → `labels` gains `method: "model-assisted"`, the counts `human_checked`/`auto_accepted`/`audited`, and `audit_error_rate` (audited rows where Richard's value differs from the assist value ÷ audited rows, with a bootstrap CI). The headline metrics are unchanged. `blind_subset` is still reported, now from 3 sheets.

**Files:**
- Create: `pipeline/vigil_pipeline/labels.py`
- Create: `pipeline/labels/GUIDE.md`
- Modify: `pipeline/datasheets/sources.csv` (about 30 rows)
- Create: `pipeline/labels/labels.csv` (generated, then checked by hand)
- Test: `pipeline/tests/test_labels.py`

**Interfaces:**
- Consumes: `SOURCE_FIELDS` (Task 1), `read_sources` (Task 6), the `out/<id>.json` files (Task 6)
- Produces:
  - `output_ids(out_dir) -> list[str]`, the sorted stems of `out/*.json` excluding `eval`, `run-log` and `schema`
  - `pick_blind(test_ids, k=8, seed=2026) -> list[str]`
  - `write_template(datasheet_ids, out_dir, dest, blind_ids=()) -> int`
  - The CSV columns `datasheet_id,field_id,value,unit,prefill_value,prefill_unit,blind,checked`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_labels.py`:
```python
import csv
import json

from vigil_pipeline.labels import output_ids, pick_blind, write_template
from vigil_pipeline.schema import SOURCE_FIELDS


def _out(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for name in ("a", "b"):
        (out / f"{name}.json").write_text(json.dumps({"fields": [
            {"id": "weight", "raw_value": "49.0", "raw_unit": "g", "status": "verified-source"},
            {"id": "manufacturer", "raw_value": None, "raw_unit": None, "status": "review"},
        ]}))
    for extra in ("eval", "run-log", "schema"):
        (out / f"{extra}.json").write_text("{}")
    return out


def test_output_ids_ignores_non_sheet_files(tmp_path):
    assert output_ids(_out(tmp_path)) == ["a", "b"]


def test_template_prefills_and_blinds(tmp_path):
    out = _out(tmp_path)
    dest = tmp_path / "labels.csv"
    n = write_template(["a", "b"], out, dest, blind_ids=["b"])
    rows = list(csv.DictReader(dest.open()))
    assert n == len(rows) == 2 * len(SOURCE_FIELDS)
    a_w = next(r for r in rows if r["datasheet_id"] == "a" and r["field_id"] == "weight")
    b_w = next(r for r in rows if r["datasheet_id"] == "b" and r["field_id"] == "weight")
    assert (a_w["value"], a_w["prefill_value"], a_w["blind"], a_w["checked"]) == ("49.0", "49.0", "", "")
    assert (b_w["value"], b_w["prefill_value"], b_w["blind"]) == ("", "", "y")


def test_pick_blind_is_deterministic_and_bounded():
    ids = [f"s{i}" for i in range(25)]
    assert pick_blind(ids) == pick_blind(list(reversed(ids)))
    assert len(pick_blind(ids)) == 8 and len(pick_blind(ids[:3])) == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_labels.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `labels.py` and write the labelling guide**

`pipeline/vigil_pipeline/labels.py`:
```python
"""python -m vigil_pipeline.labels  - write labels/labels.csv as a DRAFT for Richard to check.

Non-blind sheets are pre-filled from the extraction output (prefill_* columns keep the original so
the edit rate can be reported). About 8 test sheets are 'blind': no prefill at all, labelled from the
PDF only, so the headline can be reported on labels the model never influenced (spec §5.3)."""
import csv
import json
import random
from pathlib import Path

from .schema import SOURCE_FIELDS
from .sources import read_sources

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["datasheet_id", "field_id", "value", "unit", "prefill_value", "prefill_unit", "blind", "checked"]
_NOT_SHEETS = {"eval", "run-log", "schema"}


def output_ids(out_dir) -> list[str]:
    return sorted(p.stem for p in Path(out_dir).glob("*.json") if p.stem not in _NOT_SHEETS)


def pick_blind(test_ids, k: int = 8, seed: int = 2026) -> list[str]:
    ids = sorted(test_ids)
    return sorted(random.Random(seed).sample(ids, min(k, len(ids))))


def write_template(datasheet_ids, out_dir, dest, blind_ids=()) -> int:
    rows = []
    for ds in datasheet_ids:
        blind = ds in set(blind_ids)
        prefill = {}
        path = Path(out_dir) / f"{ds}.json"
        if not blind and path.exists():
            prefill = {f["id"]: f for f in json.loads(path.read_text())["fields"]}
        for field in SOURCE_FIELDS:
            p = prefill.get(field.id, {})
            value, unit = p.get("raw_value") or "", p.get("raw_unit") or ""
            rows.append({"datasheet_id": ds, "field_id": field.id, "value": value, "unit": unit,
                         "prefill_value": value, "prefill_unit": unit,
                         "blind": "y" if blind else "", "checked": ""})
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    dest = ROOT / "labels" / "labels.csv"
    if dest.exists():
        raise SystemExit(f"{dest} exists - refusing to overwrite checked labels")
    ids = output_ids(ROOT / "out")
    sources = read_sources(ROOT / "datasheets" / "sources.csv")
    blind = pick_blind([i for i in ids if sources.get(i, {}).get("split") == "test"])
    print(write_template(ids, ROOT / "out", dest, blind), "rows written to", dest, "- blind:", blind)
```

`pipeline/labels/GUIDE.md`:
```markdown
# Labelling guide (read before labelling; keep decisions consistent)

- **One row per field per sheet.** Compare with the PDF only. The prefill is a suggestion, not evidence.
- **Absent:** if the datasheet does not state the field, leave `value` and `unit` empty. Don't infer it,
  don't calculate it, don't use outside knowledge.
- **Variants:** if the sheet lists several models, label the main/first one (the same rule the model gets).
- **Capacity:** use nominal or typical capacity, not minimum.
- **Internal resistance:** label whatever the sheet gives (AC or DC), as written.
- **Temperatures:** the discharge range, not storage or charge.
- **Units:** copy the unit as written (mAh stays mAh). The eval converts.
- **Free-text fields** (hazardous substances, extinguishing agent, dismantling, UN 38.3, EU declaration):
  copy the key phrase, e.g. "dry chemical, CO2", not the whole paragraph.
- **Blind sheets (`blind=y`):** these have no prefill on purpose. Label them first, from the PDF.
- When a row is done, type `y` in `checked`. The eval refuses any row without it.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_labels.py -v`
Expected: PASS

- [ ] **Step 5: Collect about 30 datasheets (Claude can do this; Richard skims the list)**

Download public PDF datasheets into `pipeline/datasheets/`, named `<manufacturer>-<model>.pdf` in lowercase with hyphens. Add one `sources.csv` row per PDF with:
- the exact download URL
- a `licence_note` (e.g. "public manufacturer datasheet, reproduced as extracted text for a non-commercial demo")
- a `split`: mark about 5 of them `dev`, spread across manufacturers, and the rest `test`

The mix:
- About 20 cylindrical cells (18650/21700) from at least 5 manufacturers.
- About 5 LFP cells or prismatic cells.
- About 5 e-bike, LMT or home-storage packs.

If `has_text` rejects a PDF, delete it and record it in `notes`, so that later steps never see it.

- [ ] **Step 6: Tune on dev only, then freeze**

Run: `python -m vigil_pipeline.run --split dev`

Inspect `out/<dev ids>.json` by eye. Adjust prompts, hints or ranges if something is systematically wrong, and repeat until stable. Then **freeze**:
```bash
git add -A && git commit -m "chore(pipeline): freeze prompts, ranges and checker before test run"
```
From here on, don't change `extract.py`, `schema.py`, `check.py` or `quotes.py` before the eval is reported. If you must, rerun everything and say so in the write-up.

- [ ] **Step 7: Run the test split (costs about $2–4)**

Run: `python -m vigil_pipeline.run --split test`
Expected: an `ok` line per sheet. Rerun any `failed` sheet with `--only <id>`.

- [ ] **Step 8: Generate the draft labels, then Richard labels every row**

Run: `python -m vigil_pipeline.labels`

**Richard**, following `labels/GUIDE.md`:
1. Label the blind sheets first, from the PDF only.
2. Then check every prefilled row against its PDF, correcting `value` and `unit` where needed (clear `value` if the field is absent).
3. Type `y` in `checked` on every row.

It takes about 3 hours, and the eval is only honest because of it.

- [ ] **Step 9: Commit**

```bash
git add pipeline/vigil_pipeline/labels.py pipeline/tests/test_labels.py pipeline/labels pipeline/datasheets
git commit -m "feat(pipeline): datasheet set, labelling guide and checked labels"
```

---

### Task 8: Evaluation (three arms, honest metrics)

**Files:**
- Create: `pipeline/vigil_pipeline/evaluate.py`
- Test: `pipeline/tests/test_evaluate.py`

**Interfaces:**
- Consumes:
  - `FIELD_BY_ID`, `FIELDS`, `SOURCE_FIELDS` (Task 1)
  - `normalise_unit`, `parse_number` (Task 2)
  - `norm` (Task 3)
  - `read_sources` (Task 6)
  - `output_ids` (Task 7)
- Produces:
  - `Label` (`value, unit, prefill_value, blind`)
  - `load_labels(path) -> dict[str, dict[str, Label]]`
  - `matches(field, predicted, truth) -> bool`
  - `outcome(field, predicted, truth) -> "correct" | "wrong_value" | "omission" | "hallucination"`
  - `evaluate(out_dir, labels, splits, iters=2000) -> dict`
  - `python -m vigil_pipeline.evaluate`, which writes `out/eval.json`

**Metric definitions** (these go in the case study verbatim):
- **Baseline (A) and quote prompt (B):** accuracy, recall on present fields, hallucination rate on absent fields, and counts of each outcome.
- **Checked (C):**
  - `accepted_precision`: the share of `verified-source` fields that are correct.
  - `coverage`: the share of fields auto-accepted.
  - `review_burden`: the share of fields a human must look at.
  - `produced_wrong`: wrong values plus hallucinations from B.
  - `caught`: how many of `produced_wrong` were flagged `review`.
  - `caught_rate = caught / produced_wrong`. **Omissions are excluded from this rate and reported separately.**
  - `false_alarms`: correct values that were flagged anyway.
- **Confidence intervals:** a 95% bootstrap, resampling whole sheets.
- **Headline:** `test` split only, plus a `blind_subset` block. There are no per-cluster percentages, because the samples are too small.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_evaluate.py`:
```python
import json

import pytest

from vigil_pipeline.evaluate import evaluate, load_labels, matches
from vigil_pipeline.schema import FIELD_BY_ID, SOURCE_FIELDS

HEADER = "datasheet_id,field_id,value,unit,prefill_value,prefill_unit,blind,checked"


def write_labels(path, ds_rows):
    lines = [HEADER]
    for ds, overrides, blind in ds_rows:
        for f in SOURCE_FIELDS:
            value, unit, prefill = overrides.get(f.id, ("", "", ""))
            lines.append(f"{ds},{f.id},{value},{unit},{prefill},{unit if prefill else ''},{'y' if blind else ''},y")
    path.write_text("\n".join(lines) + "\n")


def write_sheet(out, ds, checked_over, baseline_items, served="claude-opus-5-5"):
    (out / "baseline").mkdir(parents=True, exist_ok=True)
    fields = []
    for f in SOURCE_FIELDS:
        status, value, quote = checked_over.get(f.id, ("review", None, None))
        fields.append({"id": f.id, "status": status, "value": value, "quote": quote})
    run = {"cost_usd": 0.05, "elapsed_s": 4.0, "served_model": served}
    (out / f"{ds}.json").write_text(json.dumps({"id": ds, "fields": fields, "run": run}))
    (out / "baseline" / f"{ds}.json").write_text(json.dumps(
        {"id": ds, "fields": baseline_items, "run": {**run, "cost_usd": 0.02, "elapsed_s": 2.0}}))


LABELS_A = {"rated_capacity": ("3500", "mAh", "3500"), "nominal_voltage": ("3.635", "V", "3.7"),
            "weight": ("49.0", "g", "50"), "model_identifier": ("MJ1", "", "")}
CHECKED_A = {
    "rated_capacity": ("verified-source", 3.5, "Nominal Capacity 3500 mAh"),   # correct, accepted
    "nominal_voltage": ("review", 3.7, "Nominal Voltage 3.7 V"),               # wrong value, caught
    "weight": ("verified-source", 50.0, "Weight 50 g"),                        # wrong value, missed
    "manufacturer": ("verified-source", "Made Up Corp", "Made Up Corp"),       # hallucination, missed
}                                                                              # model_identifier: omission
BASELINE_A = [
    {"id": "model_identifier", "found": True, "value": "MJ1", "unit": ""},
    {"id": "manufacturer", "found": True, "value": "LG", "unit": ""},
    {"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh"},
    {"id": "nominal_voltage", "found": True, "value": "3.635", "unit": "V"},
]


def _setup(tmp_path, blind=False):
    out = tmp_path / "out"
    write_sheet(out, "a", CHECKED_A, BASELINE_A)
    labels = tmp_path / "labels.csv"
    write_labels(labels, [("a", LABELS_A, blind)])
    return out, labels


def test_three_arms_and_caught_rate_excludes_omissions(tmp_path):
    out, labels = _setup(tmp_path)
    r = evaluate(out, load_labels(labels), {"a": "test"}, iters=200)
    c = r["checked"]
    assert (c["produced_wrong"], c["caught"], c["omissions"], c["false_alarms"]) == (3, 1, 1, 0)
    assert c["caught_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert c["accepted"] == 3 and c["accepted_precision"] == pytest.approx(1 / 3, abs=1e-4)
    assert c["review_burden"] == pytest.approx(17 / 20)
    b = r["quote_prompt"]
    assert (b["correct"], b["wrong_value"], b["omission"], b["hallucination"]) == (16, 2, 1, 1)
    a = r["baseline"]
    assert (a["correct"], a["omission"], a["hallucination"]) == (18, 1, 1)
    assert a["recall_present"] == 0.75 and a["hallucination_rate_absent"] == 0.0625
    assert [m["field"] for m in r["missed_errors"]] == ["manufacturer", "weight"]
    assert r["ci95"]["accepted_precision"] == [0.3333, 0.3333]
    assert r["labels"]["edit_rate_vs_prefill"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["blind_subset"] is None and r["served_models"] == ["claude-opus-5-5"]
    assert r["cost"]["baseline_s_per_sheet"] == 2.0 and r["cost"]["checked_usd_per_sheet"] == 0.05


def test_blind_subset_reported(tmp_path):
    out, labels = _setup(tmp_path, blind=True)
    r = evaluate(out, load_labels(labels), {"a": "test"}, iters=50)
    assert r["blind_subset"]["datasheets"] == 1


def test_matching_rules():
    assert not matches(FIELD_BY_ID["model_identifier"], "INR18650", "INR18650 MJ1")
    assert matches(FIELD_BY_ID["model_identifier"], "inr18650 mj1", "INR18650 MJ1")
    assert matches(FIELD_BY_ID["extinguishing_agent"], "Use dry chemical or CO2 extinguisher", "dry chemical, CO2")
    assert not matches(FIELD_BY_ID["nominal_voltage"], 3.6, 3.635)
    assert matches(FIELD_BY_ID["nominal_voltage"], 3.636, 3.635)


def test_load_labels_rejects_unknown_field(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text(HEADER + "\na,wieght,49,g,,,,y\n")
    with pytest.raises(ValueError, match="unknown field id 'wieght'"):
        load_labels(p)


def test_load_labels_rejects_unchecked_and_duplicates(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text(HEADER + "\na,weight,49,g,,,,\n")
    with pytest.raises(ValueError, match="not checked"):
        load_labels(p)
    p.write_text(HEADER + "\na,weight,49,g,,,,y\na,weight,50,g,,,,y\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_labels(p)


def test_evaluate_refuses_unlabelled_output(tmp_path):
    out, labels = _setup(tmp_path)
    write_sheet(out, "b", {}, [])
    with pytest.raises(ValueError, match="outputs without labels: \\['b'\\]"):
        evaluate(out, load_labels(labels), {}, iters=10)


def test_evaluate_refuses_incomplete_or_unitless_labels(tmp_path):
    out = tmp_path / "out"
    write_sheet(out, "a", {}, [])
    p = tmp_path / "l.csv"
    p.write_text(HEADER + "\na,weight,49,g,,,,y\n")
    with pytest.raises(ValueError, match="missing fields"):
        evaluate(out, load_labels(p), {}, iters=10)
    write_labels(p, [("a", {"weight": ("49", "", "")}, False)])
    with pytest.raises(ValueError, match="not a number in a unit convertible"):
        evaluate(out, load_labels(p), {}, iters=10)


def test_evaluate_refuses_labels_without_output(tmp_path):
    (tmp_path / "out").mkdir()
    p = tmp_path / "l.csv"
    write_labels(p, [("ghost", {}, False)])
    with pytest.raises(FileNotFoundError, match="ghost"):
        evaluate(tmp_path / "out", load_labels(p), {}, iters=10)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `evaluate.py`**

`pipeline/vigil_pipeline/evaluate.py`:
```python
"""python -m vigil_pipeline.evaluate  - three-arm evaluation against checked labels -> out/eval.json.

Arms: A = baseline prompt, B = quote prompt with checks ignored, C = quote prompt with checks.
B vs C isolates the checks; A vs B isolates the prompt. Only the 20 'source' fields are scored."""
import csv
import json
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .labels import output_ids
from .quotes import norm
from .schema import FIELD_BY_ID, FIELDS, SOURCE_FIELDS
from .sources import read_sources
from .units import normalise_unit, parse_number

ROOT = Path(__file__).resolve().parent.parent
NUM_TOL = 0.005


@dataclass
class Label:
    value: str
    unit: str
    prefill_value: str
    blind: bool


@dataclass
class Rec:
    ds: str
    field: str
    blind: bool
    truth: object
    base: object
    quote_pred: object
    status: str
    quote: str | None


def load_labels(path) -> dict[str, dict[str, Label]]:
    labels: dict[str, dict[str, Label]] = defaultdict(dict)
    with open(path, newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            ds, fid = row["datasheet_id"], row["field_id"]
            if fid not in FIELD_BY_ID:
                raise ValueError(f"unknown field id '{fid}' in labels row {n}")
            if row["checked"].strip().lower() != "y":
                raise ValueError(f"labels row {n} ({ds}/{fid}) not checked")
            if fid in labels[ds]:
                raise ValueError(f"duplicate label {ds}/{fid} in row {n}")
            labels[ds][fid] = Label(row["value"].strip(), row["unit"].strip(),
                                    (row.get("prefill_value") or "").strip(),
                                    (row.get("blind") or "").strip().lower() == "y")
    return dict(labels)


def _truth(field, label: Label, ds: str):
    if label.value == "":
        return None
    if field.vtype == "text":
        return label.value
    number, conv = parse_number(label.value), normalise_unit(label.unit)
    if number is None or conv is None or conv[0] != field.unit:
        raise ValueError(f"label {ds}/{field.id}: '{label.value} {label.unit}' is not a number "
                         f"in a unit convertible to {field.unit}")
    return number * conv[1]


def _baseline_value(field, item):
    if not item or not item.get("found"):
        return None
    value = str(item.get("value", "")).strip()
    if field.vtype == "text":
        return value or None
    number, conv = parse_number(value), normalise_unit(item.get("unit", ""))
    if number is None or conv is None or conv[0] != field.unit:
        return "unparseable"  # a value was produced but is unusable: scored as wrong, not as absent
    return number * conv[1]


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9.]+", norm(s)))


def matches(field, predicted, truth) -> bool:
    if predicted is None or truth is None:
        return predicted is None and truth is None
    if field.vtype == "number":
        return isinstance(predicted, (int, float)) and math.isclose(float(predicted), float(truth), rel_tol=NUM_TOL)
    if field.match == "tokens":
        t, p = _tokens(str(truth)), _tokens(str(predicted))
        return bool(t) and len(t & p) / len(t) >= 0.6 and len(p) <= 3 * len(t) + 3
    return norm(str(predicted)) == norm(str(truth))


def outcome(field, predicted, truth) -> str:
    if matches(field, predicted, truth):
        return "correct"
    if predicted is None:
        return "omission"
    if truth is None:
        return "hallucination"
    return "wrong_value"


def _ratio(a, b):
    return round(a / b, 4) if b else None


def _score(recs: list[Rec], attr: str) -> dict:
    c = {"n": len(recs), "correct": 0, "wrong_value": 0, "omission": 0, "hallucination": 0}
    present = absent = correct_present = 0
    for r in recs:
        o = outcome(FIELD_BY_ID[r.field], getattr(r, attr), r.truth)
        c[o] += 1
        if r.truth is None:
            absent += 1
        else:
            present += 1
            correct_present += o == "correct"
    c.update(present=present, absent=absent, accuracy=_ratio(c["correct"], c["n"]),
             recall_present=_ratio(correct_present, present),
             hallucination_rate_absent=_ratio(c["hallucination"], absent))
    return c


def _checked(recs: list[Rec]) -> dict:
    out = [outcome(FIELD_BY_ID[r.field], r.quote_pred, r.truth) for r in recs]
    accepted = [i for i, r in enumerate(recs) if r.status == "verified-source"]
    produced_wrong = [i for i, o in enumerate(out) if o in ("wrong_value", "hallucination")]
    caught = sum(recs[i].status == "review" for i in produced_wrong)
    return {
        "accepted": len(accepted),
        "accepted_precision": _ratio(sum(out[i] == "correct" for i in accepted), len(accepted)),
        "coverage": _ratio(len(accepted), len(recs)),
        "review_burden": _ratio(sum(r.status == "review" for r in recs), len(recs)),
        "produced_wrong": len(produced_wrong),
        "caught": caught,
        "caught_rate": _ratio(caught, len(produced_wrong)),
        "false_alarms": sum(1 for i, r in enumerate(recs)
                            if r.status == "review" and r.quote_pred is not None and out[i] == "correct"),
        "omissions": out.count("omission"),
    }


def bootstrap_ci(recs: list[Rec], metric, iters: int, seed: int = 0):
    by_sheet: dict[str, list[Rec]] = defaultdict(list)
    for r in recs:
        by_sheet[r.ds].append(r)
    sheets, rng, values = sorted(by_sheet), random.Random(seed), []
    for _ in range(iters):
        sample = [r for s in (rng.choice(sheets) for _ in sheets) for r in by_sheet[s]]
        v = metric(sample)
        if v is not None:
            values.append(v)
    if not values:
        return None
    values.sort()
    return [round(values[int(0.025 * (len(values) - 1))], 4), round(values[int(0.975 * (len(values) - 1))], 4)]


def evaluate(out_dir, labels: dict[str, dict[str, Label]], splits: dict[str, str], iters: int = 2000) -> dict:
    out_dir = Path(out_dir)
    unlabelled = sorted(set(output_ids(out_dir)) - set(labels))
    if unlabelled:
        raise ValueError(f"outputs without labels: {unlabelled}")
    recs: list[Rec] = []
    costs: dict[str, list[float]] = defaultdict(list)
    served: set[str] = set()
    for ds in sorted(labels):
        cp, bp = out_dir / f"{ds}.json", out_dir / "baseline" / f"{ds}.json"
        for p in (cp, bp):
            if not p.exists():
                raise FileNotFoundError(f"no pipeline output for '{ds}': {p}")
        row = labels[ds]
        missing = [f.id for f in SOURCE_FIELDS if f.id not in row]
        if missing:
            raise ValueError(f"labels for '{ds}' missing fields: {missing}")
        checked_doc, base_doc = json.loads(cp.read_text()), json.loads(bp.read_text())
        for doc, key in ((checked_doc, "checked"), (base_doc, "baseline")):
            costs[f"{key}_usd"].append(doc["run"]["cost_usd"])
            costs[f"{key}_s"].append(doc["run"]["elapsed_s"])
            served.add(doc["run"].get("served_model") or doc["run"].get("model", "unknown"))
        checked = {f["id"]: f for f in checked_doc["fields"]}
        base = {f["id"]: f for f in base_doc["fields"]}
        blind = any(label.blind for label in row.values())
        for f in SOURCE_FIELDS:
            c = checked.get(f.id, {})
            recs.append(Rec(ds, f.id, blind, _truth(f, row[f.id], ds), _baseline_value(f, base.get(f.id)),
                            c.get("value"), c.get("status", "review"), c.get("quote")))
    has_test = any(splits.get(r.ds) == "test" for r in recs)
    test = [r for r in recs if splits.get(r.ds) == "test"] if has_test else recs
    blind_recs = [r for r in test if r.blind]
    prefilled = [lab for row in labels.values() for lab in row.values() if not lab.blind and lab.prefill_value]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {
        "split": "test" if has_test else "all",
        "datasheets": len({r.ds for r in test}),
        "fields_scored_per_sheet": len(SOURCE_FIELDS),
        "unscored_fields": [f.id for f in FIELDS if f.kind != "source"],
        "baseline": _score(test, "base"),
        "quote_prompt": _score(test, "quote_pred"),
        "checked": _checked(test),
        "ci95": {
            "baseline_accuracy": bootstrap_ci(test, lambda rs: _score(rs, "base")["accuracy"], iters),
            "accepted_precision": bootstrap_ci(test, lambda rs: _checked(rs)["accepted_precision"], iters),
            "caught_rate": bootstrap_ci(test, lambda rs: _checked(rs)["caught_rate"], iters),
        },
        "blind_subset": None if not blind_recs else {
            "datasheets": len({r.ds for r in blind_recs}),
            "baseline": _score(blind_recs, "base"),
            "checked": _checked(blind_recs),
        },
        "labels": {"edit_rate_vs_prefill": _ratio(sum(lab.value != lab.prefill_value for lab in prefilled), len(prefilled)),
                   "blind_sheets": len({r.ds for r in recs if r.blind})},
        "cost": {f"{k}_per_sheet": mean(v) for k, v in sorted(costs.items())},
        "served_models": sorted(served),
        "missed_errors": [{"datasheet": r.ds, "field": r.field, "predicted": r.quote_pred,
                           "label": r.truth, "quote": r.quote}
                          for r in test
                          if outcome(FIELD_BY_ID[r.field], r.quote_pred, r.truth) in ("wrong_value", "hallucination")
                          and r.status != "review"],
    }


if __name__ == "__main__":
    splits = {i: row["split"] for i, row in read_sources(ROOT / "datasheets" / "sources.csv").items()}
    result = evaluate(ROOT / "out", load_labels(ROOT / "labels" / "labels.csv"), splits)
    (ROOT / "out" / "eval.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k != "missed_errors"}, indent=2))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_evaluate.py -v`
Expected: all pass

- [ ] **Step 5: Run the real eval and read it with Richard**

Run: `python -m vigil_pipeline.evaluate`

Check that `served_models` has exactly one entry. Read `missed_errors`: they become the case study's "failure that got through" (spec §9). Phrase the results like this, with the numbers filled in from `eval.json`:

> On N public datasheets (one labeller; M held out from tuning), quote verification flagged X of Y wrong extractions (95% CI a–b). Accepted fields were P% correct, against Q% for a single-prompt baseline, at K× the cost. It did not catch Z errors, e.g. wrong-variant picks. These results are for this model and document mix.

- [ ] **Step 6: Commit**

```bash
git add pipeline/vigil_pipeline/evaluate.py pipeline/tests/test_evaluate.py
git commit -m "feat(pipeline): three-arm evaluation with selective metrics and bootstrap CIs"
```

---

### Task 9: Export the demo set, schema and final checks

**Files:**
- Create: `pipeline/vigil_pipeline/export.py`
- Test: `pipeline/tests/test_export.py`

**Interfaces:**
- Consumes:
  - `FIELDS`, `CLUSTERS`, `CLUSTER_LABELS` (Task 1)
  - `allowed_units` (Task 2)
  - The `out/` files (Tasks 6 and 8)
- Produces:
  - `schema_json() -> dict`
  - `export(ids, out_dir, dest) -> None`, run as `python -m vigil_pipeline.export ID [ID ...] [--dest DIR]`
  - It writes `dest/<id>.json`, `dest/eval.json`, `dest/index.json` (`[{id, title}]`, in the order given) and `dest/schema.json`. **Plan 2 reads exactly these files.**

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_export.py`:
```python
import json

import pytest

from vigil_pipeline.export import export, schema_json


def test_schema_json_has_everything_the_review_screen_needs():
    s = schema_json()
    assert [c["id"] for c in s["clusters"]][0] == "general" and s["clusters"][0]["label"]
    cap = next(f for f in s["fields"] if f["id"] == "rated_capacity")
    assert cap["allowed_units"] == ["Ah", "mAh"] and cap["min"] == 0.01 and cap["vtype"] == "number"
    carbon = next(f for f in s["fields"] if f["id"] == "carbon_footprint")
    assert carbon["allowed_units"] == ["kg CO2e/kWh"]
    assert next(f for f in s["fields"] if f["id"] == "chemistry")["allowed_units"] == []


def test_export_writes_index_schema_and_eval(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for id_, title in (("a", "Cell A"), ("b", "Cell B")):
        (out / f"{id_}.json").write_text(json.dumps({"id": id_, "title": title, "fields": []}))
    (out / "eval.json").write_text(json.dumps({"datasheets": 2}))
    dest = tmp_path / "data"
    export(["b", "a"], out, dest)
    assert json.loads((dest / "index.json").read_text()) == [{"id": "b", "title": "Cell B"},
                                                             {"id": "a", "title": "Cell A"}]
    assert (dest / "a.json").exists() and json.loads((dest / "eval.json").read_text())["datasheets"] == 2
    assert len(json.loads((dest / "schema.json").read_text())["fields"]) == 25


def test_export_refuses_missing_id(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "eval.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        export(["nope"], tmp_path / "out", tmp_path / "data")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `export.py`**

`pipeline/vigil_pipeline/export.py`:
```python
"""python -m vigil_pipeline.export ID [ID ...] [--dest ../app/public/data]"""
import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .schema import CLUSTER_LABELS, CLUSTERS, FIELDS
from .units import allowed_units

ROOT = Path(__file__).resolve().parent.parent


def schema_json() -> dict:
    return {
        "clusters": [{"id": c, "label": CLUSTER_LABELS[c]} for c in CLUSTERS],
        "fields": [{**asdict(f), "allowed_units": (allowed_units(f.unit) or [f.unit]) if f.unit else []}
                   for f in FIELDS],
    }


def export(ids: list[str], out_dir, dest) -> None:
    out_dir, dest = Path(out_dir), Path(dest)
    missing = [i for i in ids if not (out_dir / f"{i}.json").exists()]
    if missing or not (out_dir / "eval.json").exists():
        raise FileNotFoundError(f"missing outputs: {missing or ['eval.json']}")
    dest.mkdir(parents=True, exist_ok=True)
    index = []
    for i in ids:
        shutil.copyfile(out_dir / f"{i}.json", dest / f"{i}.json")
        index.append({"id": i, "title": json.loads((out_dir / f"{i}.json").read_text())["title"]})
    shutil.copyfile(out_dir / "eval.json", dest / "eval.json")
    (dest / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    (dest / "schema.json").write_text(json.dumps(schema_json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--dest", default=str(ROOT.parent / "app" / "public" / "data"))
    args = parser.parse_args()
    export(args.ids, ROOT / "out", args.dest)
    print("exported", args.ids, "to", args.dest)
```

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 5: Pick the demo set together with Richard (spec §5.3)**

Choose 3–4 ids from the **test** split:
1. One clean sheet, with mostly `verified-source` fields.
2. One where a `review` field is a **real** wrong value that the check caught. To find one, look for sheets with a `caught` field: a record that is `review` and disagrees with its label.
3. One with many `supplier` and `estimate` gaps.

If the check caught nothing real, use the most instructive real `review` field instead, and say so in the case study. **Never edit output values by hand.**

Then run: `python -m vigil_pipeline.export <id1> <id2> <id3>`

- [ ] **Step 6: Verify the carbon estimate citation**

Open IVL report C444 (Emilsson & Dahllöf, 2019) and confirm the 61–106 kg CO2e per kWh range. If it differs, update `estimates.py` and `test_check.py` together, then rerun `pytest`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/vigil_pipeline/export.py pipeline/tests/test_export.py app/public/data
git commit -m "feat(pipeline): export demo datasheets, eval and field schema for the app"
```
