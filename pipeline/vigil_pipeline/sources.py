"""datasheets/sources.csv: id,title,url,manufacturer,licence_note,split(dev|test),notes"""
import csv


def read_sources(path) -> dict[str, dict]:
    with open(path, newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}
