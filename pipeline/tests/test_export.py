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
