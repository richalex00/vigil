"""python -m vigil_pipeline.assist  - the independent second labeller (spec §5.3, revised Wed 7 Oct 2026).

Labels every non-blind sheet into labels/assist/<id>.json from the PDF text and labels/GUIDE.md only.
It never reads out/ beyond the list of sheet ids, so its labels can't be anchored on the extractor.
It must be a different model from the extractor: Gemini by default (GEMINI_API_KEY), else a different
Claude model, recorded in each file. Run it after the test run, then `python -m vigil_pipeline.labels`."""
import json
import os
import urllib.request
from pathlib import Path

from .ingest import Page, pdf_to_pages, render_for_prompt
from .schema import SOURCE_FIELDS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GEMINI = "gemini-2.5-flash"
FALLBACK_CLAUDE = "claude-sonnet-5-5"
_IDS = [f.id for f in SOURCE_FIELDS]


def build_prompt(guide: str, pages: list[Page]) -> str:
    fields = "\n".join(f"- {f.id}: {f.label}" + (f" [{f.unit}]" if f.unit else "") +
                       (f" - {f.hint}" if f.hint else "") for f in SOURCE_FIELDS)
    return (
        "You are labelling ground truth for an evaluation of battery datasheet extraction.\n"
        "Follow this labelling guide exactly:\n\n" + guide.strip() + "\n\n"
        "Return one entry per field id below. Copy value and unit exactly as written in the datasheet. "
        "If the datasheet does not state a field, return empty strings for value and unit.\n\n"
        f"Fields:\n{fields}\n\nDatasheet (each line is prefixed [page line]):\n{render_for_prompt(pages)}"
    )


def parse_response(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in json.loads(text).get("fields", []):
        fid = item.get("id")
        if fid in _IDS and fid not in out:
            out[fid] = {"value": str(item.get("value") or "").strip(), "unit": str(item.get("unit") or "").strip()}
    return {fid: out.get(fid, {"value": "", "unit": ""}) for fid in _IDS}


def label_sheet(call, pages: list[Page], guide: str) -> tuple[dict[str, dict], str]:
    text, served = call(build_prompt(guide, pages))
    return parse_response(text), served


def run_assist(ids, pages_for, call, guide: str, dest_dir, skip=()) -> dict[str, str]:
    dest_dir, status = Path(dest_dir), {}
    dest_dir.mkdir(parents=True, exist_ok=True)
    for ds in ids:
        path = dest_dir / f"{ds}.json"
        if ds in set(skip):
            status[ds] = "blind"
        elif path.exists():
            status[ds] = "exists"
        else:
            try:
                fields, served = label_sheet(call, pages_for(ds), guide)
            except Exception as exc:  # one bad sheet never stops the run
                status[ds] = f"failed: {type(exc).__name__}: {exc}"
            else:
                path.write_text(json.dumps({"model": served, "fields": fields}, ensure_ascii=False, indent=2))
                status[ds] = "ok"
        print(f"{status[ds]:8} {ds}")
    return status


def _schema(upper: bool) -> dict:
    t = (lambda s: s.upper()) if upper else (lambda s: s)
    item = {"type": t("object"), "properties": {
        "id": {"type": t("string"), "enum": _IDS}, "value": {"type": t("string")}, "unit": {"type": t("string")}},
        "required": ["id", "value", "unit"]}
    schema = {"type": t("object"), "properties": {"fields": {"type": t("array"), "items": item}},
              "required": ["fields"]}
    if not upper:
        item["additionalProperties"] = False
        schema["additionalProperties"] = False
    return schema


def _gemini(model: str, key: str):
    def call(prompt: str) -> tuple[str, str]:
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                     "responseSchema": _schema(upper=True)}}
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"], data.get("modelVersion", model)
    return call


def _claude(model: str):
    def call(prompt: str) -> tuple[str, str]:
        import anthropic

        resp = anthropic.Anthropic(max_retries=4).messages.create(
            model=model, max_tokens=8000, messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _schema(upper=False)}})
        return next(b.text for b in resp.content if b.type == "text"), resp.model
    return call


def choose_caller(env) -> tuple[str, object]:
    key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if key:
        model = env.get("VIGIL_ASSIST_MODEL", DEFAULT_GEMINI)
        return model, _gemini(model, key)
    model = env.get("VIGIL_ASSIST_MODEL", FALLBACK_CLAUDE)
    return model, _claude(model)


if __name__ == "__main__":
    from .labels import blind_for, output_ids
    from .sources import read_sources

    model, call = choose_caller(os.environ)
    print("assist labeller:", model)
    ids = output_ids(ROOT / "out")
    blind = blind_for(ROOT / "out", read_sources(ROOT / "datasheets" / "sources.csv"))
    run_assist(ids, lambda ds: pdf_to_pages(ROOT / "datasheets" / f"{ds}.pdf"), call,
               (ROOT / "labels" / "GUIDE.md").read_text(), ROOT / "labels" / "assist", skip=blind)
