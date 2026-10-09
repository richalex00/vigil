import { useEffect, useMemo, useRef, useState } from "react";
import { Rings } from "./Rings";
import { currentValue, readableReason } from "./format";
import { acceptAllFromSource, progress, ringOf, validateFix, type Resolutions, type Ring } from "./rings";
import type { FieldResult, Schema, SchemaField, Sheet } from "./types";

interface Props {
  sheet: Sheet; schema: Schema; res: Resolutions;
  setRes: React.Dispatch<React.SetStateAction<Resolutions>>;
  onDone: () => void; onRestart: () => void;
}

const GROUPS: { ring: Ring; title: string; note: string }[] = [
  { ring: "verify", title: "Needs you", note: "The checker couldn't confirm these against the page. Confirm or fix each one." },
  { ring: "source", title: "From the datasheet", note: "Each value was found, word for word, on the page shown." },
  { ring: "supply", title: "Suppliers and estimates", note: "Not in any datasheet. Ask the supplier, or use an industry estimate." },
];

function useClock() {
  const [s, setS] = useState(0);
  useEffect(() => { const id = setInterval(() => setS((x) => x + 1), 1000); return () => clearInterval(id); }, []);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function Review({ sheet, schema, res, setRes, onDone, onRestart }: Props) {
  const [focus, setFocus] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [fromField, setFromField] = useState(true);
  const sourceRef = useRef<HTMLDivElement>(null);
  const clock = useClock();
  const p = progress(sheet.fields, res);
  const schemaById = useMemo(() => Object.fromEntries(schema.fields.map((f) => [f.id, f])), [schema]);
  const focused = sheet.fields.find((f) => f.id === focus) ?? null;

  // line → the field quoting it, so hovering the source highlights the field too
  const fieldAt = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of sheet.fields) if (f.page && f.line)
      for (let l = f.line; l <= (f.line_end ?? f.line); l++) m.set(`${f.page}-${l}`, f.id);
    return m;
  }, [sheet]);

  useEffect(() => {
    if (!fromField || !focused?.line) return;
    const el = sourceRef.current;
    const line = el?.querySelector<HTMLElement>(`#ln-${focused.page}-${focused.line}`);
    if (el && line) el.scrollTo({ top: line.offsetTop - el.clientHeight / 2,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [focus]);

  const resolve = (id: string, r: Resolutions[string]) => { setRes((x) => ({ ...x, [id]: r })); setOpen(null); };
  const requested = sheet.fields.filter((f) => res[f.id]?.kind === "requested");
  const pendingSource = sheet.fields.filter((f) => ringOf(f) === "source" && !res[f.id]).length;

  return (
    <main className="instrument review">
      <header className="bar">
        <button className="link" onClick={onRestart}>Datasheets</button>
        <span className="bar-title">{sheet.title}</span>
        <span className="mono dim" aria-label="Time on this review">{clock}</span>
        <span className="mono">{p.done}/{p.total}</span>
      </header>

      <div className="review-grid">
        <section className="source mono" ref={sourceRef} aria-label="Datasheet text">
          {sheet.pages.map((pg) => (
            <div key={pg.number} className="page">
              <p className="page-no">page {pg.number}</p>
              {pg.lines.map((text, i) => {
                const id = fieldAt.get(`${pg.number}-${i + 1}`);
                const lit = focused?.page === pg.number && focused.line !== null &&
                  i + 1 >= focused.line && i + 1 <= (focused.line_end ?? focused.line);
                return (
                  <div key={i} id={`ln-${pg.number}-${i + 1}`} className={`src-line${id ? " has-field" : ""}${lit ? " is-lit" : ""}`}
                    onMouseEnter={() => { if (id) { setFromField(false); setFocus(id); } }}>
                    <span className="ln">{i + 1}</span>{text}
                  </div>
                );
              })}
            </div>
          ))}
        </section>

        <section className="dial" aria-label="Progress">
          <Rings fields={sheet.fields} res={res} focus={focus} onFocus={(id) => { setFromField(true); setFocus(id); }} size={260}
            label={p.complete
              ? <span className="ready">Passport ready</span>
              : <><b className="mono">{p.done}</b><span>of {p.total} resolved</span></>} />
          <dl className="ring-key mono">
            <div><dt><span className="key key-source" />From the datasheet</dt><dd>{p.rings.source.done}/{p.rings.source.total}</dd></div>
            <div><dt><span className="key key-verify" />Checked by you</dt><dd>{p.rings.verify.done}/{p.rings.verify.total}</dd></div>
            <div><dt><span className="key key-supply" />Supplier or estimate</dt><dd>{p.rings.supply.done}/{p.rings.supply.total}</dd></div>
          </dl>
          {p.complete
            ? <button className="btn" onClick={onDone}>Print the passport</button>
            : <p className="dim small">Every field needs a decision before the passport can be printed.</p>}
        </section>

        <section className="fields" aria-label="Fields">
          {GROUPS.map(({ ring, title, note }) => {
            const list = sheet.fields.filter((f) => ringOf(f) === ring);
            if (!list.length) return null;
            return (
              <div key={ring} className={`group group-${ring}`}>
                <div className="group-head">
                  <h2>{title}</h2>
                  {ring === "source" && pendingSource > 0 && (
                    <button className="btn small" onClick={() => setRes((x) => ({ ...x, ...acceptAllFromSource(sheet.fields, x) }))}>
                      Accept all {pendingSource}
                    </button>
                  )}
                </div>
                <p className="group-note">{note}</p>
                <ul>
                  {list.map((f) => (
                    <FieldRow key={f.id} f={f} schema={schemaById[f.id]} res={res} focused={focus === f.id}
                      open={open === f.id} onOpen={() => setOpen(open === f.id ? null : f.id)}
                      onFocus={() => { setFromField(true); setFocus(f.id); }} onResolve={resolve} />
                  ))}
                </ul>
                {ring === "supply" && requested.length > 0 && <SupplierDraft sheet={sheet} fields={requested} />}
              </div>
            );
          })}
        </section>
      </div>
    </main>
  );
}

function FieldRow({ f, schema, res, focused, open, onOpen, onFocus, onResolve }: {
  f: FieldResult; schema: SchemaField; res: Resolutions; focused: boolean; open: boolean;
  onOpen: () => void; onFocus: () => void; onResolve: (id: string, r: Resolutions[string]) => void;
}) {
  const r = res[f.id];
  const ring = ringOf(f);
  const empty = (f.value === null || f.value === "") && !f.raw_value;
  const shown = currentValue(f, r);
  const state = !r ? null : r.kind === "fixed" ? "Fixed" : r.kind === "requested" ? "Requested" : "Accepted";

  return (
    <li className={`field ring-${ring}${r ? " is-done" : ""}${focused ? " is-focus" : ""}`}>
      <button className="field-main" aria-expanded={open} onClick={onOpen} onMouseEnter={onFocus} onFocus={onFocus}>
        <span className="field-label">{f.label}</span>
        <span className={`field-value mono${shown.length > 22 ? " is-long" : ""}${shown === "—" ? " is-empty" : ""}`}>
          {shown === "—" ? "Not stated" : shown}
        </span>
        <span className="field-reason">{readableReason(f)}</span>
        {state && <span className={`chip chip-${r!.kind}`}>{state}</span>}
      </button>
      {open && (
        <div className="field-actions">
          {f.quote && <p className="quote mono">“{f.quote}”</p>}
          {f.estimate_note && <p className="small dim">{f.estimate_note}</p>}
          <Actions f={f} schema={schema} ring={ring} empty={empty} onResolve={onResolve} />
        </div>
      )}
    </li>
  );
}

function Actions({ f, schema, ring, empty, onResolve }: {
  f: FieldResult; schema: SchemaField; ring: Ring; empty: boolean; onResolve: (id: string, r: Resolutions[string]) => void;
}) {
  const [fixing, setFixing] = useState(false);
  if (fixing) return <FixForm f={f} schema={schema} onSave={(value, unit) => onResolve(f.id, { kind: "fixed", value, unit })} onCancel={() => setFixing(false)} />;

  const accept = () => onResolve(f.id, { kind: "accepted" });
  return (
    <div className="actions">
      {f.status === "supplier" && <button className="btn small" onClick={() => onResolve(f.id, { kind: "requested" })}>Ask the supplier</button>}
      {f.status === "estimate" && <button className="btn small" onClick={accept}>Use the estimate</button>}
      {ring === "verify" && <button className="btn small" onClick={accept}>{empty ? "Confirm it's not stated" : "Confirm this value"}</button>}
      {ring === "source" && <button className="btn small" onClick={accept}>Accept</button>}
      <button className="btn small ghost" onClick={() => setFixing(true)}>{empty ? "Enter a value" : "Fix the value"}</button>
    </div>
  );
}

function FixForm({ f, schema, onSave, onCancel }: {
  f: FieldResult; schema: SchemaField; onSave: (v: number | string, unit: string | null) => void; onCancel: () => void;
}) {
  const [raw, setRaw] = useState(f.raw_value ?? "");
  const [unit, setUnit] = useState(schema.allowed_units.includes(f.raw_unit ?? "") ? f.raw_unit! : schema.allowed_units[0] ?? "");
  const check = raw.trim() ? validateFix(schema, raw, unit) : null;

  return (
    <form className="fix" onSubmit={(e) => { e.preventDefault(); if (check?.ok) onSave(check.value!, check.unit); }}>
      <label className="sr" htmlFor={`fix-${f.id}`}>{f.label}</label>
      <input id={`fix-${f.id}`} className="mono" value={raw} autoFocus onChange={(e) => setRaw(e.target.value)}
        inputMode={schema.vtype === "number" ? "decimal" : "text"} />
      {schema.vtype === "number" && (
        <select aria-label="Unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
          {schema.allowed_units.map((u) => <option key={u}>{u}</option>)}
        </select>
      )}
      <button className="btn small" disabled={!check?.ok}>Save the fix</button>
      <button type="button" className="btn small ghost" onClick={onCancel}>Cancel</button>
      {check?.warning && <p className={`small ${check.ok ? "warn" : "error"}`} role="status">{check.warning}</p>}
    </form>
  );
}

function SupplierDraft({ sheet, fields }: { sheet: Sheet; fields: FieldResult[] }) {
  const maker = sheet.fields.find((f) => f.id === "manufacturer")?.value ?? "the manufacturer";
  return (
    <aside className="draft">
      <p className="draft-head">Drafted request to {String(maker)}. Never sent; this is a demo.</p>
      <pre className="mono">{`Subject: Battery passport data for ${sheet.title}

Hello,

We're preparing the EU battery passport for ${sheet.title}.
Your datasheet doesn't cover the following, could you send them?

${fields.map((f) => `  - ${f.label}`).join("\n")}

Thank you.`}</pre>
    </aside>
  );
}
