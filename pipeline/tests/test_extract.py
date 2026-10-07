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
