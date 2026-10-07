import json

from vigil_pipeline.assist import build_prompt, choose_caller, label_sheet, parse_response, run_assist
from vigil_pipeline.ingest import Page
from vigil_pipeline.schema import SOURCE_FIELDS

PAGES = [Page(1, ["Nominal Capacity 3500 mAh", "Weight 49.0 g max"])]
GUIDE = "# Labelling guide\n- Capacity: use nominal or typical capacity, not minimum."


def test_prompt_has_guide_fields_and_document_only():
    prompt = build_prompt(GUIDE, PAGES)
    assert "use nominal or typical capacity" in prompt
    assert all(f.id in prompt for f in SOURCE_FIELDS)
    assert "[p1 L2] Weight 49.0 g max" in prompt
    assert "rated_energy" not in prompt and "carbon_footprint" not in prompt  # source fields only


def test_parse_response_fills_missing_dedupes_and_drops_unknown():
    text = json.dumps({"fields": [
        {"id": "weight", "value": "49.0", "unit": "g"},
        {"id": "weight", "value": "50", "unit": "g"},
        {"id": "made_up", "value": "1", "unit": ""},
    ]})
    fields = parse_response(text)
    assert set(fields) == {f.id for f in SOURCE_FIELDS}
    assert fields["weight"] == {"value": "49.0", "unit": "g"}
    assert fields["manufacturer"] == {"value": "", "unit": ""}


def test_label_sheet_uses_injected_caller():
    seen = []

    def call(prompt):
        seen.append(prompt)
        return json.dumps({"fields": [{"id": "weight", "value": "49.0", "unit": "g"}]}), "gemini-2.5-flash"

    fields, served = label_sheet(call, PAGES, GUIDE)
    assert served == "gemini-2.5-flash" and fields["weight"]["value"] == "49.0" and len(seen) == 1


def test_run_assist_skips_blind_and_existing_and_survives_errors(tmp_path):
    dest = tmp_path / "assist"
    dest.mkdir()
    (dest / "done.json").write_text(json.dumps({"model": "x", "fields": {}}))

    def call(prompt):
        if "BROKEN" in prompt:
            raise RuntimeError("api down")
        return json.dumps({"fields": []}), "m"

    pages = {"a": PAGES, "done": PAGES, "blind1": PAGES, "bad": [Page(1, ["BROKEN sheet text"])]}
    status = run_assist(["a", "done", "blind1", "bad"], pages.__getitem__, call, GUIDE, dest,
                        skip=["blind1"])
    assert status == {"a": "ok", "done": "exists", "blind1": "blind", "bad": "failed: RuntimeError: api down"}
    assert json.loads((dest / "a.json").read_text())["model"] == "m"
    assert not (dest / "blind1.json").exists() and not (dest / "bad.json").exists()


def test_choose_caller_prefers_gemini_and_falls_back_to_a_different_claude():
    assert choose_caller({"GEMINI_API_KEY": "k"})[0] == "gemini-2.5-flash"
    assert choose_caller({"GEMINI_API_KEY": "k", "VIGIL_ASSIST_MODEL": "gemini-2.5-pro"})[0] == "gemini-2.5-pro"
    model, _ = choose_caller({})
    assert model.startswith("claude-") and model != "claude-opus-5-5"
