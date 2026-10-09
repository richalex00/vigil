import type { FieldResult } from "./types";
import type { Resolution } from "./rings";

export function fmtNumber(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString("en-GB", { maximumFractionDigits: 1 });
  return String(Number(n.toPrecision(4)));
}

export function fmtValue(value: number | string | null, unit: string | null): string {
  if (value === null || value === "") return "—";
  return typeof value === "number" ? `${fmtNumber(value)}${unit ? ` ${unit}` : ""}` : value;
}

/** The value a field currently stands at, after any decision the user made. */
export function currentValue(f: FieldResult, r?: Resolution): string {
  if (r?.kind === "fixed") return fmtValue(r.value, r.unit);
  // a value the checker couldn't convert is still shown, exactly as the AI read it
  if ((f.value === null || f.value === "") && f.raw_value) return `${f.raw_value}${f.raw_unit ? ` ${f.raw_unit}` : ""}`;
  return fmtValue(f.value, f.unit);
}

/** The checker's reasons, in words a reviewer understands (pipeline/check.py emits the raw form). */
export function readableReason(f: FieldResult): string {
  const r = f.reason ?? "";
  if (f.status === "verified-source") return `Quote found on page ${f.page}, line ${f.line}`;
  if (f.status === "derived") return "Calculated from capacity × nominal voltage";
  if (f.status === "estimate") return "Not in the datasheet. Industry-average estimate";
  if (f.status === "supplier") return "Not in the datasheet. Held by the supplier";
  if (r === "not found in document") return "Not stated in the datasheet";
  if (r === "quote not found in document") return "The quoted text isn't in the datasheet";
  if (r === "value not in quote") return "The value doesn't appear in its own quote";
  if (r === "value outside plausible range") return "Outside the plausible range for this field";
  if (r === "depends on unverified field") return "Depends on a field that still needs checking";
  const unit = r.match(/^unit '(.*)' not convertible to (.*)$/);
  if (unit) return `The unit “${unit[1]}” can't be read as ${unit[2]}`;
  return r;
}

export type Tag = "self-declared" | "verified" | "estimated" | "derived" | "requested";

/** Passport provenance tag (spec §6.4). */
export function tagOf(f: FieldResult, r?: Resolution): Tag {
  if (r?.kind === "fixed" || (f.status === "review" && r?.kind === "accepted")) return "verified";
  if (f.status === "estimate") return "estimated";
  if (f.status === "supplier") return "requested";
  if (f.status === "derived") return "derived";
  return "self-declared";
}
