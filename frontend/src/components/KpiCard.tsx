interface KpiCardProps {
  label: string;
  value: string;
  /** The qualifier under the figure — what it is measured over. */
  unit?: string;
  /** Orange: something here is worth acting on. */
  emphasis?: boolean;
  /** Red: a constraint is being exceeded. */
  alert?: boolean;
}

/**
 * One headline figure.
 *
 * `unit` is not decoration. "5" alone is meaningless and "$44,719" invites the
 * question "over what?" — the qualifier is the difference between a number and
 * a fact.
 */
export function KpiCard({ label, value, unit, emphasis, alert }: KpiCardProps) {
  const valueColour = alert
    ? "text-alert"
    : emphasis
      ? "text-signal"
      : "text-ink-strong";

  return (
    <div className="rounded-lg border border-rule bg-surface px-4 py-3">
      <p className="text-[12px] text-ink-soft">{label}</p>
      <p
        className={`tabular mt-1 truncate text-[24px] font-semibold leading-tight tracking-[-0.02em] ${valueColour}`}
      >
        {value}
      </p>
      {unit && <p className="mt-0.5 text-[12px] text-ink-faint">{unit}</p>}
    </div>
  );
}
