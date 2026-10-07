# Labelling guide (read before labelling; keep decisions consistent)

The second-model labeller (`assist.py`) is given this guide as its instructions, so these rules apply
to it and to Richard alike.

- **One row per field per sheet.** Compare with the PDF only. Any prefilled value is a suggestion, not evidence.
- **Absent:** if the datasheet does not state the field, leave `value` and `unit` empty. Don't infer it,
  don't calculate it, don't use outside knowledge.
- **Variants:** if the sheet lists several models, label the main/first one (the same rule the model gets).
- **Capacity:** use nominal or typical capacity, not minimum.
- **Internal resistance:** label whatever the sheet gives (AC or DC), as written.
- **Temperatures:** the discharge range, not storage or charge.
- **Units:** copy the unit as written (mAh stays mAh). The eval converts.
- **Free-text fields** (hazardous substances, extinguishing agent, dismantling, UN 38.3, EU declaration):
  copy the key phrase, e.g. "dry chemical, CO2", not the whole paragraph.

## Richard's part (filter the spreadsheet on `queue`)

- **`blind`:** no prefill on purpose. Do these first, from the PDF only.
- **`disagree`:** the second model and the extractor gave different answers. Check against the PDF and
  set `value`/`unit` to what the sheet actually says (it may be neither of them).
- **`audit`:** a random sample of rows where both models agreed. Check them just as carefully; the
  share you have to change is reported as the error rate of the auto-accepted labels.
- **`check`:** a sheet the second model couldn't label. Check every row.
- When a queued row is done, type `y` in `checked`. Rows with `checked=auto` need nothing.
