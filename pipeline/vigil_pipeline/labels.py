"""python -m vigil_pipeline.labels  - write labels/labels.csv as a DRAFT for Richard to check.

Model-assisted (spec §5.3, revised Wed 7 Oct 2026): for non-blind sheets the label comes from an
independent second model (labels/assist/, see assist.py), and the extractor's output is kept in the
prefill_* columns. Rows where the two agree are accepted (checked=auto), except a seeded random audit
sample; disagreements and the audit sample are queued for Richard. About 3 test sheets are 'blind':
no prefill at all, labelled from the PDF only. Without assist labels for a sheet, every row of it is
queued (the original fully manual flow)."""
import csv
import json
import math
import random
from pathlib import Path

from .quotes import norm
from .schema import SOURCE_FIELDS, Field
from .units import normalise_unit, parse_number

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["datasheet_id", "field_id", "value", "unit", "prefill_value", "prefill_unit",
           "assist_value", "assist_unit", "blind", "queue", "checked"]
_NOT_SHEETS = {"eval", "run-log", "schema"}


def output_ids(out_dir) -> list[str]:
    return sorted(p.stem for p in Path(out_dir).glob("*.json") if p.stem not in _NOT_SHEETS)


def pick_blind(test_ids, k: int = 3, seed: int = 2026) -> list[str]:
    ids = sorted(test_ids)
    return sorted(random.Random(seed).sample(ids, min(k, len(ids))))


def same_value(field: Field, a_value: str, a_unit: str, b_value: str, b_unit: str) -> bool:
    a, b = (a_value or "").strip(), (b_value or "").strip()
    if not a or not b:
        return not a and not b
    if field.vtype == "number":
        na, nb = parse_number(a), parse_number(b)
        ua, ub = normalise_unit(a_unit), normalise_unit(b_unit)
        if None not in (na, nb, ua, ub) and ua[0] == ub[0]:
            return math.isclose(na * ua[1], nb * ub[1], rel_tol=1e-6)
        return norm(f"{a} {a_unit}") == norm(f"{b} {b_unit}")
    if field.match == "tokens":
        return norm(a) in norm(b) or norm(b) in norm(a)
    return norm(a) == norm(b)


def write_template(datasheet_ids, out_dir, dest, blind_ids=(), assist=None,
                   audit_rate: float = 0.15, seed: int = 2026) -> int:
    rng = random.Random(seed)
    rows = []
    for ds in datasheet_ids:
        blind = ds in set(blind_ids)
        prefill = {}
        path = Path(out_dir) / f"{ds}.json"
        if not blind and path.exists():
            prefill = {f["id"]: f for f in json.loads(path.read_text())["fields"]}
        sheet_assist = None if blind or assist is None else assist.get(ds)
        for field in SOURCE_FIELDS:
            p = prefill.get(field.id, {})
            pv, pu = p.get("raw_value") or "", p.get("raw_unit") or ""
            row = {"datasheet_id": ds, "field_id": field.id, "prefill_value": pv, "prefill_unit": pu,
                   "assist_value": "", "assist_unit": "", "blind": "y" if blind else "", "checked": ""}
            if blind:
                row.update(value="", unit="", queue="blind")
            elif sheet_assist is None:
                row.update(value=pv, unit=pu, queue="check")
            else:
                a = sheet_assist.get(field.id, {})
                av, au = a.get("value") or "", a.get("unit") or ""
                row.update(value=av, unit=au, assist_value=av, assist_unit=au)
                if not same_value(field, av, au, pv, pu):
                    row["queue"] = "disagree"
                elif rng.random() < audit_rate:
                    row["queue"] = "audit"
                else:
                    row.update(queue="", checked="auto")
            rows.append(row)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_assist(assist_dir) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text())["fields"] for p in sorted(Path(assist_dir).glob("*.json"))}


def blind_for(out_dir, sources) -> list[str]:
    """The blind sheets: shared by assist.py (which must skip them) and the template."""
    return pick_blind([i for i in output_ids(out_dir) if sources.get(i, {}).get("split") == "test"])


if __name__ == "__main__":
    from .sources import read_sources

    dest = ROOT / "labels" / "labels.csv"
    if dest.exists():
        raise SystemExit(f"{dest} exists - refusing to overwrite checked labels")
    ids = output_ids(ROOT / "out")
    blind = blind_for(ROOT / "out", read_sources(ROOT / "datasheets" / "sources.csv"))
    assist = load_assist(ROOT / "labels" / "assist")
    n = write_template(ids, ROOT / "out", dest, blind, assist=assist or None)
    with open(dest, newline="") as fh:
        queued = sum(1 for r in csv.DictReader(fh) if r["queue"])
    print(n, "rows written to", dest, "-", queued, "queued for Richard - blind:", blind)
