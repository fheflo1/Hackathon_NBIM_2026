import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  Clock3,
  FileText,
  Fingerprint,
  ShieldCheck,
  UserCheck,
  X,
} from 'lucide-react';
import type { Item, Job } from '../lib/types';
import { api } from '../lib/api';
import { confidence, date, number, tally } from '../lib/format';
import { RiskCell, TriagePanel } from './TriagePanel';
import { triaged } from '../model/types';

export function VoteBadge({ item }: { item: Item }) {
  const r = item.result;
  if (!r)
    return (
      <span className="badge neutral">
        <Clock3 size={12} /> Venter
      </span>
    );
  if (r.needs_human_review) return <span className="badge manual">Manuell vurdering</span>;
  return (
    <span className={'badge ' + r.vote.toLowerCase()}>
      {r.vote === 'FOR' && <Check size={12} />}
      {r.vote === 'FOR' ? 'For' : r.vote === 'MOT' ? 'Mot' : 'Avstå'}
    </span>
  );
}

export function Results({ job, onJob }: { job: Job; onJob?: (job: Job) => void }) {
  const [filter, setFilter] = useState('Alle');
  const [selected, setSelected] = useState<string | null>(null);
  const closeDetail = useCallback(() => setSelected(null), []);
  const counts = tally(job.items);
  const items = job.items.filter(
    (i) =>
      filter === 'Alle' ||
      (filter === 'Manuell'
        ? i.result?.needs_human_review
        : (i.result?.status === 'verified' || i.result?.status === 'human') &&
          i.result.vote === filter),
  );
  const selectedItem = job.items.find((i) => i.record_id === selected);
  return (
    <section className="result-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">SAKSLISTEN</span>
          <h2>Stemmeforslag per sak</h2>
          <p className="muted small">
            Klikk på et stemmetall for å filtrere, eller en sak for detaljer.
          </p>
        </div>
        <a className="button secondary compact" href={`/api/jobs/${job.id}/export.csv`}>
          <ArrowDownToLine size={15} /> Eksporter CSV
        </a>
      </div>
      <div className="vote-stats">
        {(['FOR', 'MOT', 'AVSTÅ'] as const).map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={filter === v}
            onClick={() => setFilter(filter === v ? 'Alle' : v)}
            title={`Vis ${v === 'FOR' ? 'For' : v === 'MOT' ? 'Mot' : 'Avstå'}-saker`}
          >
            <span className={'dot ' + v.toLowerCase()} />
            <span>{v === 'FOR' ? 'For' : v === 'MOT' ? 'Mot' : 'Avstå'}</span>
            <strong>{number(counts[v])}</strong>
            <small>stemmeforslag</small>
          </button>
        ))}
        <button
          type="button"
          className={counts.manual ? 'needs-attention' : ''}
          aria-pressed={filter === 'Manuell'}
          onClick={() => setFilter(filter === 'Manuell' ? 'Alle' : 'Manuell')}
          title="Vis saker som må følges opp"
        >
          <span className="dot manual" />
          <span>Manuell</span>
          <strong>{number(counts.manual)}</strong>
          <small>må følges opp</small>
        </button>
      </div>
      <div className="table-card">
        <div className="table-toolbar">
          <div className="tabs" aria-label="Filtrer anbefalinger">
            {['Alle', 'FOR', 'MOT', 'AVSTÅ', 'Manuell'].map((f) => (
              <button key={f} className={filter === f ? 'active' : ''} onClick={() => setFilter(f)}>
                {f === 'Alle'
                  ? `Alle saker · ${job.total}`
                  : f === 'FOR'
                    ? 'For'
                    : f === 'MOT'
                      ? 'Mot'
                      : f === 'AVSTÅ'
                        ? 'Avstå'
                        : f}
              </button>
            ))}
          </div>
          <span className="muted small">
            {counts.pending ? `${counts.pending} venter` : `${job.done} av ${job.total} behandlet`}
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Sak</th>
                <th>Agendapunkt</th>
                <th>Prioritering / kontroll</th>
                <th>Anbefaling</th>
                <th title="Agentens egen vurdering, ikke målt treffsikkerhet">Konfidens</th>
                <th>Retningslinjer</th>
                <th>
                  <span className="sr-only">Detaljer</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.record_id}>
                  <td className="item-number">{item.item_no}</td>
                  <td>
                    <button className="proposal-button" onClick={() => setSelected(item.record_id)}>
                      {item.proposal_text}
                    </button>
                    <span className="row-subtitle">
                      {item.company || 'Selskapsnavn ikke oppgitt'}
                      {item.cached ? ' · Gjenbrukt resultat' : ''}
                    </span>
                  </td>
                  <td>
                    <RiskCell item={item} />
                  </td>
                  <td>
                    <VoteBadge item={item} />
                  </td>
                  <td>
                    <span className="confidence-number">{confidence(item.result)}</span>
                    {item.result?.status === 'verified' && (
                      <span className="mini-bar">
                        <i style={{ width: `${(item.result.confidence || 0) * 100}%` }} />
                      </span>
                    )}
                  </td>
                  <td>
                    {item.result?.citations.length ? (
                      <span className="policy-chip">
                        <ShieldCheck size={12} />
                        {item.result.citations[0].policy_id.replace('NBIM25-', '')}
                        {item.result.citations.length > 1
                          ? ` +${item.result.citations.length - 1}`
                          : ''}
                      </span>
                    ) : (
                      <span className="muted">{item.result ? 'Mangler kilder' : '—'}</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`Se grunnlaget for sak ${item.item_no}`}
                      onClick={() => setSelected(item.record_id)}
                    >
                      <ChevronRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && <p className="empty-filter">Ingen saker i dette utvalget.</p>}
        </div>
      </div>
      {selectedItem && (
        <Detail
          item={selectedItem}
          onClose={closeDetail}
          decision={
            FINISHED.includes(job.status)
              ? { jobId: job.id, index: job.items.indexOf(selectedItem), onJob }
              : undefined
          }
        />
      )}
    </section>
  );
}

const FINISHED = ['completed', 'needs_attention', 'failed'];
const VOTE_LABEL: Record<string, string> = { FOR: 'For', MOT: 'Mot', AVSTÅ: 'Avstå' };

interface HumanVote {
  vote: string;
  note: string;
  decided_at: string;
  agent_vote?: string;
}

interface DecisionTarget {
  jobId: string;
  index: number;
  onJob?: (job: Job) => void;
}

/** The reviewer's own vote. It closes a manual case and is written to the job's event log. */
function HumanDecision({ item, target }: { item: Item; target: DecisionTarget }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const r = item.result;
  if (!r) return null;
  const human = (r as typeof r & { human_decision?: HumanVote }).human_decision;
  const decide = async (vote: string) => {
    setBusy(true);
    setError('');
    try {
      const res = await api<{ job: Job }>(`/jobs/${target.jobId}/items/${target.index}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vote, note }),
      });
      setNote('');
      target.onJob?.(res.job);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Kunne ikke lagre vedtaket.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="detail-block human-decision">
      <h3>
        <UserCheck size={17} /> Ditt vedtak
      </h3>
      {human ? (
        <p>
          Du valgte <strong>{VOTE_LABEL[human.vote] || human.vote}</strong>. Agentens forslag var{' '}
          {r.needs_human_review || human.agent_vote === undefined
            ? 'manuell vurdering'
            : VOTE_LABEL[human.agent_vote] || human.agent_vote}
          {human.note ? ` · «${human.note}»` : ''}. Du kan endre valget.
        </p>
      ) : (
        <p className="muted small">
          {r.needs_human_review
            ? 'Saken trenger en menneskelig vurdering. Velg stemme for å lukke den.'
            : 'Du kan overstyre forslaget. Valget lagres i behandlingsloggen.'}
        </p>
      )}
      <textarea
        className="human-note"
        rows={2}
        maxLength={500}
        placeholder="Kort begrunnelse (valgfritt)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="human-actions">
        {['FOR', 'MOT', 'AVSTÅ'].map((v) => (
          <button
            key={v}
            className={'button secondary compact' + (human?.vote === v ? ' active' : '')}
            disabled={busy}
            onClick={() => decide(v)}
          >
            {VOTE_LABEL[v]}
          </button>
        ))}
      </div>
      {error && <p className="soft-note">{error}</p>}
    </section>
  );
}

function Detail({
  item,
  onClose,
  decision,
}: {
  item: Item;
  onClose: () => void;
  decision?: DecisionTarget;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab') return;
      const focusable = panel.current?.querySelectorAll<HTMLElement>('button, a[href]');
      if (!focusable?.length) return;
      const first = focusable[0],
        last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', key);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [onClose]);
  const r = item.result;
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-title"
        ref={panel}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-top">
          <span className="eyebrow">GRUNNLAG FOR ANBEFALINGEN</span>
          <button ref={close} className="icon-button" onClick={onClose} aria-label="Lukk detaljer">
            <X size={20} />
          </button>
        </div>
        <div className="drawer-content">
          <span className="muted small">
            SAK {item.item_no} · {item.company || 'Selskapsnavn ikke oppgitt'}
          </span>
          <h2 id="detail-title">{item.proposal_text}</h2>
          <p className="muted small">Generalforsamling {date(item.meeting_date)}</p>
          <div className="decision-card">
            <div>
              <span className="eyebrow">VALG</span>
              <VoteBadge item={item} />
              {r?.needs_human_review && (
                <small>Reservevalg: Avstå · ikke godkjent anbefaling</small>
              )}
            </div>
            <div>
              <span className="eyebrow">AGENTENS KONFIDENS</span>
              <strong>{confidence(r)}</strong>
              <small>ikke en målt treffsikkerhet</small>
            </div>
          </div>
          {decision && <HumanDecision item={item} target={decision} />}
          <TriagePanel item={item} />
          <section className="detail-block">
            <h3>Begrunnelse</h3>
            <p>{r?.reason || 'Denne saken venter på behandling.'}</p>
          </section>
          <section className="detail-block">
            <h3>
              <ShieldCheck size={17} /> Retningslinjene som ble brukt
            </h3>
            {r?.citations.length ? (
              r.citations.map((c, i) => (
                <article className="citation" key={c.policy_id + i}>
                  <div>
                    <span className="policy-chip">{c.policy_id}</span>
                    <a href={c.source_url} target="_blank" rel="noreferrer">
                      NBIM · {c.locator}
                      <ArrowUpRight size={13} />
                    </a>
                  </div>
                  <blockquote>{c.policy_excerpt}</blockquote>
                  <span className="eyebrow">
                    GRUNNLAG I SAKSLISTEN{item.source_ref ? ` · SIDE ${item.source_ref.page}` : ''}
                  </span>
                  <p className="source-quote">“{c.evidence_quote}”</p>
                  <small>
                    {triaged(item).result?.check === 'light'
                      ? 'Historisk standardbegrunnelse fra NBIM. Lett kontroll har ikke samme sitatverifikasjon som fullflyten.'
                      : 'Retningslinjen er en kuratert parafrase. Lenken viser originalkilden.'}
                  </small>
                </article>
              ))
            ) : (
              <div className="soft-note">
                Ingen godkjente kildehenvisninger. Saken kan ikke regnes som ferdig vurdert.
              </div>
            )}
          </section>
          {r && (
            <section className="detail-block">
              <h3>
                <CheckCheck size={17} />{' '}
                {triaged(item).result?.check === 'light'
                  ? 'Lett agentkontroll'
                  : 'Kontrollagentens vurdering'}
              </h3>
              <p>{r.review_reason}</p>
              <div className="inline-facts">
                <span>{r.attempts} forsøk</span>
                <span>{r.retries} gjentakelser</span>
                <span>{Math.round(r.duration_ms / 1000)} sekunder</span>
              </div>
            </section>
          )}
          <section className="detail-block">
            <h3>
              <FileText size={17} /> Originalt saksgrunnlag
            </h3>
            <blockquote className="original-quote">{item.proposal_text}</blockquote>
            {item.source_ref && (
              <small>Uttrekket er kontrollert mot side {item.source_ref.page} i dokumentet.</small>
            )}
          </section>
          {r && (
            <details className="audit-details">
              <summary>
                <Fingerprint size={16} /> Behandlingslogg og vannmerke
                <ChevronRight size={15} />
              </summary>
              <ol className="audit-list">
                {r.trace.map((e, i) => (
                  <li key={i}>
                    <span className={'audit-dot ' + (e.accepted ? 'passed' : '')} />
                    <div>
                      <strong>
                        {
                          (
                            {
                              attempt_started: 'Vurdering startet',
                              recommendation: 'Agentens foreløpige forslag',
                              source_validation: 'Kildekontroll',
                              verification: e.accepted
                                ? 'Anbefalingen ble godkjent'
                                : 'Anbefalingen ble avvist',
                              finalized: 'Resultatet ble lagret',
                              cache_hit: 'Lagret resultat gjenbrukt',
                              triage: 'Triagemodellen',
                              light_check: 'Lett agentkontroll',
                            } as Record<string, string>
                          )[e.event]
                        }
                      </strong>
                      <small>
                        Forsøk {e.attempt} · {new Date(e.timestamp).toLocaleTimeString('nb-NO')}
                      </small>
                      {e.detail && <p>{e.detail}</p>}
                    </div>
                  </li>
                ))}
              </ol>
              <small className="hash-label">Saksgrunnlag</small>
              <code>{item.evidence_hash}</code>
              <small className="hash-label">Kjørings-ID</small>
              <code>{r.run_key}</code>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}
