import type { Bootstrap } from '../lib/types';
import { number } from '../lib/format';

/** Actual historical counts, not market prices or simulated live data. */
export function TerminalTape({ info }: { info: Bootstrap | null }) {
  const source = info?.sources.find((s) => s.id === 'real');
  return (
    <div className="terminal-tape" aria-label="Historiske stemmetall fra NBIM">
      <span className="tape-label">NBIM / HISTORIKK</span>
      {[
        ['SAKER', source?.report.total_rows, ''],
        ['FOR', source?.counts.FOR, 'positive'],
        ['MOT', source?.counts.MOT, 'negative'],
        ['AVSTÅ', source?.counts['AVSTÅ'], 'abstain'],
        ['UKJENT', source?.counts.UKJENT, 'unknown'],
      ].map(([label, count, tone]) => (
        <span className="tape-item" key={String(label)}>
          <span>{label}</span>
          <strong className={String(tone)}>
            {typeof count === 'number' ? number(count) : '—'}
          </strong>
        </span>
      ))}
      <span className="tape-note">ORIGINALDATA · INGEN SIMULERTE TALL</span>
    </div>
  );
}
