import { useEffect, useMemo, useRef, useState } from "react";
import { Rings } from "./Rings";
import { currentValue } from "./format";
import type { Resolutions } from "./rings";
import type { Sheet } from "./types";

const REPLAY_MS = 6500;
const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Replays the saved extraction at a readable speed (spec §6.2); the real timings are shown alongside. */
export function Scan({ sheet, onDone, onRestart }: { sheet: Sheet; onDone: () => void; onRestart: () => void }) {
  const lines = useMemo(() => sheet.pages.flatMap((p) => p.lines.map((text, i) => ({ p: p.number, l: i + 1, text }))), [sheet]);
  const order = useMemo(() => {
    const pos = (p: number | null, l: number | null) => (p && l ? lines.findIndex((x) => x.p === p && x.l === l) : lines.length);
    return sheet.fields.map((f) => ({ f, at: pos(f.page, f.line) })).sort((a, b) => a.at - b.at);
  }, [sheet, lines]);

  const [t, setT] = useState(reduced() ? 1 : 0);
  const startRef = useRef(reduced() ? -Infinity : performance.now());
  const windowRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    const tick = (now: number) => {
      const next = Math.min(1, (now - startRef.current) / REPLAY_MS);
      setT(next);
      if (next < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  const skip = () => { startRef.current = -Infinity; setT(1); };

  const cursor = Math.floor(t * lines.length);
  const shown = order.filter(({ at }) => at <= cursor || t >= 1);
  const res: Resolutions = Object.fromEntries(shown.map(({ f }) => [f.id, { kind: "accepted" as const }]));

  useEffect(() => {
    // scroll only the scan panel; scrollIntoView would also scroll the page on phones
    const el = windowRef.current;
    const c = el?.querySelector<HTMLElement>(".is-cursor");
    if (el && c) el.scrollTop = c.offsetTop - el.clientHeight / 2;
  }, [cursor]);

  return (
    <main className="instrument scan">
      <header className="bar">
        <button className="link" onClick={onRestart}>Datasheets</button>
        <span className="bar-title">{sheet.title}</span>
        <span className="mono dim">{Math.round(t * sheet.run.elapsed_s * 10) / 10} s</span>
      </header>

      <div className="scan-grid">
        <div className="scan-window mono" ref={windowRef} aria-hidden="true">
          {lines.slice(Math.max(0, cursor - 40), cursor + 12).map((x, i) => {
            const at = Math.max(0, cursor - 40) + i;
            return (
            <div key={`${x.p}-${x.l}`} className={`scan-line${at === cursor ? " is-cursor" : ""}${at > cursor ? " is-ahead" : ""}`}>
              <span className="ln">p{x.p} {String(x.l).padStart(2, " ")}</span> {x.text}
            </div>
          ); })}
        </div>

        <div className="scan-side">
          <Rings fields={sheet.fields} res={res} size={240}
            label={<><b className="mono">{shown.length}</b><span>of {sheet.fields.length} fields</span></>} />
          <ul className="stream mono" aria-live="polite">
            {shown.slice(-7).map(({ f }) => (
              <li key={f.id} className={`stream-item st-${f.status}`}>
                <span>{f.label}</span><span>{currentValue(f)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <footer className="scan-foot">
        <p className="mono dim">
          Replay of the real run: {sheet.run.served_model}, {sheet.run.elapsed_s} s, ${sheet.run.cost_usd.toFixed(3)}, sped up to read.
        </p>
        {t < 1
          ? <button key="skip" className="btn ghost" onClick={skip}>Skip replay</button>
          : <button key="review" className="btn" onClick={onDone}>Review the fields</button>}
      </footer>
    </main>
  );
}
