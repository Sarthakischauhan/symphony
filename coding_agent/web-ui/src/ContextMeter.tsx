import type { ContextGauge, UsageBreakdown } from "./events";

// 92200 → "92.2k", 128000 → "128k", 1048576 → "1m".
export function tokens(value: number) {
  const scaled = (n: number, unit: string) =>
    `${Number.isInteger(Math.round(n * 10) / 10) ? Math.round(n) : (Math.round(n * 10) / 10).toFixed(1)}${unit}`;
  if (value >= 1_000_000) return scaled(value / 1_000_000, "m");
  if (value >= 1000) return scaled(value / 1000, "k");
  return String(value);
}
export type Level = "low" | "warning" | "critical";
// Green below 60%, amber from 60% to 85%, red above 85%.
export const level = (fraction: number): Level =>
  fraction > 0.85 ? "critical" : fraction >= 0.6 ? "warning" : "low";

const RADIUS = 6;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * Header context gauge from the protocol `context` event (tokens_used,
 * context_limit) with the latest `usage` breakdown on hover. Rows appear only
 * for fields the usage payload carries.
 */
export function ContextMeter({
  context,
  usage,
}: {
  context: ContextGauge | null;
  usage: UsageBreakdown | null;
}) {
  if (!context?.limit) return null;
  const fraction = Math.min(1, context.used / context.limit);
  const tone = level(fraction);
  const summary = `${tokens(context.used)} / ${tokens(context.limit)}`;
  const rows: [string, number | undefined][] = [
    ["Input", usage?.input],
    ["Output", usage?.output],
    ["Reasoning", usage?.reasoning],
  ];
  return (
    <div
      className="context-meter"
      data-level={tone}
      tabIndex={0}
      aria-label={`Context ${Math.round(fraction * 100)}% full, ${summary} tokens`}
    >
      <svg className="context-ring" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r={RADIUS} className="context-ring-track" />
        <circle
          cx="8"
          cy="8"
          r={RADIUS}
          className="context-ring-fill"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
        />
      </svg>
      <span className="context-text">{summary}</span>
      <div className="context-popover" role="tooltip">
        <div className="context-popover-head">
          <span className="context-percent">{Math.round(fraction * 100)}% full</span>
          <span className="context-total">{summary}</span>
        </div>
        <div className="context-bar" aria-hidden="true">
          <span style={{ width: `${fraction * 100}%` }} />
        </div>
        {rows.some(([, value]) => value !== undefined) && (
          <dl className="context-rows">
            {rows.map(([label, value]) =>
              value === undefined ? null : (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{tokens(value)}</dd>
                </div>
              ),
            )}
          </dl>
        )}
      </div>
    </div>
  );
}
