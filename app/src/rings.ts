import type { FieldResult, SchemaField } from "./types";

/** The three growth rings (spec §3): from the datasheet, verified by you, waiting on suppliers/estimates. */
export type Ring = "source" | "verify" | "supply";
export const RINGS: Ring[] = ["source", "verify", "supply"];

export type Resolution =
  | { kind: "accepted" }
  | { kind: "fixed"; value: number | string; unit: string | null }
  | { kind: "requested" };
export type Resolutions = Record<string, Resolution>;

export function ringOf(field: FieldResult): Ring {
  if (field.status === "verified-source" || field.status === "derived") return "source";
  if (field.status === "review") return "verify";
  return "supply";
}

export function progress(fields: FieldResult[], res: Resolutions) {
  const rings = Object.fromEntries(RINGS.map((r) => [r, { done: 0, total: 0 }])) as
    Record<Ring, { done: number; total: number }>;
  for (const f of fields) {
    const ring = rings[ringOf(f)];
    ring.total += 1;
    if (res[f.id]) ring.done += 1;
  }
  const done = fields.filter((f) => res[f.id]).length;
  return { rings, done, total: fields.length, complete: done === fields.length };
}

/** "Accept all" for fields the checker verified against the datasheet; never overrides a decision. */
export function acceptAllFromSource(fields: FieldResult[], res: Resolutions): Resolutions {
  const out: Resolutions = {};
  for (const f of fields) if (ringOf(f) === "source" && !res[f.id]) out[f.id] = { kind: "accepted" };
  return out;
}

// Mirrors pipeline/vigil_pipeline/units.py for the units the fix input offers.
const FACTOR: Record<string, number> = {
  Ah: 1, mAh: 0.001, V: 1, mV: 0.001, A: 1, mA: 0.001, Wh: 1, kWh: 1000, "mΩ": 1, "Ω": 1000,
  g: 1, kg: 1000, "%": 1, "°C": 1, cycles: 1, "kg CO2e/kWh": 1,
};

export function parseNumber(text: string): number | null {
  const m = text.replace(/[−–]/g, "-").match(/-?\d+(?:[ ,]\d{3})*(?:[.,]\d+)?/);
  if (!m) return null;
  const parts = m[0].match(/^(-?\d+(?:[ ,]\d{3})*)([.,]\d+)?$/)!;
  return Number(parts[1].replace(/[ ,]/g, "") + (parts[2] ?? "").replace(",", "."));
}

export type FixResult = { ok: boolean; value: number | string | null; unit: string | null; warning: string | null };

export function validateFix(field: SchemaField, raw: string, unit: string): FixResult {
  if (field.vtype === "text") {
    const v = raw.trim();
    return v ? { ok: true, value: v, unit: null, warning: null } : { ok: false, value: null, unit: null, warning: "Enter a value." };
  }
  const n = parseNumber(raw);
  if (n === null) return { ok: false, value: null, unit: null, warning: "Enter a number." };
  const value = Math.round(n * (FACTOR[unit] ?? 1) * 1e9) / 1e9;
  const out = field.min !== null && field.max !== null && (value < field.min || value > field.max);
  return { ok: true, value, unit: field.unit,
    warning: out ? `${value} ${field.unit} is outside the plausible range (${field.min}–${field.max}). You can still confirm it.` : null };
}
