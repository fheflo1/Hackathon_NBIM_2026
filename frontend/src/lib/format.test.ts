import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confidence, finished, tally } from './format.ts';
import type { Item, Result } from './types.ts';

const result = (over: Partial<Result>): Result => ({
  run_key: 'k',
  status: 'verified',
  vote: 'FOR',
  confidence: 0.9,
  reason: '',
  review_reason: '',
  citations: [],
  attempts: 1,
  retries: 0,
  needs_human_review: false,
  duration_ms: 0,
  trace: [],
  ...over,
});
const item = (r: Result | null): Item => ({
  record_id: Math.random().toString(),
  item_no: '1',
  proposal_text: 'x',
  meeting_date: '2024-01-01',
  result: r,
});

test('only terminal statuses count as finished', () => {
  for (const status of ['completed', 'needs_attention', 'failed'])
    assert.equal(finished({ status }), true);
  for (const status of ['queued', 'reading', 'processing'])
    assert.equal(finished({ status }), false);
});

test('tally keeps manual review and pending apart from verified votes', () => {
  const counts = tally([
    item(result({ vote: 'FOR' })),
    item(result({ vote: 'MOT' })),
    item(result({ vote: 'MOT', needs_human_review: true, status: 'human_review' })),
    item(null),
  ]);
  assert.deepEqual(counts, { FOR: 1, MOT: 1, AVSTÅ: 0, manual: 1, pending: 1 });
});

test('confidence is only shown for verified results', () => {
  assert.equal(confidence(result({ status: 'human_review' })), '—');
  assert.equal(confidence(null), '—');
  assert.notEqual(confidence(result({ confidence: 0.9 })), '—');
});
