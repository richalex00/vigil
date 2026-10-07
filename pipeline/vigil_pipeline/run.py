"""python -m vigil_pipeline.run [--only ID ...] [--split dev|test]  - process datasheets/*.pdf into out/."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

import anthropic

from .check import check_all
from .contract import DatasheetResult
from .extract import extract_baseline, extract_checked
from .ingest import has_text, pages_to_dicts, pdf_to_pages
from .sources import read_sources

ROOT = Path(__file__).resolve().parent.parent
DATASHEETS = ROOT / "datasheets"
OUT = ROOT / "out"


def _log(out_dir: Path, id_: str, status: str, detail: str = "") -> str:
    """Append to out/run-log.json immediately, so a crash or a later --only run never loses history."""
    path = out_dir / "run-log.json"
    entries = json.loads(path.read_text()) if path.exists() else []
    entries.append({"id": id_, "status": status, "detail": detail})
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))
    print(f"{status:8} {id_} {detail}")
    return status


def process_one(pdf_path, title: str, client, out_dir, extract_pages=pdf_to_pages) -> str:
    id_, out_dir = Path(pdf_path).stem, Path(out_dir)
    try:
        pages = extract_pages(pdf_path)
    except Exception as exc:  # corrupt or encrypted PDF: log it and carry on with the next sheet
        return _log(out_dir, id_, "failed", f"unreadable PDF: {type(exc).__name__}: {exc}")
    if not has_text(pages):
        return _log(out_dir, id_, "skipped", "no text layer (scanned PDF?)")
    try:
        raw, run, raw_text = extract_checked(client, pages)
        base_raw, base_run, base_text = extract_baseline(client, pages)
    except Exception as exc:  # API errors, refusals, malformed JSON: one bad sheet never stops the run
        return _log(out_dir, id_, "failed", f"{type(exc).__name__}: {exc}")
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw" / f"{id_}.checked.txt").write_text(raw_text)
    (out_dir / "raw" / f"{id_}.baseline.txt").write_text(base_text)
    if run.served_model != base_run.served_model:
        return _log(out_dir, id_, "failed",
                    f"served models differ: {run.served_model} vs {base_run.served_model}")
    result = DatasheetResult(id=id_, title=title, source_file=Path(pdf_path).name,
                             pages=pages_to_dicts(pages), fields=check_all(raw, pages), run=run)
    (out_dir / "baseline").mkdir(parents=True, exist_ok=True)
    (out_dir / f"{id_}.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    baseline = {"id": id_, "fields": [{"id": r.id, "found": r.found, "value": r.value, "unit": r.unit}
                                      for r in base_raw.values()], "run": asdict(base_run)}
    (out_dir / "baseline" / f"{id_}.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
    return _log(out_dir, id_, "ok", f"${run.cost_usd + base_run.cost_usd:.3f}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="datasheet ids (file stems) to process")
    parser.add_argument("--split", choices=["dev", "test"], help="only process this split")
    args = parser.parse_args(argv)
    sources = read_sources(DATASHEETS / "sources.csv")
    client = anthropic.Anthropic(max_retries=4)
    for pdf in sorted(DATASHEETS.glob("*.pdf")):
        if args.only and pdf.stem not in set(args.only):
            continue
        row = sources.get(pdf.stem)
        if row is None:
            _log(OUT, pdf.stem, "failed", "missing from sources.csv")
            continue
        if args.split and row["split"] != args.split:
            continue
        process_one(pdf, row["title"], client, OUT)


if __name__ == "__main__":
    main()
