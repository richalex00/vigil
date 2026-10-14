# Vigil

**A living record for every device in Europe.** Vigil started as a team venture at the EIT Digital Summer School 2026 (Bari): turn the EU's mandatory Digital Product Passport from a compliance cost into a source of revenue. This repo is my solo build afterwards: a battery-passport pipeline and a playable demo of it.

▶️ **Live demo:** https://richalex00.github.io/vigil-demo/
It replays real output from real battery datasheets. The AI ran offline beforehand, so nothing in the demo calls an AI. The Life tab is a concept with simulated data.

## What's here

| Path | What it is |
|---|---|
| `app/` | The demo: React + TypeScript (Vite). Pick a datasheet, watch the extraction replay, review fields, see the passport. |
| `pipeline/` | The Python pipeline behind it: PDF datasheet → 20 passport fields → deterministic checker → evaluation. |
| `docs/` | Specs and plans written along the way. |

## The pipeline

1. **Ingest** (`ingest.py`): PDF datasheet → pages of text (pdfplumber).
2. **Extract** (`extract.py`, Claude): 20 passport fields, each with a value, a unit, a quote from the PDF and a page.
3. **Check** (`check.py`, `quotes.py`, `units.py`): **deterministic, no AI.** It finds the quote in the PDF text, normalises units and compares numbers. Each field ends up either *accepted* or sent to human *review*.
4. **Evaluate** (`evaluate.py`): scores the extractor and the checker against `labels/labels.csv`, with bootstrap CIs, on a held-out test split (21 sheets; 5 more for dev).

> **About the labels:** the ground truth is model-assisted and model-adjudicated (`checked=claude`). It has not been hand-checked yet, and every number below inherits that caveat.

### Running it

```bash
cd pipeline
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python fetch_datasheets.py     # PDFs aren't committed (third-party documents)
.venv/bin/python -m pytest -q
.venv/bin/python -m vigil_pipeline.run   # needs ANTHROPIC_API_KEY; re-extracts every sheet
.venv/bin/python -m vigil_pipeline.evaluate
```

```bash
cd app && npm install && npm run dev
```

## Checker hill-climb (branch `checker-climb`)

A Claude Managed Agent improved the checker on its own. Each iteration it read the failures, changed one thing, re-scored on the **dev split only**, ran the tests, and kept the change only if false alarms dropped without hurting precision; otherwise it reverted. An Outcome grader audited every field whose status changed against its PDF quote. The test split was scored once, at the end.

| Checker, test split (21 sheets) | Before | After |
|---|---|---|
| False alarms (correct values sent to review) | 14 | **8** |
| Accepted precision | 0.9818 | 0.9823 |
| Review burden | 0.476 | 0.462 |
| Wrong values caught | 0 of 4 | 0 of 4 |

The change: pdfplumber splits wrapped table cells and wrapped sentences across lines, so when a quote stops exactly at a line break, the checker now also reads the next line. Numeric fields take only its first number (the value cell, not a tolerance column). Free text may continue onto it, and identifiers may not.

Still open: the 4 wrong values that get through are PDF-text quirks (a lost subscript, a detached minus sign, values taken from the wrong row or test condition). The dev split has no such cases left to learn from, so catching them needs a bigger, hand-checked dev set first.
