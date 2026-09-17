import { formatPct } from "@/lib/format";

/** Diagonal hatch: used wherever a value is unknown, never where one is low. */
const HATCH =
  "repeating-linear-gradient(135deg, var(--color-rule) 0 3px, transparent 3px 7px)";

interface SoilingBarProps {
  /** s0. Null renders the whole track as unknown. */
  soilingPct: number | null;
  /** s*, the break-even line. */
  breakEvenPct: number;
  /** Shared upper bound for every bar in the region. */
  axisMax: number;
  /** True once the overshoot is large enough to act on. */
  isRecommended: boolean;
  label: string;
}

/**
 * Today's soiling drawn against the break-even line on the region's shared
 * axis. The decision is the segment between them, so that segment is the only
 * thing on the page in the signal colour.
 */
export function SoilingBar({
  soilingPct,
  breakEvenPct,
  axisMax,
  isRecommended,
  label,
}: SoilingBarProps) {
  const toPercent = (value: number) => `${Math.min(100, (value / axisMax) * 100)}%`;
  const breakEvenLeft = toPercent(breakEvenPct);

  if (soilingPct === null) {
    return (
      <div className="relative h-4" role="img" aria-label={label}>
        <div
          className="absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-[1px] border border-rule"
          style={{ backgroundImage: HATCH }}
        />
        <BreakEvenMarker left={breakEvenLeft} />
      </div>
    );
  }

  const overshoot = soilingPct > breakEvenPct;

  return (
    <div className="relative h-4" role="img" aria-label={label}>
      <div className="absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-[1px] bg-paper ring-1 ring-rule ring-inset" />
      <div
        className="absolute top-1/2 left-0 h-2.5 -translate-y-1/2 rounded-l-[1px] bg-ink-soft"
        style={{ width: toPercent(Math.min(soilingPct, breakEvenPct)) }}
      />
      {overshoot && (
        <div
          className={`absolute top-1/2 h-2.5 -translate-y-1/2 ${
            isRecommended ? "bg-signal" : "bg-signal/45"
          }`}
          style={{
            left: breakEvenLeft,
            width: `${Math.max(0.4, ((soilingPct - breakEvenPct) / axisMax) * 100)}%`,
          }}
        />
      )}
      <BreakEvenMarker left={breakEvenLeft} />
    </div>
  );
}

function BreakEvenMarker({ left }: { left: string }) {
  return (
    <div
      className="absolute top-1/2 h-4 w-px -translate-x-1/2 -translate-y-1/2 bg-ink"
      style={{ left }}
    />
  );
}

/** The alt text for a bar, spelled out for screen readers and for hover. */
export function soilingBarLabel(soilingPct: number | null, breakEvenPct: number): string {
  if (soilingPct === null) {
    return `Soiling not estimable. Break-even ${formatPct(breakEvenPct)}.`;
  }
  return `Soiling ${formatPct(soilingPct)} against break-even ${formatPct(breakEvenPct)}.`;
}
