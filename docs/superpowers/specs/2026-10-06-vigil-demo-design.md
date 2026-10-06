# Vigil demo: design spec

_Written Tue 6 Oct 2026. Status: design approved in conversation; spec under review. Building starts after the Mon 12 Oct 2026 application wave._

## 1. Purpose

A playable, static demo of **Vigil** (EIT Digital Summer School 2026 team venture: a "living record" for every device, built on the EU Digital Product Passport) for Richard's portfolio at https://richalex00.github.io/, alongside the StuddyBuddy and map-generator demos.

It exists to fill two gaps the portfolio research (Tue 6 Oct 2026) found:

1. **A real AI system with measured results.** It has evals against a baseline, guardrails and an honest account of failures. This is the evidence AI engineer, forward-deployed and founding engineer roles look for.
2. **One interaction polished to a really high standard.** This is the core evidence for design engineer, frontend and UI/UX roles.

It also has to show Richard's visual style and creativity, using the existing Vigil brand.

**Success looks like this:** a reviewer opens the Vigil card, understands what Vigil is within about 2 minutes of playing, can tell which parts are real AI output and which are simulated, and finds the eval numbers on the case-study page.

**Attribution:** the concept and brand are from the summer-school team venture (Team D). The prototype, pipeline and eval are Richard's own build. The case study says both.

## 2. Scope

**In scope**
- **One product category: batteries.** The EU battery passport becomes mandatory on 18 Feb 2027 (Regulation 2023/1542) for EV, industrial, LMT (e-bike/e-scooter) and home-storage batteries over 2 kWh.
- **A slice of about 22 passport fields** covering the official clusters (initial list in §5.2; finalised against the Battery Pass open data model, github.com/batterypass/BatteryPassDataModel, at plan time).
- **An offline extraction pipeline**, plus a baseline, plus an eval over about 30 public datasheets.
- **A static demo app** showing 3–4 handpicked datasheets.
- **A simulated "Life" concept view** standing in for Vigil's Dynamic tier.
- **Portfolio integration:** a sync script, a demo button and a case-study section.

**Out of scope:** live API calls from the demo, user uploads, any backend or auth, a real supplier workflow, a verifier/auditor role, other product categories, and all ~80 battery-passport attributes.

**How Vigil's parts map to the demo**

| Vigil (from the pitch) | Demo |
|---|---|
| Static DPP | Real: the extraction, review and passport flow |
| Platform AI: data-gap assessment, drafted supplier requests | Real gap detection; the supplier request is drafted but never sent |
| Dynamic DPP: live diagnostics, lifecycle, resale value | **Simulated** "Life" view, permanently labelled as a concept |

## 3. Visual direction

**"A diagnostic instrument built around living rings."** It combines option C (living rings) with option A (field instrument) from the visual exploration.

- **Brand, unchanged:** Jade `#1C8C6B`, Coral `#FF6F59`, Warm Ivory `#F1E9D8`, Pine `#12211D`, Manrope. JetBrains Mono (or similar) for the instrument readouts.
- **Coral means exactly one thing:** "a human needs to look / verified checkpoint". It's never used for decoration, which matches its role in the logo.
- **Growth rings are the hero element and the progress display:**
  - inner ring: fields from the datasheet
  - middle ring (coral): fields verified by the user
  - outer ring: fields waiting on suppliers or estimates
  - Resolving a field grows its segment, and the passport is complete when all rings close.
- **The instrument chrome** sits on dark Pine: a monospace datasheet scan, a confidence readout next to each field, a timer, a progress counter.
- **The public passport page switches to Ivory**, as if the instrument "prints" a clean document. This echoes the pitch deck.
- **Rings are hand-built SVG**, with no chart library.
- **It must work at phone width** (about 375 px). The rings may stack above the field list on narrow screens.

## 4. Architecture

Repo: `~/Documents/GitHub/vigil-demo` (public). It has two halves that share **only data files**.

```
vigil-demo/
  pipeline/          Python, runs on the laptop, never deployed
    datasheets/      source PDFs (public datasheets) + sources.csv (URL, licence note)
    labels/          hand-labelled ground truth, one file per datasheet
    schema/          field definitions: name, cluster, unit, plausible range, status rules
    out/             generated: <id>.json per datasheet, baseline/<id>.json, eval.json
  app/               React + TypeScript + Vite, fully static
    public/data/     copied from pipeline/out for the 3–4 demo datasheets + eval.json
```

**Contract:** the app reads only the JSON in `app/public/data/`. It has no API key and no network calls beyond static files. A copy script moves the chosen files from `pipeline/out`.

**Portfolio integration:** `npm run vigil:sync` in `~/Documents/GitHub/portfolio` builds the app (`npm --prefix ../vigil-demo/app run build`), runs `rm -rf` on `public/vigil-demo/`, then copies `vigil-demo/app/dist` there. That's the same pattern as `demo:sync` for StuddyBuddy, plus the build step. Vite uses `base: "/vigil-demo/"`, and all data fetches go through `import.meta.env.BASE_URL`, so the app works both under the portfolio and in local dev. The Vigil entry in `src/data/site.ts` gets a `demo` block ("Try the demo"), which opens in the existing pixel window, plus a new case-study section with the eval results.

## 5. Pipeline

### 5.1 Stages

1. **Ingest:** PDF → text with page and line numbers (pdfplumber). If a PDF yields no usable text (a scan), it's logged and skipped. It's never OCR'd or guessed in v1.
2. **Extract (Claude, current Sonnet model, structured output):** for each schema field it returns `{value, unit, quote, page}` or `{not_found: true}`. The prompt says outright that "not in the document" is a valid and expected answer.
3. **Check (plain code, no AI).** Each field gets one status:
   - **`verified-source`:** the quote appears in the page text (after whitespace and hyphenation normalisation), the unit normalises to the schema unit, the value is in range, and the value can be parsed from the quote.
   - **`review`:** any check fails. The failure reason is stored, e.g. "quote not found in document" or "value outside plausible range".
   - **`estimate`:** fields the schema marks as estimable (e.g. carbon footprint) and that are absent from the document. They're filled from a stated industry-average table with its source cited.
   - **`supplier`:** fields the schema marks as supplier-held (e.g. recycled content share) and that are absent.
   - **`derived`:** computed by code from other verified fields (e.g. rated energy = capacity × nominal voltage). If any input field isn't `verified-source`, the derived field is `review` with the reason "depends on unverified field".
   - **`not_found` on any other field** (e.g. manufacturer, UN 38.3, extinguishing agent) → `review` with the reason "not found in document". Every field therefore always ends with exactly one status.
   - **Confidence** in the UI comes from these checks, not from the model rating itself.
4. **Baseline:** the same datasheets through one plain prompt (no quotes, no checks), outputting values only.
5. **Eval:** compares extract-then-check and the baseline against `labels/` and writes `eval.json`:
   - field accuracy for each method (overall and per cluster)
   - **errors caught versus missed:** of the wrong values extract-then-check produced, how many were flagged `review`. This is the headline metric.
   - correct "not found" rate (the AI didn't invent a value)
   - cost and wall-clock time per datasheet
   - a list of missed errors with their reasons, for the write-up

### 5.2 Initial field list (about 22; finalised at plan time)

- **General:** manufacturer · model identifier · battery category · chemistry / cathode material · weight · manufacturing date _(often supplier)_
- **Performance:** rated capacity · nominal voltage · min / max voltage · max continuous discharge current · internal resistance · expected lifetime (cycles) · capacity threshold for exhaustion (%) · operating temperature range · rated energy _(derived)_
- **Materials:** hazardous substances · critical raw materials content _(often supplier)_ · recycled content share _(supplier)_
- **Carbon:** carbon footprint per kWh _(estimate)_
- **Circularity & safety:** dismantling / removal information · extinguishing agent
- **Compliance:** UN 38.3 transport test · EU declaration of conformity reference

### 5.3 Data

- **About 30 public datasheets** spanning several manufacturers and layouts: cylindrical cells (18650/21700, e.g. LG, Samsung, Molicel, Panasonic) plus a few e-bike and home-storage packs. `sources.csv` records the URL for each.
- **Ground truth:** Richard labels every field in a spreadsheet, about 2–3 hours. Claude may pre-fill a draft, but **Richard checks every value against the PDF**. Unchecked pre-fills would make the eval circular.
- **Demo set:** 3–4 datasheets chosen from the results: one clean, one where the check caught a real model error, and one with many supplier and estimate gaps. **If the check never catches a real error** across the ~30 sheets, the demo uses the most instructive real `review` field instead (e.g. a value that wasn't in the document), and the case study reports the result honestly. Errors are never planted.

## 6. Demo flow

1. **Pick a battery:** a terminal-style list of the 3–4 demo datasheets, each with a small completeness ring.
2. **Extraction:** a monospace datasheet "scan" while fields stream in with confidence readouts. It's a replay of the saved real run at a readable speed, with the original timings shown alongside.
3. **Review (the hero screen):**
   - Hovering or focusing a field highlights its source line, and the other way round.
   - `verified-source` fields can be accepted in one batch. `review` fields need a fix or a confirm, and the stored failure reason is shown. A fix is a value plus a unit (from the schema's allowed units), checked against the same range rule as the pipeline. An out-of-range fix shows an inline warning but can still be confirmed, because the user is the authority.
   - Estimates can be accepted or overridden. `supplier` fields go into a drafted supplier request the user can preview (it's never sent).
   - Every resolution grows its ring segment.
4. **Passport:** the rings close and the view switches to Ivory. It shows the public passport with a QR code encoding `https://richalex00.github.io/vigil-demo/`, a fixed production URL that's never localhost, with fields grouped into the official battery clusters and tagged as self-declared, verified, estimated or derived.
5. **Life (concept):** a tab on the passport.
   - A time scrubber plays the battery's simulated life forward: one ring per year, with ring thickness showing state of health.
   - Notches mark events (repair, cell swap, change of owner), and a coral checkpoint marks a verified inspection.
   - It ends with a projected remaining life and a resale grade.
   - **A permanent label reads "Concept: simulated data. Phase 2 of Vigil."**

**Honesty rule:** real outputs (extraction, checks, eval numbers) are shown and labelled as real. Simulated content (life data, supplier replies) is always labelled as simulated.

**State:** everything lives in memory and resets on reload. "Restart" is always available. No storage is needed.

## 7. Error handling

- **Pipeline:**
  - Unreadable PDFs are skipped and logged.
  - API errors retry with backoff, then the datasheet is marked `failed` in the run log.
  - A run never silently drops a field: every schema field appears in the output with a status.
  - The eval refuses to run if any datasheet lacks labels.
- **App:** all data is static, so validation happens at build time. Every JSON file is checked against a TypeScript or JSON schema, and the build fails loudly on a mismatch or a missing file.

## 8. Testing

- **Pipeline:** unit tests for the checker with no API calls: quote matching (whitespace, hyphenation, units such as "3,500 mAh" vs "3.5 Ah"), unit normalisation, range checks and status assignment, using small fixed fixtures. The eval is a script, not a CI test.
- **App:**
  - Unit tests for ring and progress logic: resolving a field grows the correct segment, and the passport completes only when every required field is resolved.
  - Build-time data validation (see §7).
  - A manual run-through in the browser at desktop and 375 px widths.
  - A keyboard pass on the review screen: fields are focusable and the source highlight follows focus.

## 9. Case study (portfolio)

- **A new section on the Vigil page** covering: what was built, how extract-then-check works, the eval table (baseline vs extract-then-check), and **one failure that got through the check and why**.
- **Stage tags as on the other cards:** Research · Design · Build.
- **The write-up text and the visual decisions are Richard's own.**

## 10. Open items for the plan stage (not blockers)

- **Final field list:** confirm the about 22 fields against the Battery Pass data model, and source the industry-average carbon figures.
- **Extraction model:** Plan 1 uses `claude-opus-5-5`. Richard may switch to a cheaper model later, e.g. `gemini-2.5-flash` as used in StuddyBuddy. Keep every model call inside `pipeline/vigil_pipeline/extract.py` so a switch touches one file, and rerun the eval after any switch, since the numbers belong to the model that produced them.
- **Fonts:** pick the exact monospace face.
