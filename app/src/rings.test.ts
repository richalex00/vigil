import { describe, expect, it } from "vitest";
import { acceptAllFromSource, progress, ringOf, validateFix, type Resolutions } from "./rings";
import type { FieldResult, SchemaField } from "./types";

const f = (id: string, status: FieldResult["status"]): FieldResult => ({
  id, label: id, cluster: "general", kind: "source", status, value: 1, unit: "g", raw_value: "1",
  raw_unit: "g", quote: null, page: null, line: null, line_end: null, reason: null, estimate_note: null,
});
const FIELDS = [f("a", "verified-source"), f("b", "derived"), f("c", "review"), f("d", "estimate"), f("e", "supplier")];

describe("rings", () => {
  it("puts each status on its ring", () => {
    expect(FIELDS.map(ringOf)).toEqual(["source", "source", "verify", "supply", "supply"]);
  });

  it("grows only the ring of the resolved field and completes when all are resolved", () => {
    const res: Resolutions = { c: { kind: "fixed", value: 2, unit: "g" } };
    const p = progress(FIELDS, res);
    expect(p.rings.verify).toEqual({ done: 1, total: 1 });
    expect(p.rings.source).toEqual({ done: 0, total: 2 });
    expect(p.complete).toBe(false);
    const all: Resolutions = { ...res, ...acceptAllFromSource(FIELDS, res),
      d: { kind: "accepted" }, e: { kind: "requested" } };
    expect(progress(FIELDS, all).complete).toBe(true);
    expect(progress(FIELDS, all).done).toBe(5);
  });

  it("accept-all touches only datasheet fields and keeps earlier decisions", () => {
    const res: Resolutions = { a: { kind: "fixed", value: 9, unit: "g" } };
    const out = acceptAllFromSource(FIELDS, res);
    expect(Object.keys(out).sort()).toEqual(["b"]);
  });
});

describe("validateFix", () => {
  const cap: SchemaField = { id: "rated_capacity", label: "Rated capacity", cluster: "performance",
    kind: "source", vtype: "number", unit: "Ah", min: 0.01, max: 2000, hint: "", match: "exact",
    allowed_units: ["Ah", "mAh"] };

  it("converts to the canonical unit", () => {
    expect(validateFix(cap, "3,500", "mAh")).toEqual({ ok: true, value: 3.5, unit: "Ah", warning: null });
    expect(validateFix(cap, "3,6", "Ah").value).toBe(3.6);
  });

  it("warns but allows an out-of-range value, and rejects non-numbers", () => {
    const r = validateFix(cap, "5000", "Ah");
    expect(r.ok).toBe(true);
    expect(r.warning).toMatch(/outside the plausible range/);
    expect(validateFix(cap, "lots", "Ah").ok).toBe(false);
  });

  it("passes text fields through", () => {
    const chem = { ...cap, id: "chemistry", vtype: "text" as const, unit: null, min: null, max: null, allowed_units: [] };
    expect(validateFix(chem, " NMC ", "")).toEqual({ ok: true, value: "NMC", unit: null, warning: null });
  });
});
