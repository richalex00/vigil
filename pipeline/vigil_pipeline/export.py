"""python -m vigil_pipeline.export ID [ID ...] [--dest ../app/public/data]"""
import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .schema import CLUSTER_LABELS, CLUSTERS, FIELDS
from .units import allowed_units

ROOT = Path(__file__).resolve().parent.parent


def schema_json() -> dict:
    return {
        "clusters": [{"id": c, "label": CLUSTER_LABELS[c]} for c in CLUSTERS],
        "fields": [{**asdict(f), "allowed_units": (allowed_units(f.unit) or [f.unit]) if f.unit else []}
                   for f in FIELDS],
    }


def export(ids: list[str], out_dir, dest) -> None:
    out_dir, dest = Path(out_dir), Path(dest)
    missing = [i for i in ids if not (out_dir / f"{i}.json").exists()]
    if missing or not (out_dir / "eval.json").exists():
        raise FileNotFoundError(f"missing outputs: {missing or ['eval.json']}")
    dest.mkdir(parents=True, exist_ok=True)
    index = []
    for i in ids:
        shutil.copyfile(out_dir / f"{i}.json", dest / f"{i}.json")
        index.append({"id": i, "title": json.loads((out_dir / f"{i}.json").read_text())["title"]})
    shutil.copyfile(out_dir / "eval.json", dest / "eval.json")
    (dest / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    (dest / "schema.json").write_text(json.dumps(schema_json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--dest", default=str(ROOT.parent / "app" / "public" / "data"))
    args = parser.parse_args()
    export(args.ids, ROOT / "out", args.dest)
    print("exported", args.ids, "to", args.dest)
