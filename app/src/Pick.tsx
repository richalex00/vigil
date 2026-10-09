import { Rings } from "./Rings";
import type { Resolutions } from "./rings";
import type { Sheet } from "./types";

function preview(sheet: Sheet): Resolutions {
  return Object.fromEntries(sheet.fields.filter((f) => f.status === "verified-source" || f.status === "derived")
    .map((f) => [f.id, { kind: "accepted" as const }]));
}

export function Pick({ sheets, evalJson, onPick }: { sheets: Sheet[]; evalJson: any; onPick: (s: Sheet) => void }) {
  const precision = Math.round((evalJson?.checked?.accepted_precision ?? 0) * 100);
  const n = evalJson?.datasheets;

  return (
    <main className="instrument pick">
      <header className="pick-head">
        <img className="lockup" src={`${import.meta.env.BASE_URL}brand/vigil-lockup.png`} alt="Vigil" width="113" height="48" />
        <h1>Turn a battery datasheet into a passport you can check, line by line.</h1>
        <p className="lede">
          From February 2027, every EV, e-bike and home-storage battery sold in the EU needs a digital passport.
          Most of what goes into one is already written down, scattered across PDF datasheets. Pick one: an AI
          reads it, plain code checks every answer against the page it came from, and you decide what goes in.
        </p>
      </header>

      <ol className="sheet-list" aria-label="Datasheets">
        {sheets.map((s) => {
          const fromSheet = s.fields.filter((f) => f.status === "verified-source").length;
          const needs = s.fields.filter((f) => f.status === "review").length;
          return (
            <li key={s.id}>
              <button className="sheet" onClick={() => onPick(s)}>
                <Rings fields={s.fields} res={preview(s)} size={68} />
                <span className="sheet-text">
                  <span className="sheet-title">{s.title}</span>
                  <span className="sheet-meta mono">
                    {s.pages.length} pages, {fromSheet} fields matched to the page, {needs} for you to look at
                  </span>
                </span>
                <span className="sheet-go mono">Open</span>
              </button>
            </li>
          );
        })}
      </ol>

      <footer className="pick-foot mono dim">
        <p>
          Real output from a real run, replayed: {s3(n)} test datasheets, {precision}% of auto-accepted fields correct.
          The extraction ran offline; nothing here calls an AI.
        </p>
        <p className="legend">
          <span className="key key-source" /> from the datasheet
          <span className="key key-verify" /> checked by you
          <span className="key key-supply" /> supplier or estimate
        </p>
      </footer>
    </main>
  );
}

const s3 = (n: unknown) => (typeof n === "number" ? n : "—");
