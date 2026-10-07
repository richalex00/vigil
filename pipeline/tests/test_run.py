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
