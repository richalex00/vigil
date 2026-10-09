import { useMemo, useState } from "react";
import qrcode from "qrcode-generator";
import { Rings } from "./Rings";
import { currentValue, tagOf, type Tag } from "./format";
import type { Resolutions } from "./rings";
import type { Schema, Sheet } from "./types";

const PUBLIC_URL = "https://richalex00.github.io/vigil-demo/";
const TAG_TEXT: Record<Tag, string> = {
  "self-declared": "Self-declared", verified: "Verified", estimated: "Estimated", derived: "Derived", requested: "Requested",
};

function Qr({ text }: { text: string }) {
  const cells = useMemo(() => {
    const q = qrcode(0, "M");
    q.addData(text);
    q.make();
    const n = q.getModuleCount();
    const out: [number, number][] = [];
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) out.push([c, r]);
    return { n, out };
  }, [text]);
  return (
    <svg className="qr" viewBox={`-2 -2 ${cells.n + 4} ${cells.n + 4}`} role="img" aria-label={`QR code for ${text}`}>
      {cells.out.map(([x, y]) => <rect key={`${x}-${y}`} x={x} y={y} width="1.02" height="1.02" />)}
    </svg>
  );
}

export function Passport({ sheet, schema, res, onBack, onRestart }: {
  sheet: Sheet; schema: Schema; res: Resolutions; onBack: () => void; onRestart: () => void;
}) {
  const [tab, setTab] = useState<"passport" | "life">("passport");
  const get = (id: string) => sheet.fields.find((f) => f.id === id);
  const maker = get("manufacturer");
  const model = get("model_identifier");

  return (
    <main className="paper">
      <header className="paper-bar">
        <button className="link" onClick={onBack}>Back to review</button>
        <div role="tablist" className="tabs">
          <button role="tab" aria-selected={tab === "passport"} onClick={() => setTab("passport")}>Passport</button>
          <button role="tab" aria-selected={tab === "life"} onClick={() => setTab("life")}>Life</button>
        </div>
        <button className="link" onClick={onRestart}>Start again</button>
      </header>

      {tab === "passport" ? (
        <article className="passport">
          <div className="passport-head">
            <div>
              <p className="wordmark dark">vigil</p>
              <h1>{sheet.title}</h1>
              <p className="sub">
                {maker ? currentValue(maker, res[maker.id]) : "Manufacturer not stated"}
                {model && <>, model {currentValue(model, res[model.id])}</>}
              </p>
            </div>
            <figure className="passport-id">
              <Qr text={PUBLIC_URL} />
              <figcaption className="mono">{PUBLIC_URL.replace("https://", "")}</figcaption>
            </figure>
          </div>

          <div className="passport-body">
            <div className="passport-rings">
              <Rings fields={sheet.fields} res={res} size={180} />
              <p className="small">Built from {sheet.source_file}, {sheet.pages.length} pages.</p>
            </div>
            <div className="clusters">
              {schema.clusters.map((c) => {
                const list = sheet.fields.filter((f) => f.cluster === c.id);
                return (
                  <section key={c.id} className="cluster">
                    <h2>{c.label}</h2>
                    <dl>
                      {list.map((f) => {
                        const r = res[f.id];
                        const tag = tagOf(f, r);
                        const value = tag === "requested" ? "Awaiting supplier" : currentValue(f, r);
                        return (
                          <div key={f.id} className="row">
                            <dt>{f.label}</dt>
                            <dd className={`mono${value.length > 22 ? " is-long" : ""}`}>{value === "—" ? "Not stated" : value}</dd>
                            <dd><span className={`tag tag-${tag}`}>{TAG_TEXT[tag]}</span></dd>
                          </div>
                        );
                      })}
                    </dl>
                  </section>
                );
              })}
            </div>
          </div>
          <p className="fine">
            Passport-shaped data for a portfolio demo. The EU battery passport is required for EV, e-bike and
            home-storage batteries from 18 February 2027; small cells like 18650s don't need one themselves.
          </p>
        </article>
      ) : (
        <Life sheet={sheet} />
      )}
    </main>
  );
}

// ---- Life: Vigil's Dynamic tier, simulated (spec §6.5) -----------------------------------------

const EVENTS = [
  { year: 2, kind: "repair", text: "Connector repaired", angle: 40 },
  { year: 4, kind: "inspection", text: "Verified inspection", angle: 150 },
  { year: 5, kind: "owner", text: "Change of owner", angle: 250 },
  { year: 7, kind: "swap", text: "Cell module swapped", angle: 320 },
];

// state of health → ring colour: jade when healthy, fading to sand as it wears
function healthColour(s: number) {
  const t = Math.min(1, Math.max(0, (100 - s) / 30));
  const mix = (a: number, b: number) => Math.round(a + (b - a) * t);
  return `rgb(${mix(28, 168)}, ${mix(140, 149)}, ${mix(107, 95)})`;
}

function simulate(seed: string) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const rand = () => ((h = (h * 1664525 + 1013904223) >>> 0) / 2 ** 32);
  const soh: number[] = [100];
  for (let y = 1; y <= 10; y++) {
    let next = soh[y - 1] - (2.4 + rand() * 1.6);
    if (y === 7) next = Math.min(100, next + 9); // module swap
    soh.push(Math.round(next * 10) / 10);
  }
  return soh;
}

function Life({ sheet }: { sheet: Sheet }) {
  const soh = useMemo(() => simulate(sheet.id), [sheet.id]);
  const [year, setYear] = useState(4);
  const now = soh[year];
  const remaining = Math.max(0, Math.round((now - 60) / 3.2));
  const grade = now >= 90 ? "A" : now >= 80 ? "B" : now >= 70 ? "C" : "D";

  return (
    <article className="life">
      <p className="concept">Concept: simulated data. Phase 2 of Vigil.</p>
      <div className="life-grid">
        <svg className="life-rings" viewBox="-120 -120 240 240" role="img"
          aria-label={`Year ${year}: state of health ${now}%`}>
          {soh.slice(1, year + 1).map((s, i) => {
            const r = 20 + i * 9.6;
            const ev = EVENTS.find((e) => e.year === i + 1);
            const a = ((ev?.angle ?? 0) * Math.PI) / 180;
            return (
              <g key={i}>
                <circle r={r} className="year-ring" stroke={healthColour(s)} strokeWidth={Math.max(1.2, (s - 62) / 4.2)} />
                {ev && <circle cx={r * Math.sin(a)} cy={-r * Math.cos(a)} r={ev.kind === "inspection" ? 4.5 : 3}
                  className={ev.kind === "inspection" ? "notch checkpoint" : "notch"} />}
              </g>
            );
          })}
          <text className="mono life-center" textAnchor="middle" dy="4">{year === 0 ? "new" : `yr ${year}`}</text>
        </svg>

        <div className="life-side">
          <label className="scrub">
            <span>Year {year}</span>
            <input type="range" min={0} max={10} value={year} onChange={(e) => setYear(Number(e.target.value))} />
          </label>
          <dl className="readout mono">
            <div><dt>State of health</dt><dd>{now}%</dd></div>
            <div><dt>Projected remaining life</dt><dd>{remaining} years</dd></div>
            <div><dt>Resale grade</dt><dd>{grade}</dd></div>
          </dl>
          <ol className="events">
            {EVENTS.map((e) => (
              <li key={e.year} className={`${e.year <= year ? "is-past" : ""}${e.kind === "inspection" ? " is-check" : ""}`}>
                <span className="mono">Year {e.year}</span> {e.text}
              </li>
            ))}
          </ol>
          <p className="small">
            Each ring is a year of use; its thickness is the battery's state of health. In Vigil, this record would
            be written by the battery management system, repair shops and inspectors over the battery's life.
          </p>
        </div>
      </div>
    </article>
  );
}
