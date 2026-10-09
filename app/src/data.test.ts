import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { checkIndex, checkSchema, checkSheet } from "./data";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../public/data/${name}`, import.meta.url), "utf8"));

describe("exported data matches the contract (build fails otherwise)", () => {
  it("validates index, schema and every demo sheet", () => {
    const index = checkIndex(read("index.json"));
    const schema = checkSchema(read("schema.json"));
    expect(index.length).toBeGreaterThanOrEqual(3);
    for (const { id } of index) {
      const sheet = checkSheet(read(`${id}.json`), schema);
      expect(sheet.fields.map((f) => f.id)).toEqual(schema.fields.map((f) => f.id));
    }
  });

  it("rejects a sheet with a missing field or unknown status", () => {
    const schema = checkSchema(read("schema.json"));
    const sheet = read(read("index.json")[0].id + ".json");
    expect(() => checkSheet({ ...sheet, fields: sheet.fields.slice(1) }, schema)).toThrow(/fields/);
    const bad = { ...sheet, fields: sheet.fields.map((f: object, i: number) => (i ? f : { ...f, status: "maybe" })) };
    expect(() => checkSheet(bad, schema)).toThrow(/status/);
  });
});
