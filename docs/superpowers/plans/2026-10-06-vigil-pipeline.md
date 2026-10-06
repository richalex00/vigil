# Vigil Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline Python pipeline. It turns public battery datasheets (PDF) into checked Digital Product Passport field data, runs a single-prompt baseline for comparison, scores both against hand-made labels, and exports JSON files for the static demo app (Plan 2).

**Architecture:**
- **Ingest:** PDF → page/line text with pdfplumber.
- **Extract:** Claude returns every field as `value + unit + exact quote + page`, using JSON-schema structured output.
- **Check:** a deterministic checker assigns each field exactly one status (`verified-source`, `review`, `estimate`, `supplier`, `derived`) with a reason.
- **Baseline and eval:** a baseline prompt (no quotes, no checks) and an eval module compare both methods against `labels/labels.csv`.
- **Contract:** the only interface with the app is the JSON in `pipeline/out/`, defined in Task 1.

**Tech Stack:** Python 3.14 (venv + pip), `anthropic` SDK, `pdfplumber`, `pytest`. Model `claude-opus-5-5`.

**Spec:** `docs/superpowers/specs/2026-10-06-vigil-demo-design.md`

## Global Constraints

- All pipeline code lives under `pipeline/`. Run commands from `pipeline/` with the venv active (`source .venv/bin/activate`).
- **Model:** `claude-opus-5-5`, with `output_config.effort` set explicitly to `"medium"` and server-side fallbacks enabled (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`).
- **Pricing for cost reporting:** Opus 5.5 is $4.00 per 1M input tokens and $20.00 per 1M output tokens.
- **No API key in code.** The `Anthropic()` client resolves credentials from the environment (`ANTHROPIC_API_KEY` or an `ant auth login` profile).
- **"Every field in the output appears exactly once with a status. A run never silently drops a field."** (spec §7)
- **Checking is plain code with no AI** (spec §5.1). Confidence comes from the checks, never from the model rating itself.
- **The demo never shows planted errors** (spec §5.3). If no real error is caught, report that honestly.
- **Labels are checked by Richard:** every label row needs `checked=y`, otherwise the eval refuses to run (spec §5.3, to avoid a circular eval).
- **Tests make no network calls.** The Claude client is always faked in tests.
- **Field list:** the 25 fields in Task 1. This is the "about 22" from the spec, finalised here.

## Review Focus

1. **PDF text with special characters** (Ω, °, µ, "ﬁ" ligatures, the "−" minus sign) must still match the model's quote. Pinned by `test_quote_matches_after_unicode_normalisation` in Task 3.
2. **Decimal commas versus thousands separators:** "3,6 V" is 3.6 and "3,500 mAh" is 3500. A range like "2.5-4.2V" must not produce −4.2. Pinned by `test_numbers_in_handles_commas_and_ranges` in Task 2.
3. **The model returns a duplicate, unknown or missing field id.** Keep the first known occurrence, drop unknown ids, and treat a missing id as not found. Pinned by `test_to_raw_fields_dedupes_and_drops_unknown` in Task 5 and `test_check_all_covers_every_field` in Task 4.
4. **The model cites a page number that doesn't exist, or the wrong page.** The quote search must fall back to all pages. Pinned by `test_find_quote_falls_back_to_other_pages` in Task 3.
5. **A typo in a label field id or datasheet id** must make the eval refuse with a clear error, not quietly score fewer fields. Pinned by `test_load_labels_rejects_unknown_field` in Task 8.

---

### Task 1: Scaffold, field schema and output contract

**Files:**
- Create: `pipeline/pyproject.toml`, `pipeline/.gitignore`, `pipeline/vigil_pipeline/__init__.py`
- Create: `pipeline/vigil_pipeline/schema.py`
- Create: `pipeline/vigil_pipeline/contract.py`
- Test: `pipeline/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `Field` (frozen dataclass: `id, label, cluster, kind, vtype, unit, min, max, hint`)
  - `FIELDS: tuple[Field, ...]`, `FIELD_BY_ID: dict[str, Field]`, `EXTRACTABLE: tuple[Field, ...]` (kinds `source`, `supplier`, `estimate`), `SOURCE_FIELDS` (kind `source`)
  - `CLUSTERS`, `STATUSES`
  - `FieldResult` and `RunInfo` dataclasses
  - `DatasheetResult` dataclass with `to_dict() -> dict`

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

`pipeline/vigil_pipeline/__init__.py`: an empty file.

Run:
```bash
cd pipeline && python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
```
Expected: the install succeeds.

- [ ] **Step 2: Write the failing test**

`pipeline/tests/test_schema.py`:
```python
from dataclasses import asdict

from vigil_pipeline.schema import FIELDS, FIELD_BY_ID, EXTRACTABLE, SOURCE_FIELDS, CLUSTERS
from vigil_pipeline.contract import DatasheetResult, FieldResult, RunInfo, STATUSES


def test_field_ids_unique_and_indexed():
    ids = [f.id for f in FIELDS]
    assert len(ids) == len(set(ids)) == 25
    assert set(FIELD_BY_ID) == set(ids)


def test_fields_are_well_formed():
    for f in FIELDS:
        assert f.cluster in CLUSTERS
        assert f.kind in ("source", "derived", "estimate", "supplier")
        if f.vtype == "number":
            assert f.unit and f.min is not None and f.max is not None and f.min < f.max
        else:
            assert f.unit is None


def test_extractable_excludes_derived():
    assert all(f.kind != "derived" for f in EXTRACTABLE)
    assert all(f.kind == "source" for f in SOURCE_FIELDS)
    assert FIELD_BY_ID["rated_energy"] not in EXTRACTABLE


def test_datasheet_result_to_dict_shape():
    fr = FieldResult(id="weight", label="Weight", cluster="general", kind="source",
                     status="verified-source", value=49.0, unit="g", raw_value="49", raw_unit="g",
                     quote="Weight 49 g max", page=1, line=4, reason=None, estimate_note=None)
    run = RunInfo(method="checked", model="claude-opus-5-5", elapsed_s=3.2,
                  input_tokens=1000, output_tokens=500, cost_usd=0.014)
    d = DatasheetResult(id="x", title="X", source_file="x.pdf",
                        pages=[{"number": 1, "lines": ["Weight 49 g max"]}],
                        fields=[fr], run=run).to_dict()
    assert d["fields"][0]["status"] in STATUSES
    assert d["run"]["method"] == "checked"
    assert d["pages"][0]["lines"] == ["Weight 49 g max"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil_pipeline.schema'`

- [ ] **Step 4: Implement `schema.py` and `contract.py`**

`pipeline/vigil_pipeline/schema.py`:
```python
"""The battery-passport field slice used by the demo (spec §5.2), finalised at 25 fields."""
from dataclasses import dataclass
from typing import Literal

Kind = Literal["source", "derived", "estimate", "supplier"]
VType = Literal["number", "text"]

CLUSTERS = ("general", "performance", "materials", "carbon", "circularity", "compliance")


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


FIELDS: tuple[Field, ...] = (
    Field("manufacturer", "Manufacturer", "general", "source", "text"),
    Field("model_identifier", "Model identifier", "general", "source", "text"),
    Field("battery_category", "Battery category", "general", "source", "text",
          hint="portable, LMT, EV, industrial or SLI - only if the document states it"),
    Field("chemistry", "Chemistry", "general", "source", "text",
          hint="cathode chemistry, e.g. NMC, LFP, NCA"),
    Field("weight", "Weight", "general", "source", "number", "g", 1, 500_000),
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
          "mΩ", 0.01, 100_000, hint="AC or DC impedance; say which in the quote"),
    Field("expected_lifetime_cycles", "Expected lifetime", "performance", "source", "number",
          "cycles", 10, 100_000),
    Field("capacity_threshold_pct", "Capacity threshold for exhaustion", "performance", "source",
          "number", "%", 50, 100, hint="end-of-life capacity percentage the cycle life is rated to"),
    Field("operating_temp_min", "Min operating temperature", "performance", "source", "number",
          "°C", -60, 30, hint="lowest discharge temperature"),
    Field("operating_temp_max", "Max operating temperature", "performance", "source", "number",
          "°C", 20, 120, hint="highest discharge temperature"),
    Field("rated_energy", "Rated energy", "performance", "derived", "number", "Wh", 0.01, 2_000_000),
    Field("hazardous_substances", "Hazardous substances", "materials", "source", "text"),
    Field("critical_raw_materials", "Critical raw materials content", "materials", "supplier", "text"),
    Field("recycled_content_share", "Recycled content share", "materials", "supplier", "text"),
    Field("carbon_footprint", "Carbon footprint", "carbon", "estimate", "number",
          "kg CO2e/kWh", 10, 500),
    Field("dismantling_info", "Dismantling & removal information", "circularity", "source", "text"),
    Field("extinguishing_agent", "Extinguishing agent", "circularity", "source", "text"),
    Field("un38_3_test", "UN 38.3 transport test", "compliance", "source", "text"),
    Field("eu_declaration_ref", "EU declaration of conformity", "compliance", "source", "text"),
)

FIELD_BY_ID: dict[str, Field] = {f.id: f for f in FIELDS}
EXTRACTABLE: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind != "derived")
SOURCE_FIELDS: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind == "source")
```

`pipeline/vigil_pipeline/contract.py`:
```python
"""The JSON contract between the pipeline and the demo app. Plan 2 mirrors these shapes in TypeScript."""
from dataclasses import dataclass, asdict, field as dc_field
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
    reason: str | None = None
    estimate_note: str | None = None


@dataclass
class RunInfo:
    method: Literal["checked", "baseline"]
    model: str
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
  - `normalise_unit(raw: str) -> tuple[str, float] | None` returns `(canonical_unit, factor)`
  - `numbers_in(text: str) -> list[float]`
  - `parse_number(text: str) -> float | None`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_units.py`:
```python
import pytest
from vigil_pipeline.units import normalise_unit, numbers_in, parse_number


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
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil_pipeline.units'`

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

# A minus sign only counts when it isn't joining two numbers ("2.5-4.2" is a range).
_NUM_RE = re.compile(r"(?:(?<![\w.])-)?\d+(?:[ ,]\d{3})*(?:[.,]\d+)?")
_PARTS_RE = re.compile(r"(-?\d+(?:[ ,]\d{3})*)([.,]\d+)?")


def normalise_unit(raw: str) -> tuple[str, float] | None:
    key = unicodedata.normalize("NFKC", raw or "").casefold()
    key = re.sub(r"\s+", "", key).replace("º", "°")
    return _UNITS.get(key)


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

Note: NFKC turns "℃" into "°C" and the ohm sign into Greek Ω, so `casefold` gives "ω".

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_units.py -v`
Expected: all pass. If `" m A h "` fails, check that whitespace is stripped before lookup.

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
  - `Page` (dataclass `number: int, lines: list[str]`)
  - `pdf_to_pages(path) -> list[Page]`
  - `has_text(pages) -> bool`
  - `render_for_prompt(pages) -> str`
  - `pages_to_dicts(pages) -> list[dict]`
  - `norm(s: str) -> str`
  - `find_quote(quote: str, pages: list[Page], page_hint: int | None) -> tuple[int, int] | None`, which returns 1-indexed `(page, line)`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_quotes.py`:
```python
from vigil_pipeline.ingest import Page, has_text, render_for_prompt, pages_to_dicts
from vigil_pipeline.quotes import find_quote, norm

PAGES = [
    Page(1, ["LG Chem", "Model INR18650 MJ1", "Nominal Capacity  3500 mAh", "Weight 49.0 g max"]),
    Page(2, ["Operating temperature −20 ℃ ~ 60 ℃", "AC impedance ≤ 35 mΩ", "manu-", "facturer: LG Energy Solution"]),
]


def test_find_quote_exact_and_whitespace():
    assert find_quote("Nominal Capacity 3500 mAh", PAGES, 1) == (1, 3)


def test_quote_matches_after_unicode_normalisation():
    assert find_quote("Operating temperature -20 °C ~ 60 °C", PAGES, 2) == (2, 1)
    assert find_quote("ac impedance ≤ 35 mΩ", PAGES, 2) == (2, 2)


def test_find_quote_falls_back_to_other_pages():
    assert find_quote("Weight 49.0 g max", PAGES, 7) == (1, 4)
    assert find_quote("Weight 49.0 g max", PAGES, None) == (1, 4)


def test_find_quote_across_hyphenated_line_break():
    loc = find_quote("manufacturer: LG Energy Solution", PAGES, 2)
    assert loc is not None and loc[0] == 2


def test_find_quote_rejects_invented_and_tiny_quotes():
    assert find_quote("Nominal Capacity 3600 mAh", PAGES, 1) is None
    assert find_quote("mA", PAGES, 1) is None


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
"""Checks that a model-supplied quote really appears in the datasheet, and locates it."""
import re
import unicodedata

from .ingest import Page

MIN_QUOTE_CHARS = 3


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def _dehyphen(s: str) -> str:
    return re.sub(r"(?<=[a-z])- (?=[a-z])", "", s)


def find_quote(quote: str, pages: list[Page], page_hint: int | None) -> tuple[int, int] | None:
    q = norm(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return None
    ordered = sorted(pages, key=lambda p: p.number != page_hint)
    for page in ordered:
        normed = [norm(line) for line in page.lines]
        offsets, pos = [], 0
        for line in normed:
            offsets.append(pos)
            pos += len(line) + 1
        joined = " ".join(normed)
        idx = joined.find(q)
        if idx >= 0:
            line_idx = max(k for k, off in enumerate(offsets) if off <= idx)
            return page.number, line_idx + 1
        if _dehyphen(q) in _dehyphen(joined):
            first_word = _dehyphen(q).split(" ")[0][:4]
            line_idx = next((k for k, ln in enumerate(normed) if first_word in ln), 0)
            return page.number, line_idx + 1
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_quotes.py -v`
Expected: all pass

- [ ] **Step 5: Smoke-test ingest on one real PDF**

Download any one public cell datasheet into `pipeline/datasheets/`, e.g. a Molicel or Samsung 21700 spec sheet. Then run:
```bash
python -c "from vigil_pipeline.ingest import *; p=pdf_to_pages('datasheets/<file>.pdf'); print(has_text(p)); print(render_for_prompt(p)[:800])"
```
Expected: `True`, then readable numbered lines. Table rows should come out as single lines.

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
  - `FIELDS`, `FIELD_BY_ID`, `Field` (Task 1)
  - `FieldResult` (Task 1)
  - `normalise_unit`, `numbers_in`, `parse_number` (Task 2)
  - `Page`, `find_quote`, `norm` (Task 3)
- Produces:
  - `RawField` (dataclass `id: str, found: bool, value: str, unit: str, quote: str, page: int | None`)
  - `check_field(field, raw: RawField | None, pages) -> FieldResult`
  - `check_all(raw: dict[str, RawField], pages) -> list[FieldResult]`, which returns one result per item in `FIELDS`, in `FIELDS` order
  - `CARBON_ESTIMATE`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_check.py`:
```python
from vigil_pipeline.check import RawField, check_field, check_all
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
    assert (r.status, r.value, r.unit, r.page, r.line, r.reason) == ("verified-source", 3.5, "Ah", 1, 2, None)


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
    assert est.status == "estimate" and est.value == 85.0 and "IVL" in est.estimate_note


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

Source: IVL Swedish Environmental Research Institute (Emilsson & Dahllöf, 2019), Lithium-Ion
Vehicle Battery Production, which reports 61-106 kg CO2e per kWh of battery capacity for
production. The demo uses the midpoint. Verify against the report before publishing (Task 9).
"""
CARBON_ESTIMATE = {
    "value": 85.0,
    "unit": "kg CO2e/kWh",
    "note": "Estimate: midpoint of the 61-106 kg CO2e/kWh production range in IVL (2019).",
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
    page, line = loc if loc else (raw.page, None)
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

    status = "review" if reasons else "verified-source"
    return _base(field, status=status, value=value, raw_value=raw.value, raw_unit=raw.unit or None,
                 quote=raw.quote, page=page, line=line, reason=reasons[0] if reasons else None)


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
  - `EXTRACTABLE`, `FIELD_BY_ID` (Task 1)
  - `RunInfo` (Task 1)
  - `Page`, `render_for_prompt` (Task 3)
  - `RawField` (Task 4)
- Produces:
  - `MODEL`, `PRICE_IN_PER_M`, `PRICE_OUT_PER_M`
  - `ExtractionError(Exception)`
  - `to_raw_fields(data: dict) -> dict[str, RawField]`
  - `extract_checked(client, pages) -> tuple[dict[str, RawField], RunInfo]`
  - `extract_baseline(client, pages) -> tuple[dict[str, RawField], RunInfo]`. Baseline `RawField`s have `quote=""` and `page=None`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_extract.py`:
```python
import json
from types import SimpleNamespace

import pytest

from vigil_pipeline.extract import (MODEL, ExtractionError, extract_baseline, extract_checked,
                                    to_raw_fields)
from vigil_pipeline.ingest import Page

PAGES = [Page(1, ["Nominal Capacity 3500 mAh"])]


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        payload_text = json.dumps(payload)
        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=payload_text)],
                    stop_reason=stop_reason,
                    usage=SimpleNamespace(input_tokens=10_000, output_tokens=2_000),
                )

        self.beta = SimpleNamespace(messages=_Messages())


ONE = {"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh",
                   "quote": "Nominal Capacity 3500 mAh", "page": 1}]}


def test_extract_checked_request_and_cost():
    client = FakeClient(ONE)
    raw, run = extract_checked(client, PAGES)
    call = client.calls[0]
    assert call["model"] == MODEL == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["betas"] == ["server-side-fallback-2026-07-01"] and call["fallbacks"] == "default"
    assert "[p1 L1] Nominal Capacity 3500 mAh" in call["messages"][0]["content"]
    assert raw["rated_capacity"].quote == "Nominal Capacity 3500 mAh"
    assert run.method == "checked" and run.cost_usd == pytest.approx(10_000 * 4 / 1e6 + 2_000 * 20 / 1e6)


def test_extract_baseline_has_no_quotes():
    client = FakeClient({"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh"}]})
    raw, run = extract_baseline(client, PAGES)
    schema_item = client.calls[0]["output_config"]["format"]["schema"]["properties"]["fields"]["items"]
    assert "quote" not in schema_item["properties"]
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
"""Claude calls: extract-then-check (with quotes) and the single-prompt baseline (spec §5.1)."""
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


def _field_brief() -> str:
    lines = []
    for f in EXTRACTABLE:
        unit = f" [{f.unit}]" if f.unit else ""
        hint = f" - {f.hint}" if f.hint else ""
        lines.append(f"- {f.id}: {f.label}{unit}{hint}")
    return "\n".join(lines)


CHECKED_SYSTEM = """You extract EU battery passport data from one manufacturer datasheet.
Return exactly one entry per field id listed. For each field:
- found: true only if the datasheet states the value. "Not in the document" is a valid and expected
  answer - set found=false and leave value, unit and quote empty. Never infer or calculate a value.
- value: the value exactly as written (numbers as written, e.g. "3500").
- unit: the unit exactly as written next to the value (e.g. "mAh"), or "" for text fields.
- quote: a short verbatim span copied from the datasheet that contains the value. Copy characters
  exactly; do not paraphrase or fix typos.
- page: the page number from the [pN L…] marker of the quoted line.
If the datasheet lists several variants, use the main/first model and quote that row."""

BASELINE_SYSTEM = """You extract EU battery passport data from one manufacturer datasheet.
Return exactly one entry per field id listed, with found, value and unit."""


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
    text = next(b.text for b in resp.content if b.type == "text")
    usage = resp.usage
    cost = usage.input_tokens * PRICE_IN_PER_M / 1e6 + usage.output_tokens * PRICE_OUT_PER_M / 1e6
    run = RunInfo(method=method, model=MODEL, elapsed_s=round(elapsed, 2),
                  input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=round(cost, 6))
    return to_raw_fields(json.loads(text)), run


def extract_checked(client, pages: list[Page]):
    return _call(client, CHECKED_SYSTEM, pages, with_quotes=True, method="checked")


def extract_baseline(client, pages: list[Page]):
    raw, run = _call(client, BASELINE_SYSTEM, pages, with_quotes=False, method="baseline")
    return raw, run
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_extract.py -v`
Expected: all pass

- [ ] **Step 5: Live check on the smoke-test PDF (costs about $0.05)**

```bash
python -c "
import anthropic, json
from vigil_pipeline.ingest import pdf_to_pages
from vigil_pipeline.extract import extract_checked
raw, run = extract_checked(anthropic.Anthropic(max_retries=4), pdf_to_pages('datasheets/<file>.pdf'))
print(run); print({k: (v.found, v.value, v.unit) for k, v in raw.items()})"
```
Expected: a `RunInfo` with tokens and cost, and plausible values. If the SDK rejects `fallbacks=` as an unexpected keyword (an older SDK), upgrade with `pip install -U anthropic`, then pass it through `extra_body={"fallbacks": "default"}` and update the test.

- [ ] **Step 6: Commit**

```bash
git add pipeline/vigil_pipeline/extract.py pipeline/tests/test_extract.py
git commit -m "feat(pipeline): Claude extract-then-check and baseline calls"
```

---

### Task 6: Run command (whole folder → `out/`)

**Files:**
- Create: `pipeline/vigil_pipeline/run.py`
- Create: `pipeline/datasheets/sources.csv`
- Test: `pipeline/tests/test_run.py`

**Interfaces:**
- Consumes:
  - `pdf_to_pages`, `has_text`, `pages_to_dicts` (Task 3)
  - `check_all` (Task 4)
  - `extract_checked`, `extract_baseline`, `ExtractionError` (Task 5)
  - `DatasheetResult` (Task 1)
- Produces:
  - `process_one(pdf_path, title, client, out_dir, extract_pages=pdf_to_pages) -> str`, which returns `"ok" | "skipped" | "failed"`
  - `main(argv=None)`, run as `python -m vigil_pipeline.run [--only ID ...]`
  - Output files: `out/<id>.json` (a `DatasheetResult`), `out/baseline/<id>.json` (`{"id", "fields": [{id, found, value, unit}], "run": RunInfo}`), and `out/run-log.json` (a list of `{id, status, detail}`)

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_run.py`:
```python
import json

from tests.test_extract import FakeClient
from vigil_pipeline.ingest import Page
from vigil_pipeline.run import process_one
from vigil_pipeline.schema import FIELDS

TEXT_PAGES = [Page(1, ["Nominal Capacity 3500 mAh"] + ["filler text line " * 4] * 5)]
PAYLOAD = {"fields": [{"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh",
                       "quote": "Nominal Capacity 3500 mAh", "page": 1}]}


def test_process_one_writes_both_outputs(tmp_path):
    status = process_one(tmp_path / "cell-a.pdf", "Cell A", FakeClient(PAYLOAD), tmp_path / "out",
                         extract_pages=lambda p: TEXT_PAGES)
    assert status == "ok"
    data = json.loads((tmp_path / "out" / "cell-a.json").read_text())
    assert [f["id"] for f in data["fields"]] == [f.id for f in FIELDS]
    assert data["title"] == "Cell A" and data["pages"][0]["lines"][0] == "Nominal Capacity 3500 mAh"
    base = json.loads((tmp_path / "out" / "baseline" / "cell-a.json").read_text())
    assert base["run"]["method"] == "baseline"


def test_process_one_skips_scanned_pdf(tmp_path):
    status = process_one(tmp_path / "scan.pdf", "Scan", FakeClient(PAYLOAD), tmp_path / "out",
                         extract_pages=lambda p: [Page(1, [])])
    assert status == "skipped" and not (tmp_path / "out" / "scan.json").exists()


def test_process_one_marks_failed_on_refusal(tmp_path):
    status = process_one(tmp_path / "x.pdf", "X", FakeClient(PAYLOAD, stop_reason="refusal"), tmp_path / "out",
                         extract_pages=lambda p: TEXT_PAGES)
    assert status == "failed" and not (tmp_path / "out" / "x.json").exists()
```

Also create an empty `pipeline/tests/__init__.py` so `from tests.test_extract import FakeClient` resolves.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil_pipeline.run'`

- [ ] **Step 3: Implement `run.py` and the sources file**

`pipeline/datasheets/sources.csv`. Header only for now; Task 7 fills it in:
```csv
id,title,url,manufacturer,notes
```

`pipeline/vigil_pipeline/run.py`:
```python
"""python -m vigil_pipeline.run [--only ID ...]  - process datasheets/*.pdf into out/."""
import argparse
import csv
import json
from pathlib import Path

import anthropic

from .check import check_all
from .contract import DatasheetResult
from .extract import ExtractionError, extract_baseline, extract_checked
from .ingest import has_text, pages_to_dicts, pdf_to_pages

ROOT = Path(__file__).resolve().parent.parent
DATASHEETS = ROOT / "datasheets"
OUT = ROOT / "out"
_LOG: list[dict] = []


def _log(id_: str, status: str, detail: str = "") -> str:
    _LOG.append({"id": id_, "status": status, "detail": detail})
    print(f"{status:8} {id_} {detail}")
    return status


def process_one(pdf_path: Path, title: str, client, out_dir: Path, extract_pages=pdf_to_pages) -> str:
    id_ = Path(pdf_path).stem
    pages = extract_pages(pdf_path)
    if not has_text(pages):
        return _log(id_, "skipped", "no text layer (scanned PDF?)")
    try:
        raw, run = extract_checked(client, pages)
        base_raw, base_run = extract_baseline(client, pages)
    except (anthropic.APIError, ExtractionError) as exc:
        return _log(id_, "failed", f"{type(exc).__name__}: {exc}")
    result = DatasheetResult(id=id_, title=title, source_file=Path(pdf_path).name,
                             pages=pages_to_dicts(pages), fields=check_all(raw, pages), run=run)
    (out_dir / "baseline").mkdir(parents=True, exist_ok=True)
    (out_dir / f"{id_}.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    baseline = {"id": id_, "fields": [{"id": r.id, "found": r.found, "value": r.value, "unit": r.unit}
                                      for r in base_raw.values()], "run": base_run.__dict__}
    (out_dir / "baseline" / f"{id_}.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
    return _log(id_, "ok", f"${run.cost_usd + base_run.cost_usd:.3f}")


def _titles() -> dict[str, str]:
    with open(DATASHEETS / "sources.csv", newline="") as fh:
        return {row["id"]: row["title"] for row in csv.DictReader(fh)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="datasheet ids (file stems) to process")
    args = parser.parse_args(argv)
    titles = _titles()
    client = anthropic.Anthropic(max_retries=4)
    pdfs = sorted(DATASHEETS.glob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if p.stem in set(args.only)]
    for pdf in pdfs:
        if pdf.stem not in titles:
            _log(pdf.stem, "failed", "missing from sources.csv")
            continue
        process_one(pdf, titles[pdf.stem], client, OUT)
    OUT.mkdir(exist_ok=True)
    (OUT / "run-log.json").write_text(json.dumps(_LOG, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/vigil_pipeline/run.py pipeline/datasheets/sources.csv pipeline/tests/
git commit -m "feat(pipeline): run command writing checked and baseline outputs"
```

---

### Task 7: Datasheets and labelling tools (Richard does the hands-on part)

**Files:**
- Create: `pipeline/vigil_pipeline/labels.py`
- Modify: `pipeline/datasheets/sources.csv` (about 30 rows)
- Create: `pipeline/labels/labels.csv` (generated, then checked by hand)
- Test: `pipeline/tests/test_labels.py`

**Interfaces:**
- Consumes: `SOURCE_FIELDS` (Task 1), and the `out/<id>.json` files (Task 6)
- Produces:
  - `write_template(datasheet_ids, out_dir, dest) -> int`, which returns the number of rows written
  - The CSV columns `datasheet_id,field_id,value,unit,checked`. Empty `value` means the field is absent from the document.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_labels.py`:
```python
import csv
import json

from vigil_pipeline.labels import write_template
from vigil_pipeline.schema import SOURCE_FIELDS


def test_template_prefills_from_output_and_leaves_checked_blank(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.json").write_text(json.dumps({"fields": [
        {"id": "weight", "raw_value": "49.0", "raw_unit": "g", "status": "verified-source"},
        {"id": "manufacturer", "raw_value": None, "raw_unit": None, "status": "review"},
    ]}))
    dest = tmp_path / "labels.csv"
    n = write_template(["a", "b"], out, dest)
    rows = list(csv.DictReader(dest.open()))
    assert n == len(rows) == 2 * len(SOURCE_FIELDS)
    weight = next(r for r in rows if r["datasheet_id"] == "a" and r["field_id"] == "weight")
    assert (weight["value"], weight["unit"], weight["checked"]) == ("49.0", "g", "")
    assert all(r["checked"] == "" for r in rows)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_labels.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `labels.py`**

`pipeline/vigil_pipeline/labels.py`:
```python
"""python -m vigil_pipeline.labels  - write labels/labels.csv as a DRAFT for Richard to check.

The draft is pre-filled from the extraction output. Every row stays checked='' until Richard has
compared it with the PDF and typed 'y'; evaluate.py refuses unchecked rows (spec §5.3)."""
import csv
import json
from pathlib import Path

from .schema import SOURCE_FIELDS

ROOT = Path(__file__).resolve().parent.parent


def write_template(datasheet_ids: list[str], out_dir: Path, dest: Path) -> int:
    rows = []
    for ds in datasheet_ids:
        path = Path(out_dir) / f"{ds}.json"
        prefill = {}
        if path.exists():
            prefill = {f["id"]: f for f in json.loads(path.read_text())["fields"]}
        for field in SOURCE_FIELDS:
            p = prefill.get(field.id, {})
            rows.append({"datasheet_id": ds, "field_id": field.id, "value": p.get("raw_value") or "",
                         "unit": p.get("raw_unit") or "", "checked": ""})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["datasheet_id", "field_id", "value", "unit", "checked"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    ids = [p.stem for p in sorted((ROOT / "datasheets").glob("*.pdf"))]
    dest = ROOT / "labels" / "labels.csv"
    if dest.exists():
        raise SystemExit(f"{dest} exists - refusing to overwrite checked labels")
    print(write_template(ids, ROOT / "out", dest), "rows written to", dest)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_labels.py -v`
Expected: PASS

- [ ] **Step 5: Collect about 30 datasheets (Claude can do this; Richard skims the list)**

Download public PDF datasheets into `pipeline/datasheets/`, named `<manufacturer>-<model>.pdf` in lowercase with hyphens. Add one `sources.csv` row per PDF with its exact download URL. The mix:
- About 20 cylindrical cells (18650/21700) from at least 5 manufacturers, e.g. LG, Samsung SDI, Molicel, Panasonic, Sony/Murata, EVE.
- About 5 LFP cells or prismatic cells.
- About 5 e-bike, LMT or home-storage packs.

Skip any PDF that `has_text` rejects, and record it in `notes`.

- [ ] **Step 6: Run the pipeline on all of them (costs about $2–4)**

Run: `python -m vigil_pipeline.run`
Expected: one line per PDF and `out/run-log.json`. Fix any `failed` lines before going on.

- [ ] **Step 7: Generate the draft labels, then Richard checks every row against the PDFs**

Run: `python -m vigil_pipeline.labels`

**Richard** opens `labels/labels.csv` in a spreadsheet. For each row, compare with the PDF, then correct `value`/`unit` (or clear `value` if the field really isn't in the document) and type `y` in `checked`. This takes about 2–3 hours, and the eval is only honest because of it.

- [ ] **Step 8: Commit**

```bash
git add pipeline/vigil_pipeline/labels.py pipeline/tests/test_labels.py pipeline/datasheets pipeline/labels
git commit -m "feat(pipeline): datasheet set and checked labels"
```

---

### Task 8: Evaluation

**Files:**
- Create: `pipeline/vigil_pipeline/evaluate.py`
- Test: `pipeline/tests/test_evaluate.py`

**Interfaces:**
- Consumes:
  - `FIELD_BY_ID`, `SOURCE_FIELDS` (Task 1)
  - `normalise_unit`, `parse_number` (Task 2)
  - `norm` (Task 3)
  - The `out/` files (Task 6) and `labels/labels.csv` (Task 7)
- Produces:
  - `load_labels(path) -> dict[str, dict[str, tuple[str, str]]]`
  - `evaluate(out_dir, labels) -> dict`
  - `python -m vigil_pipeline.evaluate`, which writes `out/eval.json` with the keys `datasheets`, `fields_per_sheet`, `baseline`, `checked`, `not_found`, `per_cluster`, `cost`, `missed_errors`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_evaluate.py`:
```python
import json

import pytest

from vigil_pipeline.evaluate import evaluate, load_labels
from vigil_pipeline.schema import SOURCE_FIELDS


def write_labels(path, rows):
    lines = ["datasheet_id,field_id,value,unit,checked"] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")


def full_rows(ds, overrides):
    rows = []
    for f in SOURCE_FIELDS:
        value, unit = overrides.get(f.id, ("", ""))
        rows.append((ds, f.id, value, unit, "y"))
    return rows


def test_load_labels_rejects_unknown_field(tmp_path):
    p = tmp_path / "labels.csv"
    write_labels(p, [("a", "wieght", "49", "g", "y")])
    with pytest.raises(ValueError, match="unknown field id 'wieght'"):
        load_labels(p)


def test_load_labels_rejects_unchecked(tmp_path):
    p = tmp_path / "labels.csv"
    write_labels(p, [("a", "weight", "49", "g", "")])
    with pytest.raises(ValueError, match="not checked"):
        load_labels(p)


def _field(id, status, value, unit=None, quote=None):
    return {"id": id, "cluster": "performance" if id != "manufacturer" else "general",
            "status": status, "value": value, "unit": unit, "quote": quote}


def test_evaluate_counts_caught_and_missed(tmp_path):
    out = tmp_path / "out"
    (out / "baseline").mkdir(parents=True)
    checked_fields = [_field(f.id, "review", None) for f in SOURCE_FIELDS]
    by = {f["id"]: f for f in checked_fields}
    by["rated_capacity"].update(status="verified-source", value=3.5, unit="Ah")   # correct
    by["nominal_voltage"].update(status="review", value=3.7, unit="V")            # wrong, caught
    by["weight"].update(status="verified-source", value=50.0, unit="g")           # wrong, missed
    (out / "a.json").write_text(json.dumps({"id": "a", "fields": checked_fields,
        "run": {"cost_usd": 0.05, "elapsed_s": 4.0}}))
    (out / "baseline" / "a.json").write_text(json.dumps({"id": "a", "fields": [
        {"id": "rated_capacity", "found": True, "value": "3500", "unit": "mAh"},
        {"id": "nominal_voltage", "found": True, "value": "3.7", "unit": "V"},
        {"id": "manufacturer", "found": True, "value": "Made Up Corp", "unit": ""},
    ], "run": {"cost_usd": 0.02, "elapsed_s": 2.0}}))
    labels_path = tmp_path / "labels.csv"
    write_labels(labels_path, full_rows("a", {"rated_capacity": ("3500", "mAh"),
                                              "nominal_voltage": ("3.635", "V"), "weight": ("49.0", "g")}))
    result = evaluate(out, load_labels(labels_path))
    n = len(SOURCE_FIELDS)
    assert result["checked"]["wrong"] == 2 and result["checked"]["wrong_flagged"] == 1
    assert result["checked"]["errors_caught_rate"] == 0.5
    assert result["checked"]["accuracy"] == pytest.approx((n - 2) / n)
    # baseline: capacity right; voltage wrong; manufacturer invented (label absent); weight missed (label 49 g)
    assert result["baseline"]["accuracy"] == pytest.approx((n - 3) / n)
    assert result["not_found"]["baseline_correct"] == result["not_found"]["label_absent"] - 1
    assert result["missed_errors"][0]["field"] == "weight"
    assert result["cost"]["checked_usd_per_sheet"] == 0.05


def test_evaluate_refuses_missing_output(tmp_path):
    (tmp_path / "out" / "baseline").mkdir(parents=True)
    labels_path = tmp_path / "labels.csv"
    write_labels(labels_path, full_rows("ghost", {}))
    with pytest.raises(FileNotFoundError, match="ghost"):
        evaluate(tmp_path / "out", load_labels(labels_path))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `evaluate.py`**

`pipeline/vigil_pipeline/evaluate.py`:
```python
"""python -m vigil_pipeline.evaluate  - score checked vs baseline against labels -> out/eval.json (spec §5.1 step 5)."""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from .quotes import norm
from .schema import FIELD_BY_ID, SOURCE_FIELDS
from .units import normalise_unit, parse_number

ROOT = Path(__file__).resolve().parent.parent


def load_labels(path) -> dict[str, dict[str, tuple[str, str]]]:
    labels: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    with open(path, newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            if row["field_id"] not in FIELD_BY_ID:
                raise ValueError(f"unknown field id '{row['field_id']}' in labels row {n}")
            if row["checked"].strip().lower() != "y":
                raise ValueError(f"labels row {n} ({row['datasheet_id']}/{row['field_id']}) not checked")
            labels[row["datasheet_id"]][row["field_id"]] = (row["value"].strip(), row["unit"].strip())
    return dict(labels)


def _canonical(field, value, unit):
    """Label or baseline value -> canonical (float in field unit | text | None)."""
    if value in (None, ""):
        return None
    if field.vtype == "text":
        return str(value)
    if isinstance(value, (int, float)):
        return float(value)
    number, conv = parse_number(str(value)), normalise_unit(unit or "")
    if number is None or conv is None or conv[0] != field.unit:
        return None
    return number * conv[1]


def _match(field, predicted, truth) -> bool:
    if predicted is None or truth is None:
        return predicted is None and truth is None
    if field.vtype == "number":
        return math.isclose(float(predicted), float(truth), rel_tol=0.01)
    a, b = norm(str(predicted)), norm(str(truth))
    return a == b or (min(len(a), len(b)) >= 2 and (a in b or b in a))


def evaluate(out_dir, labels) -> dict:
    out_dir = Path(out_dir)
    tally = {"baseline": [0, 0], "checked": [0, 0]}
    cluster_tally = defaultdict(lambda: {"baseline": [0, 0], "checked": [0, 0]})
    wrong = flagged = false_alarms = absent = nf_checked = nf_base = 0
    costs = {"checked": [], "baseline": [], "checked_s": []}
    missed = []
    for ds, truth_row in sorted(labels.items()):
        checked_path, base_path = out_dir / f"{ds}.json", out_dir / "baseline" / f"{ds}.json"
        for p in (checked_path, base_path):
            if not p.exists():
                raise FileNotFoundError(f"no pipeline output for '{ds}': {p}")
        checked = {f["id"]: f for f in json.loads(checked_path.read_text())["fields"]}
        base_doc = json.loads(base_path.read_text())
        base = {f["id"]: f for f in base_doc["fields"]}
        run = json.loads(checked_path.read_text())["run"]
        costs["checked"].append(run["cost_usd"]); costs["checked_s"].append(run["elapsed_s"])
        costs["baseline"].append(base_doc["run"]["cost_usd"])
        for field in SOURCE_FIELDS:
            truth = _canonical(field, *truth_row.get(field.id, ("", "")))
            c = checked.get(field.id, {})
            c_pred = c.get("value") if c.get("status") not in ("supplier", "estimate") else None
            b = base.get(field.id, {})
            b_pred = _canonical(field, b.get("value"), b.get("unit")) if b.get("found") else None
            c_ok, b_ok = _match(field, c_pred, truth), _match(field, b_pred, truth)
            for name, ok in (("checked", c_ok), ("baseline", b_ok)):
                tally[name][0] += ok; tally[name][1] += 1
                cluster_tally[field.cluster][name][0] += ok; cluster_tally[field.cluster][name][1] += 1
            if truth is None:
                absent += 1; nf_checked += c_pred is None; nf_base += b_pred is None
            if not c_ok:
                wrong += 1
                if c.get("status") == "review":
                    flagged += 1
                else:
                    missed.append({"datasheet": ds, "field": field.id, "predicted": c_pred,
                                   "label": truth, "quote": c.get("quote")})
            elif c.get("status") == "review" and c_pred is not None:
                false_alarms += 1
    acc = lambda t: round(t[0] / t[1], 4) if t[1] else None
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {
        "datasheets": len(labels),
        "fields_per_sheet": len(SOURCE_FIELDS),
        "baseline": {"accuracy": acc(tally["baseline"])},
        "checked": {"accuracy": acc(tally["checked"]), "wrong": wrong, "wrong_flagged": flagged,
                    "errors_caught_rate": round(flagged / wrong, 4) if wrong else None,
                    "false_alarms": false_alarms},
        "not_found": {"label_absent": absent, "checked_correct": nf_checked, "baseline_correct": nf_base},
        "per_cluster": {k: {m: acc(v[m]) for m in v} for k, v in sorted(cluster_tally.items())},
        "cost": {"checked_usd_per_sheet": mean(costs["checked"]),
                 "baseline_usd_per_sheet": mean(costs["baseline"]),
                 "checked_s_per_sheet": mean(costs["checked_s"])},
        "missed_errors": missed,
    }


if __name__ == "__main__":
    result = evaluate(ROOT / "out", load_labels(ROOT / "labels" / "labels.csv"))
    (ROOT / "out" / "eval.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k != "missed_errors"}, indent=2))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_evaluate.py -v`
Expected: all pass

- [ ] **Step 5: Run the real eval**

Run: `python -m vigil_pipeline.evaluate`
Expected: a summary printed and `out/eval.json` written. Read `missed_errors` together with Richard. They become the case study's "failure that got through" (spec §9).

- [ ] **Step 6: Commit**

```bash
git add pipeline/vigil_pipeline/evaluate.py pipeline/tests/test_evaluate.py
git commit -m "feat(pipeline): evaluation of checked vs baseline against labels"
```

---

### Task 9: Export the demo set and final checks

**Files:**
- Create: `pipeline/vigil_pipeline/export.py`
- Test: `pipeline/tests/test_export.py`

**Interfaces:**
- Consumes: the `out/<id>.json` and `out/eval.json` files (Tasks 6 and 8)
- Produces:
  - `export(ids, out_dir, dest) -> None`, run as `python -m vigil_pipeline.export ID [ID ...] --dest ../app/public/data`
  - It writes `dest/<id>.json`, `dest/eval.json` and `dest/index.json` (`[{ "id", "title" }]`, in the order given). **Plan 2 reads exactly these files.**

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_export.py`:
```python
import json

import pytest

from vigil_pipeline.export import export


def test_export_writes_index_in_order(tmp_path):
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
"""python -m vigil_pipeline.export ID [ID ...] --dest ../app/public/data"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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

From `out/`, choose 3–4 ids:
1. One clean sheet, with mostly `verified-source` fields.
2. One where a `review` field is a **real** model error (find it in `out/eval.json` → compare `wrong_flagged`, or search the outputs for `review` fields whose value disagrees with the label).
3. One with many `supplier` and `estimate` gaps.

If the check caught no real error at all, use the most instructive real `review` field instead, and note that for the case study. **Never edit output values by hand.**

Then run: `python -m vigil_pipeline.export <id1> <id2> <id3>`

- [ ] **Step 6: Verify the carbon estimate citation**

Open the IVL 2019 report (Emilsson & Dahllöf, "Lithium-Ion Vehicle Battery Production") and confirm the 61–106 kg CO2e/kWh range. If it differs, update `estimates.py` and `test_check.py` together, then rerun `pytest` and `python -m vigil_pipeline.run` and export again.

- [ ] **Step 7: Commit**

```bash
git add pipeline/vigil_pipeline/export.py pipeline/tests/test_export.py app/public/data
git commit -m "feat(pipeline): export demo datasheets and eval for the app"
```
