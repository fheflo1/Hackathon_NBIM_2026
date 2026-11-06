import {
  ArrowDown,
  ArrowRight,
  CheckCheck,
  CircleCheck,
  FileSearch,
  Fingerprint,
  GitBranch,
  RotateCcw,
  ScanText,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import type { Bootstrap, Job } from '../lib/types';
import { stages } from '../lib/format';
const steps = [
  {
    key: 'extract',
    icon: ScanText,
    title: 'Les sakslisten',
    role: 'INNLESING',
    body: 'PDF og tekst deles i agendapunkter. Sitat, side og møtedato kontrolleres mot dokumentet. CSV leses direkte.',
  },
  {
    key: 'recommend',
    icon: Sparkles,
    title: 'Vurder saken',
    role: 'AGENT 01',
    body: 'Vurderingsagenten foreslår For, Mot eller Avstå, med konfidens og sitater fra både saken og relevant NBIM-policy.',
  },
  {
    key: 'validate',
    icon: ShieldCheck,
    title: 'Kontroller kildene',
    role: 'FAST KONTROLL',
    body: 'Sjekk at retningslinjen finnes, at sitatene er ordrette og at svaret har riktig format. Lav konfidens krever oppfølging.',
  },
  {
    key: 'review',
    icon: CheckCheck,
    title: 'Etterprøv valget',
    role: 'AGENT 02',
    body: 'En separat kontrollagent vurderer om anbefalingen faktisk følger av kildene. Feil som kan rettes sendes tilbake med konkret tilbakemelding.',
  },
];
export function AgentView({ info, job }: { info: Bootstrap; job: Job | null }) {
  const live = job && !['completed', 'needs_attention', 'failed'].includes(job.status);
  return (
    <>
      <div className="page-intro">
        <span className="eyebrow">AGENT-ORKESTRERING</span>
        <h1>
          Riktig kontroll
          <br />
          for hver sak.
        </h1>
        <p>
          Sakslisten struktureres og prioriteres først. Flaggede saker og eksplisitte policytreff
          går til full agentkontroll. Andre saker får lett kontroll og eskaleres ved tvil. Flyten
          under viser fullkontrollen, som LangGraph styrer.
        </p>
      </div>
      <div className="orchestration-banner">
        <div>
          <span className={'status-dot ' + (live ? 'pulse' : '')} />
          <strong>{live ? stages[job.stage] : 'Klar for neste saksliste'}</strong>
        </div>
        <span>
          <GitBranch size={14} /> LangGraph · {info.model.name}
        </span>
      </div>
      <section className="flow-canvas">
        <div className="flow-start">
          <FileSearch size={17} /> Opplastet saksliste <span>PDF / CSV / TXT</span>
        </div>
        <div className="triage-queue-note">
          PRIORITERING → FULL KONTROLL / LETT KONTROLL → FULL KONTROLL VED TVIL
        </div>
        <ArrowDown className="flow-arrow" size={20} />
        <div className="flow-grid">
          {steps.map((s, i) => (
            <article
              key={s.key}
              className={
                'flow-node ' +
                (live && (job.stage === s.key || (s.key === 'extract' && job.stage === 'reading'))
                  ? 'running'
                  : '')
              }
            >
              <div className="flow-node-top">
                <span className="square-icon">
                  <s.icon size={21} />
                </span>
                <span className="eyebrow">{s.role}</span>
                <small>0{i + 1}</small>
              </div>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
              {i !== 3 && <ArrowRight className="node-arrow" size={18} />}
            </article>
          ))}
        </div>
        <div className="retry-path">
          <RotateCcw size={15} />
          <span>
            Kan rettes med eksisterende fakta? Ny vurdering med tilbakemelding · maks{' '}
            {info.limits.max_attempts} forsøk totalt
          </span>
        </div>
        <ArrowDown className="flow-arrow" size={20} />
        <div className="flow-outcomes">
          <div>
            <CircleCheck size={20} />
            <span>
              <strong>Godkjent anbefaling</strong>
              <small>Stemme · konfidens · retningslinjer · kildegrunnlag</small>
            </span>
          </div>
          <div>
            <FileSearch size={20} />
            <span>
              <strong>Manuell vurdering</strong>
              <small>Manglende fakta, policydekning eller gjentatte avvik</small>
            </span>
          </div>
        </div>
      </section>
      <div className="two-columns">
        <section className="panel">
          <span className="eyebrow">SPORBARHET</span>
          <h2>Hvert steg setter spor.</h2>
          <p className="muted">
            Vi lagrer kildeversjon, modell, retningslinjer, sitatkontroller, agentenes vurderinger
            og antall forsøk. En ny opplasting starter ikke de samme sakene på nytt.
          </p>
          <div className="log-preview">
            <span>
              <Fingerprint size={15} /> Saksgrunnlag + policy + modellversjon
            </span>
            <ArrowDown size={14} />
            <span>
              <CircleCheck size={15} /> Vannmerke · lagret resultat · behandlingslogg
            </span>
          </div>
        </section>
        <section className="panel">
          <span className="eyebrow">AVGRENSNINGER</span>
          <h2>Stopp når grunnlaget mangler.</h2>
          <p className="muted">
            Nye forsøk retter feil; de skaper ikke nye fakta. Manglende dekning eller dokumentasjon
            sendes direkte til manuell vurdering.
          </p>
          <p className="muted">
            Et teknisk reservevalg «Avstå» holdes adskilt fra en begrunnet, kontrollert
            Avstå-stemme. Agentene sender ingen stemmer til en generalforsamling.
          </p>
          <small className="same-model-note">
            {info.model.reviewer === info.model.name
              ? 'Begge agentroller bruker samme modell i separate kall. Dette er ingen garanti mot felles feil.'
              : `Kontrollagent: ${info.model.reviewer}`}
          </small>
        </section>
      </div>
    </>
  );
}
