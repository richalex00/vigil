import csv
import json

from vigil_pipeline.labels import output_ids, pick_blind, same_value, write_template
from vigil_pipeline.schema import FIELD_BY_ID, SOURCE_FIELDS


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


def _rows(dest):
    return {(r["datasheet_id"], r["field_id"]): r for r in csv.DictReader(dest.open())}


def test_output_ids_ignores_non_sheet_files(tmp_path):
    assert output_ids(_out(tmp_path)) == ["a", "b"]


def test_template_prefills_and_blinds(tmp_path):
    out = _out(tmp_path)
    dest = tmp_path / "labels.csv"
    n = write_template(["a", "b"], out, dest, blind_ids=["b"])
    rows = _rows(dest)
    assert n == len(rows) == 2 * len(SOURCE_FIELDS)
    a_w, b_w = rows[("a", "weight")], rows[("b", "weight")]
    assert (a_w["value"], a_w["prefill_value"], a_w["blind"], a_w["checked"]) == ("49.0", "49.0", "", "")
    assert (b_w["value"], b_w["prefill_value"], b_w["blind"], b_w["queue"]) == ("", "", "y", "blind")


def test_pick_blind_is_deterministic_and_bounded():
    ids = [f"s{i}" for i in range(25)]
    assert pick_blind(ids) == pick_blind(list(reversed(ids)))
    assert len(pick_blind(ids)) == 3 and len(pick_blind(ids[:2])) == 2


def test_same_value_converts_units_and_normalises_text():
    w, m = FIELD_BY_ID["rated_capacity"], FIELD_BY_ID["manufacturer"]
    assert same_value(w, "3500", "mAh", "3.5", "Ah")
    assert not same_value(w, "3500", "mAh", "3400", "mAh")
    assert same_value(w, "", "", "", "")
    assert not same_value(w, "3500", "mAh", "", "")
    assert same_value(m, "Samsung SDI", "", "  samsung sdi ", "")
    assert not same_value(m, "Samsung SDI", "", "LG Chem", "")


def test_same_value_free_text_accepts_containment():
    agent = FIELD_BY_ID["extinguishing_agent"]
    assert same_value(agent, "dry chemical, CO2", "", "CO2", "")
    assert not same_value(agent, "water", "", "CO2", "")


def test_assisted_template_queues_disagreements_and_auto_accepts_agreements(tmp_path):
    out = _out(tmp_path)
    dest = tmp_path / "labels.csv"
    assist = {"a": {"weight": {"value": "49", "unit": "g"},
                    "manufacturer": {"value": "LG Chem", "unit": ""}}}
    write_template(["a"], out, dest, assist=assist, audit_rate=0.0)
    rows = _rows(dest)
    w, m = rows[("a", "weight")], rows[("a", "manufacturer")]
    # agreement: assist value is the label, accepted without a human
    assert (w["value"], w["prefill_value"], w["assist_value"], w["queue"], w["checked"]) == \
        ("49", "49.0", "49", "", "auto")
    # extractor found nothing, assist found a value: a human decides
    assert (m["value"], m["prefill_value"], m["queue"], m["checked"]) == ("LG Chem", "", "disagree", "")
    # both empty everywhere else: agreement on absence
    assert rows[("a", "chemistry")]["checked"] == "auto"


def test_audit_sample_is_seeded_and_sized(tmp_path):
    out = _out(tmp_path)
    assist = {"a": {}, "b": {}}  # assist agrees on absence for most fields
    d1, d2 = tmp_path / "1.csv", tmp_path / "2.csv"
    write_template(["a", "b"], out, d1, assist=assist, audit_rate=0.5, seed=7)
    write_template(["a", "b"], out, d2, assist=assist, audit_rate=0.5, seed=7)
    q1 = [r["queue"] for r in _rows(d1).values()]
    assert q1 == [r["queue"] for r in _rows(d2).values()]
    audited = q1.count("audit")
    agreeing = audited + q1.count("")
    assert 0 < audited < agreeing
    assert all(r["checked"] == "" for r in _rows(d1).values() if r["queue"] == "audit")
