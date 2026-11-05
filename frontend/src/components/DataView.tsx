import { useState } from 'react';
import { ArrowUpRight, Check, Database, Fingerprint, GitBranch, Shield, Split } from 'lucide-react';
import type { Bootstrap } from '../lib/types';
import { date, number, percent } from '../lib/format';

export function DataView({ info }: { info: Bootstrap }) {
  const [sourceId, setSourceId] = useState('real');
  const source = info.sources.find((s) => s.id === sourceId) || info.sources[0];
  if (!source)
    return <div className="soft-note">Datakildene er ikke tilgjengelige i dette oppsettet.</div>;
  const report = source.report;
  const total = report.total_rows;
  const votes = [
    { key: 'FOR', name: 'For', color: 'for' },
    { key: 'MOT', name: 'Mot', color: 'mot' },
    { key: 'AVSTÅ', name: 'Avstå', color: 'avstå' },
    { key: 'UKJENT', name: 'Ukjent', color: 'unknown' },
  ];
  return (
    <>
      <div className="page-intro">
        <span className="eyebrow">FØR MODELLEN</span>
        <h1>
          Gode valg begynner
          <br />
          med gode data.
        </h1>
        <p>
          Vi skiller historiske stemmer fra saksgrunnlaget. Agentene får fakta om saken og relevante
          retningslinjer — historiske fasitsvar holdes utenfor.
        </p>
      </div>
      <div className="source-tabs" aria-label="Velg datakilde">
        {info.sources.map((s) => (
          <button
            className={source.id === s.id ? 'selected' : ''}
            key={s.id}
            onClick={() => setSourceId(s.id)}
          >
            <Database size={15} />
            {s.name}
          </button>
        ))}
      </div>
      <div className="data-metrics">
        <div>
          <span>Rader i originalfilen</span>
          <strong>{number(total)}</strong>
          <small>
            {date(report.date_range.min)} – {date(report.date_range.max)}
          </small>
        </div>
        <div>
          <span>Kjent stemme</span>
          <strong>{number(source.known)}</strong>
          <small>{percent(source.known / total)} av originaldataene</small>
        </div>
        <div>
          <span>Ukjent stemme</span>
          <strong>{number(source.counts.UKJENT || 0)}</strong>
          <small>Brukes ikke som «Avstå»</small>
        </div>
        <div>
          <span>Satt til side</span>
          <strong>{source.quarantined}</strong>
          <small>Rader som ikke består datakontroll</small>
        </div>
      </div>
      <section className="panel distribution-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">STEMMEFORDELING</span>
            <h2>Fasiten er skjevfordelt.</h2>
          </div>
          <span className="small muted">Alle {number(total)} opprinnelige rader</span>
        </div>
        <div className="distribution-bar" aria-label="Stemmefordeling">
          {votes.map((v) => (
            <span
              key={v.key}
              className={v.color}
              style={{ width: `${(100 * (source.counts[v.key] || 0)) / total}%` }}
              title={`${v.name}: ${number(source.counts[v.key] || 0)}`}
            />
          ))}
        </div>
        <div className="distribution-legend">
          {votes.map((v) => (
            <div key={v.key}>
              <span className={'dot ' + v.color} />
              <span>{v.name}</span>
              <strong>{number(source.counts[v.key] || 0)}</strong>
              <small>{percent((source.counts[v.key] || 0) / total)}</small>
            </div>
          ))}
        </div>
        <p className="footnote">
          En modell som alltid velger «For» vil se treffsikker ut. Derfor vurderer vi spesielt hvor
          godt modellen finner «Mot», og holder fremtidige generalforsamlinger utenfor treningen.
        </p>
      </section>
      {source.id === 'npx' && (
        <div className="notice amber">
          <Shield size={18} />
          <div>
            <strong>N-PX er en separat datakilde</strong>
            <p>
              Forvaltertilhørigheten er ikke verifisert. Stemmene regnes derfor ikke som NBIM-fasit
              og blandes ikke inn i NBIM-treningen.
            </p>
          </div>
        </div>
      )}
      <div className="two-columns data-principles">
        <section className="panel">
          <span className="eyebrow">PREPROCESSING</span>
          <h2>Fra råfil til saksgrunnlag.</h2>
          <ol className="process-list">
            <li>
              <span>01</span>
              <div>
                <strong>Les og normaliser</strong>
                <p>
                  Enhetlige datoer, tekst og stemmeverdier. Ukjente stemmer får beholde sin egen
                  kategori.
                </p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Kontroller identitet og kvalitet</strong>
                <p>
                  Saksnummer + generalforsamling identifiserer en sak. Motstridende rader settes til
                  side.
                </p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Skill fakta fra fasit</strong>
                <p>Historiske stemmer og begrunnelser går aldri inn som bevis til agentene.</p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>Gi saken et vannmerke</strong>
                <p>
                  Endres teksten, policyen eller modellen, får vurderingen en ny versjon. Uendrede
                  saker gjenbrukes.
                </p>
              </div>
            </li>
          </ol>
        </section>
        <div className="stack">
          <section className="panel principle-card">
            <span className="square-icon peach">
              <Split size={21} />
            </span>
            <h3>Vi beskytter mot fasitlekkasje.</h3>
            <p>
              Historiske begrunnelser kan avsløre stemmevalget. De holdes utenfor modellens inndata
              og agentenes saksgrunnlag.
            </p>
            <span className="check-line">
              <Check size={14} /> Kun forhåndstilgjengelige saksfakta
            </span>
          </section>
          <section className="panel principle-card">
            <span className="square-icon lilac">
              <GitBranch size={21} />
            </span>
            <h3>Prioritering er ikke stemmegivning.</h3>
            <p>
              Logistisk regresjon er en evaluert baseline for å prioritere saker. Den avgjør ikke
              stemmen. Alle opplastede saker går gjennom samme kontrolløp.
            </p>
            <span className="small muted">
              Ingen klustring eller historisk modell brukes som automatisk fasit.
            </span>
          </section>
        </div>
      </div>
      <div className="dataset-footer">
        <Fingerprint size={17} />
        <div>
          <strong>Datagrunnlaget kan etterprøves</strong>
          <code>{report.input_sha256}</code>
        </div>
        <span>{report.preprocessing_version}</span>
      </div>
      <section className="policy-coverage">
        <div>
          <Shield size={20} />
          <div>
            <h3>Et avgrenset policygrunnlag</h3>
            <p>
              {info.policy.rules.length} kuraterte retningslinjer · {date(info.policy.valid_from)}–
              {date(info.policy.valid_through)}. Andre datoer eller manglende dekning krever manuell
              vurdering.
            </p>
          </div>
        </div>
        <a href={info.policy.source_url} target="_blank" rel="noreferrer">
          Se NBIM-kilden
          <ArrowUpRight size={15} />
        </a>
      </section>
    </>
  );
}
