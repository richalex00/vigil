import type { IndexEntry, Schema, Sheet } from "./types";

const STATUSES = ["verified-source", "review", "estimate", "supplier", "derived"];

function fail(msg: string): never {
  throw new Error(`Vigil data contract: ${msg}`);
}

export function checkIndex(x: unknown): IndexEntry[] {
  if (!Array.isArray(x) || !x.every((e) => typeof e?.id === "string" && typeof e?.title === "string")) fail("index.json");
  return x;
}

export function checkSchema(x: any): Schema {
  if (!Array.isArray(x?.clusters) || !Array.isArray(x?.fields) || x.fields.length === 0) fail("schema.json");
  return x;
}

export function checkSheet(x: any, schema: Schema): Sheet {
  if (x?.contract_version !== 1) fail(`${x?.id}: contract_version`);
  if (!Array.isArray(x.pages) || !x.run) fail(`${x.id}: pages/run`);
  const ids = (x.fields ?? []).map((f: any) => f.id).join();
  if (ids !== schema.fields.map((f) => f.id).join()) fail(`${x.id}: fields don't match schema.json`);
  for (const f of x.fields) if (!STATUSES.includes(f.status)) fail(`${x.id}/${f.id}: status '${f.status}'`);
  return x;
}

const url = (name: string) => `${import.meta.env.BASE_URL}data/${name}`;
async function get(name: string) {
  const r = await fetch(url(name));
  if (!r.ok) fail(`${name}: HTTP ${r.status}`);
  return r.json();
}

export async function loadAll() {
  const [index, schema, evalJson] = await Promise.all([get("index.json"), get("schema.json"), get("eval.json")]);
  const s = checkSchema(schema);
  const sheets = await Promise.all(checkIndex(index).map(async (e) => checkSheet(await get(`${e.id}.json`), s)));
  return { schema: s, sheets, evalJson };
}
