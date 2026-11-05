import { ArrowDownRight, ArrowUpRight, Gauge, History, ScrollText, Zap } from 'lucide-react';
import type { Item } from '../lib/types';
import { pct, triaged } from '../model/types';
import '../model/model.css';

/** Table cell: the triage model's risk score and what happened to the item. */
export function RiskCell({ item }: { item: Item }) {
  const it = triaged(item);
  const t = it.triage;
  if (!t) return <span className="muted">—</span>;
  const state = t.flagged
    ? { cls: 'flagged', text: 'Flagget' }
    : it.safety_routed
      ? { cls: 'flagged', text: 'Sikkerhetsport' }
      : it.policy_routed
        ? { cls: 'escalated', text: 'Policyregel' }
        : it.escalated
          ? { cls: 'escalated', text: 'Eskalert' }
          : it.result?.check === 'light'
            ? { cls: 'light', text: 'Lett kontroll' }
            : { cls: 'low', text: 'Lav risiko' };
  return (
    <div className="risk-cell" title={`Terskel ${pct(t.threshold)} · ${t.lane_label}`}>
      <span className="confidence-number">{pct(t.risk)}</span>
      <span className="risk-bar">
        <i
          className={t.flagged ? 'hot' : ''}
          style={{ width: `${Math.min(100, Math.max(3, t.risk * 100))}%` }}
        />
        <b style={{ left: `${Math.min(100, t.threshold * 100)}%` }} />
      </span>
      <span className={'risk-chip ' + state.cls}>{state.text}</span>
    </div>
  );
}

/** Drawer section: why the model ranked the item where it did, and what the agents did with it. */
export function TriagePanel({ item }: { item: Item }) {
  const it = triaged(item);
  const t = it.triage;
  if (!t) return null;
  const route = t.flagged
    ? 'Flagget: saken gikk først til full agentvurdering med kontrollagent.'
    : it.safety_routed
      ? 'Teksten ligner et instruksjonsangrep. Saken gikk forbi den lette kontrollen til sikkerhetsporten, som sender den til manuell vurdering uten modellkall.'
      : it.policy_routed
        ? `Lav modellrisiko, men policyregelen ${it.policy_routed} dekker saken eksplisitt. Den gikk derfor til full agentvurdering.`
        : it.escalated
          ? 'Lav modellrisiko, men den lette agentkontrollen fant noe å se på. Saken ble eskalert til full vurdering.'
          : 'Lav modellrisiko. En lett agentkontroll bekreftet at stemmen kan følge styrets anbefaling.';
  return (
    <section className="detail-block triage-block">
      <h3>
        <Gauge size={17} /> Triagemodellen
      </h3>
      <div className="triage-head">
        <div>
          <span className="eyebrow">RISIKO FOR STEMME MOT STYRET</span>
          <strong className={t.flagged ? 'hot' : ''}>{pct(t.risk)}</strong>
          <small>
            terskel {pct(t.threshold)} · {t.lane_label} · høyere enn {pct(t.percentile)} av
            sammenlignbare saker i valideringsåret
          </small>
        </div>
        <span
          className={'risk-chip ' + (t.flagged ? 'flagged' : it.escalated ? 'escalated' : 'light')}
        >
          {t.flagged ? 'Full vurdering' : it.escalated ? 'Eskalert' : 'Lett kontroll'}
        </span>
      </div>
      <p className="triage-route">{route}</p>
      {(t.reasons.length > 0 || t.protective.length > 0) && (
        <div className="reason-columns">
          <div>
            <span className="eyebrow">TREKKER OPP</span>
            {t.reasons.length ? (
              t.reasons.map((r) => (
                <p key={r.label} className="reason up">
                  <ArrowUpRight size={13} /> {r.label}
                </p>
              ))
            ) : (
              <p className="reason muted">Ingen tydelige risikosignaler</p>
            )}
          </div>
          <div>
            <span className="eyebrow">TREKKER NED</span>
            {t.protective.length ? (
              t.protective.map((r) => (
                <p key={r.label} className="reason down">
                  <ArrowDownRight size={13} /> {r.label}
                </p>
              ))
            ) : (
              <p className="reason muted">—</p>
            )}
          </div>
        </div>
      )}
      {it.model_note && (it.model_note.justification || it.model_note.guideline !== 'none') && (
        <div className="model-note">
          <span className="eyebrow">
            <ScrollText size={12} /> BEGRUNNELSESUTKAST FRA LOKAL MODELL (ENGELSK)
          </span>
          <p>
            {it.model_note.guideline && it.model_note.guideline !== 'none' && (
              <span className="policy-chip">{it.model_note.guideline}</span>
            )}{' '}
            {it.model_note.justification || 'Ingen begrunnelse generert.'}
          </p>
        </div>
      )}
      {it.light_check && (
        <div className="model-note">
          <span className="eyebrow">
            <Zap size={12} /> LETT AGENTKONTROLL
          </span>
          <p>
            <strong>
              {it.light_check.decision === 'FOLLOW_BOARD' ? 'Følg styret' : 'Eskaler'}
            </strong>
            {it.light_check.guideline && it.light_check.guideline !== 'none'
              ? ` · ${it.light_check.guideline}`
              : ''}{' '}
            · {it.light_check.failed ? 'ugyldig svar, sendt videre' : it.light_check.reason}
          </p>
        </div>
      )}
      <div className="precedent">
        <span className="eyebrow">
          <History size={12} /> NBIMS TIDLIGERE MOT-STEMMER (SELSKAP / PERSON)
        </span>
        {t.precedent.length ? (
          t.precedent.map((p, i) => (
            <p key={p.date + i}>
              <span className="muted">{p.date}</span> {p.proposal_text}
              {p.guideline && <span className="policy-chip">{p.guideline}</span>}
              {p.same_person && <span className="risk-chip escalated">samme person</span>}
              {!p.same_person && p.same_type && <span className="risk-chip">samme sakstype</span>}
            </p>
          ))
        ) : (
          <p className="muted">Ingen tidligere mot-stemmer i dataene.</p>
        )}
      </div>
      <div className="inline-facts">
        <span>
          Sakstype {t.proposal_type.toLowerCase().replace(/_/g, ' ')}
          {t.type_inferred ? ' (beregnet)' : ''}
        </span>
        <span>{t.company_known ? 'Kjent selskap' : 'Ukjent selskap: ingen historikk'}</span>
        <span>{t.model_version}</span>
      </div>
      <small className="triage-foot">
        Modellen rangerer og flagger saker; den stemmer ikke. Navn og årstall er maskert, og
        historikken bruker bare møter før denne datoen.
      </small>
    </section>
  );
}
