"""Download the datasheet PDFs listed in datasheets/sources.csv.

The PDFs are third-party manufacturer documents, so they are not committed to this
repo. The pipeline (ingest, check, evaluate) needs them locally:

    python fetch_datasheets.py            # all sheets
    python fetch_datasheets.py --split dev
"""
import argparse
import csv
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASHEETS = ROOT / "datasheets"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"])
    args = ap.parse_args(argv)
    rows = list(csv.DictReader(open(DATASHEETS / "sources.csv", newline="")))
    failed = []
    for row in rows:
        if args.split and row["split"] != args.split:
            continue
        dest = DATASHEETS / f"{row['id']}.pdf"
        if dest.exists():
            continue
        try:
            req = urllib.request.Request(row["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF"):
                raise ValueError("response is not a PDF")
            dest.write_bytes(data)
            print(f"ok      {row['id']}")
        except Exception as exc:  # dead links happen; report and carry on
            failed.append(row["id"])
            print(f"failed  {row['id']}: {exc}")
    if failed:
        sys.exit(f"{len(failed)} sheet(s) could not be fetched; their source URLs may have moved")


if __name__ == "__main__":
    main()
