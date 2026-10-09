// Mirrors pipeline/vigil_pipeline/contract.py and export.schema_json() (contract_version 1).
export type Status = "verified-source" | "review" | "estimate" | "supplier" | "derived";

export interface FieldResult {
  id: string; label: string; cluster: string; kind: string; status: Status;
  value: number | string | null; unit: string | null;
  raw_value: string | null; raw_unit: string | null; quote: string | null;
  page: number | null; line: number | null; line_end: number | null;
  reason: string | null; estimate_note: string | null;
}

export interface Sheet {
  id: string; title: string; source_file: string;
  pages: { number: number; lines: string[] }[];
  fields: FieldResult[];
  run: { method: string; model: string; served_model: string; elapsed_s: number;
         input_tokens: number; output_tokens: number; cost_usd: number };
  contract_version: number;
}

export interface SchemaField {
  id: string; label: string; cluster: string; kind: string; vtype: "number" | "text";
  unit: string | null; min: number | null; max: number | null; hint: string; match: string;
  allowed_units: string[];
}
export interface Schema { clusters: { id: string; label: string }[]; fields: SchemaField[] }
export interface IndexEntry { id: string; title: string }
