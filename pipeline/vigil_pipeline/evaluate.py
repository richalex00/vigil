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
    checked: str = "y"
    queue: str = ""
    assist_value: str = ""


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
            checked, queue = row["checked"].strip().lower(), (row.get("queue") or "").strip()
            if not (checked == "y" or (checked == "auto" and not queue)):
                raise ValueError(f"labels row {n} ({ds}/{fid}) not checked")
            if fid in labels[ds]:
                raise ValueError(f"duplicate label {ds}/{fid} in row {n}")
            labels[ds][fid] = Label(row["value"].strip(), row["unit"].strip(),
                                    (row.get("prefill_value") or "").strip(),
                                    (row.get("blind") or "").strip().lower() == "y",
                                    checked, queue, (row.get("assist_value") or "").strip())
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


def _audit_errors(labels) -> list[tuple[str, bool]]:
    """(sheet, changed) for every audited row: did Richard change the agreed (assist) value?"""
    return [(ds, lab.value != lab.assist_value) for ds, row in sorted(labels.items())
            for lab in row.values() if lab.queue == "audit"]


def _audit_ci(audits, iters: int, seed: int = 0):
    by_sheet: dict[str, list[bool]] = defaultdict(list)
    for ds, changed in audits:
        by_sheet[ds].append(changed)
    if not by_sheet:
        return None
    sheets, rng, values = sorted(by_sheet), random.Random(seed), []
    for _ in range(iters):
        sample = [c for s in (rng.choice(sheets) for _ in sheets) for c in by_sheet[s]]
        values.append(sum(sample) / len(sample))
    values.sort()
    return [round(values[int(0.025 * (iters - 1))], 4), round(values[int(0.975 * (iters - 1))], 4)]


def _label_stats(labels, iters: int) -> dict:
    rows = [lab for row in labels.values() for lab in row.values()]
    audits = _audit_errors(labels)
    assisted = any(lab.checked == "auto" or lab.queue for lab in rows)
    return {"method": "model-assisted" if assisted else "manual",
            "human_checked": sum(lab.checked == "y" for lab in rows),
            "auto_accepted": sum(lab.checked == "auto" for lab in rows),
            "audited": len(audits),
            "audit_error_rate": _ratio(sum(c for _, c in audits), len(audits)),
            "audit_error_ci95": _audit_ci(audits, iters)}


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
                   "blind_sheets": len({r.ds for r in recs if r.blind}),
                   **_label_stats(labels, iters)},
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
