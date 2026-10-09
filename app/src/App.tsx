import { useEffect, useState } from "react";
import { loadAll } from "./data";
import { Pick } from "./Pick";
import { Scan } from "./Scan";
import { Review } from "./Review";
import { Passport } from "./Passport";
import type { Resolutions } from "./rings";
import type { Schema, Sheet } from "./types";

type Screen = "pick" | "scan" | "review" | "passport";
type Data = { schema: Schema; sheets: Sheet[]; evalJson: any };

export function App() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>("pick");
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [res, setRes] = useState<Resolutions>({});

  useEffect(() => { loadAll().then(setData, (e) => setError(String(e.message ?? e))); }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [screen]);

  const restart = () => { setScreen("pick"); setSheet(null); setRes({}); };

  if (error) return <main className="instrument center"><p className="error">Couldn't load the demo data: {error}</p></main>;
  if (!data) return <main className="instrument center"><p className="mono dim">Loading datasheets…</p></main>;

  return (
    <>
      {screen === "pick" && (
        <Pick sheets={data.sheets} evalJson={data.evalJson}
          onPick={(s) => { setSheet(s); setRes({}); setScreen("scan"); }} />
      )}
      {sheet && screen === "scan" && <Scan sheet={sheet} onDone={() => setScreen("review")} onRestart={restart} />}
      {sheet && screen === "review" && (
        <Review sheet={sheet} schema={data.schema} res={res} setRes={setRes}
          onDone={() => setScreen("passport")} onRestart={restart} />
      )}
      {sheet && screen === "passport" && (
        <Passport sheet={sheet} schema={data.schema} res={res} onBack={() => setScreen("review")} onRestart={restart} />
      )}
    </>
  );
}
