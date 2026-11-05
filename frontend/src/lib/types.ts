// Stand-in reconstructed from component usage: the original frontend/src/lib was excluded by the
// Python `lib/` rule in .gitignore. Replace with the author's file when it is committed.

export type Vote = 'FOR' | 'MOT' | 'AVSTÅ';

export interface Citation {
  policy_id: string;
  locator: string;
  source_url: string;
  policy_excerpt: string;
  evidence_quote: string;
}

export interface TraceEvent {
  event: string;
  attempt: number;
  timestamp: string;
  detail: string;
  accepted?: boolean | null;
}

export interface Result {
  run_key: string;
  status: string;
  vote: Vote;
  confidence: number | null;
  reason: string;
  review_reason: string;
  citations: Citation[];
  attempts: number;
  retries: number;
  needs_human_review: boolean;
  fallback_type?: string | null;
  duration_ms: number;
  updated_at?: string;
  trace: TraceEvent[];
}

export interface Item {
  record_id: string;
  item_no: string;
  proposal_text: string;
  company?: string;
  meeting_date: string;
  evidence_hash?: string;
  cached?: boolean;
  source_ref?: { page: number } | null;
  result: Result | null;
}

export interface JobSummary {
  id: string;
  filename: string;
  status: string;
  done: number;
  total: number;
  created_at: string;
}

export interface Job extends JobSummary {
  stage: string;
  items: Item[];
  cached: number;
  api_calls: number;
  error: string | null;
  model: string;
  reviewer_model?: string;
  current_record?: string | null;
  attempt?: number;
  updated_at?: string;
}

export interface SourceReport {
  total_rows: number;
  date_range: { min: string; max: string };
  input_sha256?: string;
  preprocessing_version?: string;
  [key: string]: unknown;
}

export interface Source {
  id: string;
  name: string;
  report: SourceReport;
  counts: Record<string, number>;
  known: number;
  quarantined: number;
}

export interface PolicyRule {
  id: string;
  locator: string;
  text: string;
  [key: string]: unknown;
}

export interface Bootstrap {
  model: { name: string; reviewer: string; provider: string; available: boolean; detail: string };
  policy: {
    version: string;
    valid_from: string;
    valid_through: string;
    source_url: string;
    rules: PolicyRule[];
  };
  sources: Source[];
  limits: { max_mb: number; max_items: number; max_attempts: number };
}
