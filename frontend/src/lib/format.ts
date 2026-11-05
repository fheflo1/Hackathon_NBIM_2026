// Stand-in reconstructed from component usage (see types.ts).
import type { Item, Job, Result } from './types';

const TERMINAL = new Set(['completed', 'needs_attention', 'failed']);

export function finished(job: Pick<Job, 'status'>): boolean {
  return TERMINAL.has(job.status);
}

export function date(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString('nb-NO', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function number(value: number): string {
  return new Intl.NumberFormat('nb-NO').format(value || 0);
}

export function percent(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('nb-NO', {
    style: 'percent',
    maximumFractionDigits: digits,
  }).format(value);
}

export function confidence(result: Result | null | undefined): string {
  if (!result || result.status !== 'verified' || result.confidence == null) return '—';
  return percent(result.confidence);
}

export function tally(items: Item[]) {
  const counts = { FOR: 0, MOT: 0, AVSTÅ: 0, manual: 0, pending: 0 };
  for (const item of items) {
    const r = item.result;
    if (!r) counts.pending += 1;
    else if (r.needs_human_review) counts.manual += 1;
    else if (r.status === 'verified') counts[r.vote] += 1;
  }
  return counts;
}

export const labels: Record<string, string> = {
  queued: 'I kø',
  reading: 'Leser',
  processing: 'Behandles',
  completed: 'Ferdig',
  needs_attention: 'Må følges opp',
  failed: 'Stoppet',
};

export const stages: Record<string, string> = {
  queued: 'I kø',
  reading: 'Leser sakslisten',
  extract: 'Henter ut agendapunkter',
  triage: 'Triagemodellen rangerer sakene',
  recommend: 'Agenten vurderer saken',
  validate: 'Kontrollerer kildene',
  review: 'Kontrollagenten etterprøver',
  done: 'Ferdig',
  failed: 'Stoppet',
  interrupted: 'Avbrutt',
};
