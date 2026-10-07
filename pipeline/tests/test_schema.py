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
