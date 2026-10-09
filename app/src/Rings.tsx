import type { FieldResult } from "./types";
import { ringOf, type Resolutions, type Ring } from "./rings";

// Inner → outer, as in spec §3: from the datasheet, verified by you, waiting on suppliers/estimates.
const RADII: Record<Ring, number> = { source: 58, verify: 80, supply: 102 };
const WIDTH: Record<Ring, number> = { source: 13, verify: 13, supply: 9 };

function arc(r: number, a0: number, a1: number) {
  const p = (a: number) => [100 + r * Math.sin(a), 120 - r * Math.cos(a)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

interface Props {
  fields: FieldResult[];
  res: Resolutions;
  focus?: string | null;
  onFocus?: (id: string | null) => void;
  size?: number;
  label?: React.ReactNode;
}

/** Hand-built SVG growth rings: one segment per field; a segment grows in when its field is resolved. */
export function Rings({ fields, res, focus = null, onFocus, size = 280, label }: Props) {
  const byRing: Record<Ring, FieldResult[]> = { source: [], verify: [], supply: [] };
  fields.forEach((f) => byRing[ringOf(f)].push(f));
  const gap = 0.05;

  return (
    <svg className="rings" viewBox="0 20 200 200" width={size} height={size} role="img"
      aria-label={`${Object.keys(res).length} of ${fields.length} fields resolved`}>
      {(Object.keys(byRing) as Ring[]).map((ring) => {
        const list = byRing[ring];
        const step = (2 * Math.PI) / Math.max(list.length, 1);
        return list.map((f, i) => {
          const a0 = i * step + gap / 2;
          const a1 = (i + 1) * step - gap / 2;
          const d = arc(RADII[ring], a0, a1);
          const done = !!res[f.id];
          return (
            <g key={f.id} className={`seg seg-${ring}${done ? " is-done" : ""}${focus === f.id ? " is-focus" : ""}`}
              onMouseEnter={() => onFocus?.(f.id)} onMouseLeave={() => onFocus?.(null)}>
              <path d={d} className="seg-track" strokeWidth={WIDTH[ring]} />
              <path d={d} className="seg-fill" strokeWidth={WIDTH[ring]} pathLength={1} />
              <title>{f.label}</title>
            </g>
          );
        });
      })}
      {label && <foreignObject x="55" y="75" width="90" height="90"><div className="rings-label">{label}</div></foreignObject>}
    </svg>
  );
}
