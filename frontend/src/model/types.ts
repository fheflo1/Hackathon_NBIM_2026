// Types for the triage model (src/nbim_flow/triage.py) as it appears in /api/model and job items.
import type { Item, Job, Result } from '../lib/types';

export interface Reason {
  label: string;
  weight: number;
}

export interface Precedent {
  date: string;
  proposal_text: string;
  guideline: string | null;
  same_person: boolean;
  same_type?: boolean;
}

export interface Triage {
  model_version: string;
  risk: number;
  lane: 'A' | 'B';
  lane_label: string;
  threshold: number;
  flagged: boolean;
  percentile: number;
  proposal_type: string;
  type_inferred: boolean;
  company_known: boolean;
  follow_board_vote: string;
  reasons: Reason[];
  protective: Reason[];
  precedent: Precedent[];
  suggested_guideline: string | null;
  facts: Record<string, number | string>;
}

export interface LightCheck {
  decision: string;
  guideline: string;
  reason: string;
  confidence: number;
  failed?: boolean;
  duration_ms?: number;
}

export interface ModelNote {
  guideline: string;
  justification: string;
  confidence: number;
  failed?: boolean;
}

export type TriagedItem = Item & {
  triage?: Triage | null;
  light_check?: LightCheck;
  model_note?: ModelNote;
  escalated?: boolean;
  safety_routed?: boolean;
  policy_routed?: string;
  result: (Result & { check?: 'light' | 'full' }) | null;
};

export type TriagedJob = Job & {
  light_calls?: number;
  escalated?: number;
  triage_summary?: { model: string | null; items: number; flagged: number; light_workers: number };
};

export interface Metrics {
  precision: number;
  recall: number;
  f1: number;
  tp: number;
  fp: number;
  fn: number;
  flagged: number;
  accuracy: number;
  items: number;
  against: number;
}

export interface CurvePoint {
  scale: number;
  threshold_A: number;
  threshold_B: number;
  precision: number;
  recall: number;
  f1: number;
  flagged: number;
  tp: number;
  fp: number;
  fn: number;
  review_share: number;
}

export type HoldoutMetrics = Metrics & {
  average_precision: number | null;
  recall_at_15pct_review: number | null;
};

export interface HoldoutReport {
  years: number[];
  trained_through: number;
  thresholds: { A: number; B: number };
  all: HoldoutMetrics;
  lane_A: HoldoutMetrics;
  lane_B: HoldoutMetrics;
  by_year: Record<string, HoldoutMetrics>;
  always_with_board: Metrics;
  type_prior_average_precision: number;
  prevalence: number;
}

export interface ModelCard {
  holdout?: { frozen: HoldoutReport; retrained_2024: HoldoutReport; protocol: string };
  available: boolean;
  detail?: string;
  version: string;
  trained_through: number;
  validated_on: number;
  thresholds: { A: number; B: number };
  validation: {
    year: number;
    all: Metrics;
    lane_A: Metrics;
    lane_B: Metrics;
    always_with_board: Metrics;
    average_precision: number;
    average_precision_A: number;
    average_precision_B: number;
  };
  curve: CurvePoint[];
  type_accuracy: number;
  data_sha256: string;
  catalogue: Record<string, { text: string; position_paper: string; count: number }>;
  top_signals: { feature: string; label: string; weight: number }[];
  light_workers: number;
}

export const triaged = (item: Item) => item as TriagedItem;
export const pct = (value: number) => `${Math.round((value || 0) * 100)} %`;
