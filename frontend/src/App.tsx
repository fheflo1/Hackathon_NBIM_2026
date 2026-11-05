import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronDown,
  CircleAlert,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Layers3,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';
import { api } from './lib/api';
import type { Bootstrap, Job, JobSummary } from './lib/types';
import { date, finished, labels, number, stages } from './lib/format';
import { Results } from './components/Results';
import { DataView } from './components/DataView';
import { AgentView } from './components/AgentView';
import { ModelView } from './components/ModelView';
import type { TriagedJob } from './model/types';

type Page = 'cases' | 'data' | 'agents' | 'model';
const pages = [
  { id: 'cases', title: 'Saksbehandling', icon: Layers3 },
  { id: 'model', title: 'Modellen', icon: Gauge },
  { id: 'data', title: 'Datagrunnlag', icon: Database },
  { id: 'agents', title: 'Agentflyt', icon: GitBranch },
] as const;
export function App() {
  const [page, setPage] = useState<Page>('cases');
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, [page]);
  const [info, setInfo] = useState<Bootstrap | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const uploadLock = useRef(false);
  const refreshJobs = useCallback(
    () =>
      api<{ jobs: JobSummary[] }>('/jobs').then((r) => {
        setJobs(r.jobs);
        return r.jobs;
      }),
    [],
  );
  useEffect(() => {
    let active = true;
    api<Bootstrap>('/bootstrap')
      .then((r) => {
        if (active) setInfo(r);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    refreshJobs()
      .then((rows) => {
        const wanted = localStorage.getItem('stem-agenda');
        const id = rows.find((r) => r.id === wanted)?.id || rows[0]?.id;
        if (id)
          api<Job>('/jobs/' + id)
            .then((j) => {
              if (active) setJob(j);
            })
            .catch((e) => {
              if (active) setError(e.message);
            });
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [refreshJobs]);
  useEffect(() => {
    if (!job || finished(job)) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      api<Job>('/jobs/' + job.id)
        .then((next) => {
          if (!cancelled) {
            setJob(next);
            setError(null);
            if (finished(next)) refreshJobs().catch(() => {});
          }
        })
        .catch(() => {
          if (!cancelled)
            setError(
              'Forbindelsen ble brutt. Behandlingen fortsetter på serveren. Last siden på nytt når den er tilgjengelig.',
            );
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status, refreshJobs]);
  async function upload(file: File) {
    if (uploadLock.current) return;
    if (!/\.(csv|pdf|txt)$/i.test(file.name) || file.size > 20 * 1024 * 1024 || file.size === 0) {
      setError('Velg en PDF, CSV eller TXT mellom 1 byte og 20 MB.');
      return;
    }
    uploadLock.current = true;
    setUploading(true);
    setError(null);
    setNotice(null);
    setPage('cases');
    try {
      const form = new FormData();
      form.append('file', file);
      const result = await api<{ job: Job; reused: boolean }>('/agenda', {
        method: 'POST',
        body: form,
      });
      setJob(result.job);
      localStorage.setItem('stem-agenda', result.job.id);
      if (result.reused)
        setNotice(
          'Denne versjonen er allerede registrert. Vi viser den eksisterende behandlingen.',
        );
      await refreshJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Opplastingen mislyktes. Prøv igjen.');
    } finally {
      uploadLock.current = false;
      setUploading(false);
    }
  }
  async function selectJob(id: string) {
    try {
      setJob(await api<Job>('/jobs/' + id));
      localStorage.setItem('stem-agenda', id);
      setHistoryOpen(false);
      setError(null);
      setNotice(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const busy = uploading || Boolean(job && !finished(job));
  const activePage = pages.find((p) => p.id === page)!;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="wordmark" href="/" aria-label="STEM – startsiden">
          <span className="brand-symbol">
            <i />
            <i />
            <i />
          </span>
          stem<span className="wordmark-period">.</span>
        </a>
        <div className="workspace-label">
          <span className="workspace-icon">N</span>
          <div>
            <strong>Voting workspace</strong>
            <span>Hackathon NBIM 2026</span>
          </div>
          <span className="workspace-mark">01</span>
        </div>
        <span className="nav-label">ARBEIDSFLATE</span>
        <nav>
          {pages.map((p) => (
            <button
              key={p.id}
              aria-label={p.title}
              title={p.title}
              aria-current={page === p.id ? 'page' : undefined}
              className={page === p.id ? 'selected' : ''}
              onClick={() => setPage(p.id)}
            >
              <p.icon size={18} />
              <span>{p.title}</span>
              {page === p.id && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-model">
            <span className={'status-dot ' + (info?.model.available ? '' : 'offline')} />
            <div>
              <strong>{info?.model.provider === 'openai' ? 'API-modell' : 'Lokal modell'}</strong>
              <span>{info?.model.name || 'Kontrollerer oppsett …'}</span>
            </div>
            <span className="model-tag">{info?.model.available ? 'KLAR' : 'VENTER'}</span>
          </div>
          <div className="sidebar-caption">
            Begrunnet. Kontrollert. Sporbart.
            <br />
            <span>Et verktøy for beslutningsstøtte.</span>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace<span>/</span>
            <strong>{activePage.title}</strong>
          </div>
          <div className="topbar-status">
            <span className="status-dot" />
            {info?.model.provider === 'openai' ? 'Kjører via API' : 'Kjører lokalt'}
            <span className="avatar">NB</span>
          </div>
        </header>
        <div className="main-content">
          <div className="page-kicker">
            <span>
              <activePage.icon size={14} />
              {activePage.title}
            </span>
            <span className="edition">NBIM HACKATHON / 2026</span>
          </div>
          {error && (
            <div className="notice error" role="alert">
              <CircleAlert size={19} />
              <p>{error}</p>
              <button
                className="icon-button"
                aria-label="Lukk feilmelding"
                onClick={() => setError(null)}
              >
                <X size={17} />
              </button>
            </div>
          )}
          {page === 'cases' && (
            <>
              <div className="page-intro case-intro">
                <div>
                  <span className="eyebrow">FRA AGENDA TIL ANBEFALING</span>
                  <h1>
                    Hver sak.
                    <br />
                    Et begrunnet standpunkt<span className="green-period">.</span>
                  </h1>
                  <p>
                    Last opp sakslisten. Agentene vurderer hvert punkt, kontrollerer grunnlaget og
                    viser deg hvorfor.
                  </p>
                </div>
                <div className="intro-stamp">
                  <ShieldCheck size={21} />
                  <span>
                    Kilder bak
                    <br />
                    <strong>hvert valg.</strong>
                  </span>
                  <span className="stamp-star">✳</span>
                </div>
              </div>
              <input
                className="sr-only"
                ref={input}
                type="file"
                accept=".pdf,.csv,.txt"
                aria-label="Last opp saksliste"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                  e.target.value = '';
                }}
              />
              <div className="upload-layout">
                <section
                  className={'upload-zone ' + (drag ? 'dragging' : '')}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (!uploading) setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    if (e.dataTransfer.files[0]) void upload(e.dataTransfer.files[0]);
                  }}
                >
                  <div className="upload-icon">
                    {uploading ? <LoaderCircle className="spin" size={24} /> : <Upload size={24} />}
                  </div>
                  <h2>
                    {uploading
                      ? 'Registrerer sakslisten …'
                      : job
                        ? 'Neste saksliste? Bare last opp.'
                        : 'Slipp sakslisten her'}
                  </h2>
                  <p>PDF, CSV eller TXT · opptil 20 MB</p>
                  <button
                    className="button primary"
                    disabled={uploading}
                    onClick={() => input.current?.click()}
                  >
                    {uploading ? 'Laster opp …' : 'Last opp saksliste'}
                    <ArrowUpRight size={17} />
                  </button>
                  <span className="upload-caption">
                    Behandlingen starter automatisk. Ingen oppsett nødvendig.
                  </span>
                </section>
                <section className="upload-side">
                  <span className="eyebrow">TRE STEG. FULL OVERSIKT.</span>
                  <div className="mini-process">
                    <span>
                      <FileText size={16} />
                    </span>
                    <div>
                      <strong>Les og strukturer</strong>
                      <small>Hvert agendapunkt blir en egen sak.</small>
                    </div>
                    <Check size={13} />
                  </div>
                  <div className="mini-process">
                    <span>
                      <Sparkles size={16} />
                    </span>
                    <div>
                      <strong>Vurder og begrunn</strong>
                      <small>Stemmevalg, konfidens og kilder.</small>
                    </div>
                    <Check size={13} />
                  </div>
                  <div className="mini-process">
                    <span>
                      <CheckCheck size={16} />
                    </span>
                    <div>
                      <strong>Kontroller og lagre</strong>
                      <small>En ny agent etterprøver svaret.</small>
                    </div>
                    <Check size={13} />
                  </div>
                  <button className="text-link" onClick={() => setPage('agents')}>
                    Se hvordan agentene jobber
                    <ArrowRight size={14} />
                  </button>
                </section>
              </div>
              {info && !info.model.available && (
                <div className="notice amber">
                  <CircleAlert size={18} />
                  <p>
                    {info.model.detail} Sakslistene dine og tidligere resultater blir liggende
                    lokalt.
                  </p>
                  <button
                    className="text-link"
                    onClick={() => {
                      api<Bootstrap>('/bootstrap')
                        .then(setInfo)
                        .catch((e) => setError(e.message));
                    }}
                  >
                    Kontroller igjen
                  </button>
                </div>
              )}
              {notice && (
                <div className="notice success" role="status">
                  <CheckCheck size={18} />
                  <p>{notice}</p>
                </div>
              )}
              {job && (
                <>
                  <div className="meeting-heading">
                    <div className="meeting-icon">
                      <FileText size={21} />
                    </div>
                    <div>
                      <span className="eyebrow">VALGT SAKSLISTE</span>
                      <h3>{job.filename}</h3>
                      <span className="small muted">
                        {job.items[0]?.company || 'Saksliste'}
                        {job.items[0]?.meeting_date ? ` · ${date(job.items[0].meeting_date)}` : ''}
                      </span>
                    </div>
                    <span className={'job-status ' + (job.status === 'failed' ? 'failed' : '')}>
                      {!finished(job) && <LoaderCircle size={13} className="spin" />}
                      {labels[job.status] || job.status}
                    </span>
                  </div>
                  {busy && !uploading && (
                    <section className="live-progress" role="status" aria-live="polite">
                      <div>
                        <span className="status-dot pulse" />
                        <strong>{stages[job.stage] || 'Behandler saksliste'}</strong>
                        <span className="small muted">
                          {job.total ? `${job.done} / ${job.total} saker` : 'Finner agendapunktene'}
                        </span>
                      </div>
                      <div className="progress-track">
                        <i
                          style={{ width: job.total ? `${(job.done / job.total) * 100}%` : '6%' }}
                        />
                      </div>
                      <small>
                        {job.current_record ? `Forsøk ${job.attempt || 1} · ` : ''}En lokal modell
                        kan bruke noen minutter per sak. Du kan la appen jobbe.
                      </small>
                    </section>
                  )}
                  {job.error && (
                    <div className="notice error">
                      <CircleAlert size={18} />
                      <div>
                        <strong>Behandlingen stoppet</strong>
                        <p>{job.error}</p>
                        <p>
                          Ferdige resultater er bevart. Last opp filen på nytt for å fortsette med
                          ubehandlede saker.
                        </p>
                      </div>
                    </div>
                  )}
                  {job.items.length > 0 && <Results key={job.id} job={job} />}
                  {job.done > 0 && (
                    <div className="run-footer">
                      <span>
                        <CheckCheck size={15} />
                        {job.done} saker lagret · {job.cached} gjenbrukt
                      </span>
                      <span>
                        {job.api_calls} modellkall
                        {(job as TriagedJob).light_calls
                          ? ` · ${(job as TriagedJob).light_calls} lette kontroller`
                          : ''}
                        {(job as TriagedJob).escalated
                          ? ` · ${(job as TriagedJob).escalated} eskalert`
                          : ''}{' '}
                        · {job.model}
                      </span>
                    </div>
                  )}
                </>
              )}
              {!job && (
                <section className="foundation">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">ARBEIDET BAK VALGENE</span>
                      <h2>Bygget på et tydelig datagrunnlag.</h2>
                    </div>
                    <button className="text-link" onClick={() => setPage('data')}>
                      Utforsk dataene
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  <div className="foundation-grid">
                    <article>
                      <span className="square-icon pale">
                        <Database size={19} />
                      </span>
                      <strong>
                        {info
                          ? number(
                              info.sources.find((s) => s.id === 'real')?.report.total_rows || 0,
                            )
                          : '—'}
                      </strong>
                      <span>historiske NBIM-stemmer</span>
                      <p>
                        Historikken brukes til analyse og modellvurdering. Agentene får aldri
                        fasiten.
                      </p>
                    </article>
                    <article>
                      <span className="square-icon lilac">
                        <ShieldCheck size={19} />
                      </span>
                      <strong>{info?.policy.rules.length || '—'} retningslinjer</strong>
                      <span>et kuratert utvalg fra NBIM 2025</span>
                      <p>Utenfor datovinduet eller policydekningen kreves manuell vurdering.</p>
                    </article>
                    <article>
                      <span className="square-icon peach">
                        <GitBranch size={19} />
                      </span>
                      <strong>To agentroller</strong>
                      <span>vurdering + separat kontroll</span>
                      <p>Ordrette sitater, avgrensede forsøk og sporbar historikk for hver sak.</p>
                    </article>
                  </div>
                </section>
              )}
              {jobs.length > 0 && (
                <section className="history-section">
                  <button
                    className="history-toggle"
                    aria-expanded={historyOpen}
                    onClick={() => setHistoryOpen(!historyOpen)}
                  >
                    <FileText size={16} />
                    Tidligere opplastinger <span>{jobs.length}</span>
                    <ChevronDown size={16} />
                  </button>
                  {historyOpen && (
                    <div className="history-list">
                      {jobs.map((j) => (
                        <button
                          key={j.id}
                          className={j.id === job?.id ? 'current' : ''}
                          onClick={() => void selectJob(j.id)}
                        >
                          <FileText size={16} />
                          <span>
                            <strong>{j.filename}</strong>
                            <small>
                              {date(j.created_at)} · {j.done}/{j.total} saker
                            </small>
                          </span>
                          <span className="small muted">{labels[j.status]}</span>
                          <ArrowUpRight size={15} />
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
          {page === 'data' &&
            (info ? (
              <DataView info={info} />
            ) : (
              <div className="loading-state">
                <LoaderCircle size={24} className="spin" />
                Leser datagrunnlaget …
              </div>
            ))}
          {page === 'model' && <ModelView />}
          {page === 'agents' &&
            (info ? (
              <AgentView info={info} job={job} />
            ) : (
              <div className="loading-state">
                <LoaderCircle size={24} className="spin" />
                Henter agentflyten …
              </div>
            ))}
          <footer className="page-footer">
            <span>
              stem<span className="green-period">.</span>
            </span>
            <span>Beslutningsstøtte for generalforsamlinger</span>
            <span>HACKATHON · 2026</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
