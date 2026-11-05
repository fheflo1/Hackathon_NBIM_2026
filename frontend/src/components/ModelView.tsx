import { useEffect, useState } from 'react';
import {
  CircleAlert,
  Gauge,
  Layers3,
  LoaderCircle,
  Lock,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';
import { api } from '../lib/api';
import { number } from '../lib/format';
import type { CurvePoint, Metrics, ModelCard } from '../model/types';
import { pct } from '../model/types';
import '../model/model.css';

function closest(curve: CurvePoint[], scale: number) {
  let best = 0;
  curve.forEach((p, i) => {
    if (Math.abs(p.scale - scale) < Math.abs(curve[best].scale - scale)) best = i;
  });
  return best;
}

function Curve({ curve, at, base }: { curve: CurvePoint[]; at: number; base: number }) {
  const w = 520,
    h = 170,
    pad = 28;
  const maxX = Math.max(...curve.map((p) => p.review_share), 0.01);
  const x = (v: number) => pad + (v / maxX) * (w - 2 * pad);
  const y = (v: number) => h - pad - v * (h - 2 * pad);
  const line = (key: 'recall' | 'precision') =>
    [...curve]
      .sort((a, b) => a.review_share - b.review_share)
      .map((p, i) => `${i ? 'L' : 'M'}${x(p.review_share).toFixed(1)},${y(p[key]).toFixed(1)}`)
      .join(' ');
  const cur = curve[at],
    def = curve[base];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="curve" role="img" aria-label="Recall og presisjon mot andel saker til full vurdering">
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} className="axis" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} className="axis" />
      {[0.25, 0.5, 0.75, 1].map((g) => (
        <g key={g}>
          <line x1={pad} y1={y(g)} x2={w - pad} y2={y(g)} className="grid" />
          <text x={pad - 6} y={y(g) + 3} textAnchor="end">{Math.round(g * 100)}</text>
        </g>
      ))}
      <path d={line('recall')} className="recall" />
      <path d={line('precision')} className="precision" />
      <line x1={x(def.review_share)} y1={pad} x2={x(def.review_share)} y2={h - pad} className="default" />
      <circle cx={x(cur.review_share)} cy={y(cur.recall)} r={4.5} className="recall" />
      <circle cx={x(cur.review_share)} cy={y(cur.precision)} r={4.5} className="precision" />
      <text x={w - pad} y={h - 8} textAnchor="end">andel saker til full vurdering →</text>
      <text x={x(def.review_share) + 4} y={pad + 9}>standard</text>
    </svg>
  );
}

function Row({ name, m, ap }: { name: string; m: Metrics; ap?: number }) {
  return (
    <tr>
      <td>{name}</td>
      <td>{number(m.items)}</td>
      <td>{number(m.against)}</td>
      <td>{number(m.flagged)}</td>
      <td>{m.flagged ? pct(m.precision) : '—'}</td>
      <td>{pct(m.recall)}</td>
      <td>{m.flagged ? m.f1.toFixed(2) : '—'}</td>
      <td>{ap == null ? '—' : ap.toFixed(2)}</td>
    </tr>
  );
}

export function ModelView() {
  const [card, setCard] = useState<ModelCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState(0);
  useEffect(() => {
    api<ModelCard>('/model')
      .then((c) => {
        setCard(c);
        if (c.available) setAt(closest(c.curve, 1));
      })
      .catch((e) => setError(e.message));
  }, []);
  if (error)
    return (
      <div className="notice error">
        <CircleAlert size={18} />
        <p>{error}</p>
      </div>
    );
  if (!card)
    return (
      <div className="loading-state">
        <LoaderCircle size={24} className="spin" /> Henter modellkortet …
      </div>
    );
  if (!card.available)
    return (
      <div className="notice amber">
        <CircleAlert size={18} />
        <p>{card.detail}</p>
      </div>
    );
  const v = card.validation;
  const base = closest(card.curve, 1);
  const p = card.curve[at];
  const prevalence = v.all.against / v.all.items;
  return (
    <>
      <div className="page-intro">
        <span className="eyebrow">TRIAGE · VALIDERT PÅ {v.year}</span>
        <h1>
          Riktig sak til
          <br />
          riktig vurdering<span className="green-period">.</span>
        </h1>
        <p>
          En logistisk regresjon trent på NBIMs egne stemmer {card.trained_through - 4}–
          {card.trained_through} rangerer hvert agendapunkt etter risiko for stemme mot styret.
          Flaggede saker får full agentvurdering først; resten får en lett, parallell agentkontroll.
          Modellen stemmer aldri selv.
        </p>
      </div>
      <div className="data-metrics">
        <div>
          <span>Average precision · {v.year}</span>
          <strong>{v.average_precision.toFixed(2)}</strong>
          <small>tilfeldig rangering: {prevalence.toFixed(2)}</small>
        </div>
        <div>
          <span>Presisjon</span>
          <strong>{pct(v.all.precision)}</strong>
          <small>
            {v.all.tp} av {v.all.flagged} flaggede var mot-stemmer
          </small>
        </div>
        <div>
          <span>Recall</span>
          <strong>{pct(v.all.recall)}</strong>
          <small>
            {v.all.tp} av {v.all.against} mot-stemmer funnet
          </small>
        </div>
        <div>
          <span>Alltid følg styret</span>
          <strong>{pct(v.always_with_board.accuracy)}</strong>
          <small>accuracy, men 0 mot-stemmer funnet</small>
        </div>
      </div>

      <section className="panel slider-card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              <SlidersHorizontal size={12} /> HVA OM · VALIDERINGSÅRET {v.year}
            </span>
            <h2>Fang flere mot-stemmer, eller færre falske alarmer.</h2>
          </div>
        </div>
        <input
          type="range"
          min={0}
          max={card.curve.length - 1}
          step={1}
          value={at}
          aria-label="Terskel for flagging"
          onChange={(e) => setAt(Number(e.target.value))}
          className="threshold-slider"
        />
        <div className="slider-scale">
          <span>Fang flere (lavere terskel)</span>
          <button className="text-link" onClick={() => setAt(base)}>
            Standard terskel
          </button>
          <span>Færre alarmer (høyere terskel)</span>
        </div>
        <div className="slider-readout">
          <div>
            <span>Recall</span>
            <strong className="recall">{pct(p.recall)}</strong>
            <small>{p.tp} av {v.all.against} funnet</small>
          </div>
          <div>
            <span>Presisjon</span>
            <strong className="precision">{pct(p.precision)}</strong>
            <small>{p.fp} falske alarmer</small>
          </div>
          <div>
            <span>F1</span>
            <strong>{p.f1.toFixed(2)}</strong>
            <small>{at === base ? 'standard' : p.f1 > card.curve[base].f1 ? 'over standard' : 'under standard'}</small>
          </div>
          <div>
            <span>Full vurdering</span>
            <strong>{pct(p.review_share)}</strong>
            <small>{number(p.flagged)} av {number(v.all.items)} saker</small>
          </div>
        </div>
        <Curve curve={card.curve} at={at} base={base} />
        <p className="footnote">
          Tallene er målt på {v.year}, som modellen aldri ble trent på. Terskelen ble valgt på{' '}
          {card.trained_through}. Driften bruker standardterskelen (saker uten person{' '}
          {pct(card.thresholds.A)}, personsaker {pct(card.thresholds.B)}). Høyere recall koster
          presisjon og arbeid: det er et policyvalg, ikke en modellforbedring.
        </p>
      </section>

      <section className="panel lane-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              <Layers3 size={12} /> TO SPOR · {v.year}
            </span>
            <h2>Der dataene forklarer saken, og der de ikke gjør det.</h2>
          </div>
        </div>
        <div className="table-scroll">
          <table className="lane-table">
            <thead>
              <tr>
                <th>Spor</th>
                <th>Saker</th>
                <th>Mot-stemmer</th>
                <th>Flagget</th>
                <th>Presisjon</th>
                <th>Recall</th>
                <th>F1</th>
                <th>Avg. precision</th>
              </tr>
            </thead>
            <tbody>
              <Row name="Saker uten person" m={v.lane_A} ap={v.average_precision_A} />
              <Row name="Personsaker (styrevalg, ansvarsfrihet)" m={v.lane_B} ap={v.average_precision_B} />
              <Row name="Samlet" m={v.all} ap={v.average_precision} />
              <Row name="Alltid følg styret (baseline)" m={v.always_with_board} ap={prevalence} />
            </tbody>
          </table>
        </div>
        <p className="footnote">
          Personsaker avhenger av fakta som ikke står i forslagsteksten (uavhengighet, antall verv).
          Der hjelper NBIMs tidligere stemmer for samme person, og mennesket avgjør.
        </p>
      </section>

      <div className="model-grid">
        <section className="panel">
          <span className="eyebrow">
            <Gauge size={12} /> STERKESTE SIGNALER
          </span>
          {card.top_signals.map((s) => (
            <div className="signal" key={s.feature}>
              <span>{s.label}</span>
              <i style={{ width: `${Math.min(100, (s.weight / card.top_signals[0].weight) * 100)}%` }} />
            </div>
          ))}
        </section>
        <section className="panel">
          <span className="eyebrow">
            <Lock size={12} /> KONTROLLER
          </span>
          <ul className="control-list">
            <li>Tidsdelt: trent ≤ {card.trained_through}, validert på {v.year}. 2025–2026 er låst testsett.</li>
            <li>Historikk bruker bare møter med tidligere dato; testet ved å snu alle senere fasitsvar.</li>
            <li>Personnavn og årstall maskeres; modellen lærer struktur, ikke navn.</li>
            <li>Begrunnelser, posisjonsnotater og NBIMs stemme er aldri input.</li>
            <li>Sakstype beregnes når den mangler (treffsikkerhet {pct(card.type_accuracy)}).</li>
            <li>
              {card.light_workers} parallelle lette kontroller; feiler en kontroll, går saken til full vurdering.
            </li>
          </ul>
          <code className="sha">data {card.data_sha256.slice(0, 16)}… · {card.version}</code>
        </section>
      </div>

      <section className="panel catalogue-panel">
        <span className="eyebrow">
          <ShieldCheck size={12} /> NBIMS BEGRUNNELSER PER RETNINGSLINJE (2019–{card.trained_through})
        </span>
        {Object.entries(card.catalogue).map(([id, c]) => (
          <details key={id}>
            <summary>
              <span className="policy-chip">{id}</span> {c.position_paper || 'Standardbegrunnelse'}
              <small> · {c.count} mot-stemmer</small>
            </summary>
            <p>{c.text}</p>
          </details>
        ))}
      </section>
    </>
  );
}
