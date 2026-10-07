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
