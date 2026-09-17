"use client";

import { useState } from "react";
import type { HistoryPoint } from "@/lib/contract";
import { formatDateShort, formatPct } from "@/lib/format";

/** Rain at or above this washes panels, per the brief's data dictionary. */
const WASHING_RAIN_MM = 8;

const VIEW_WIDTH = 640;
const VIEW_HEIGHT = 150;
const PADDING = { left: 36, right: 10, top: 10, bottom: 24 };
const PLOT_WIDTH = VIEW_WIDTH - PADDING.left - PADDING.right;
const PLOT_HEIGHT = VIEW_HEIGHT - PADDING.top - PADDING.bottom;

interface HistoryChartProps {
  history: HistoryPoint[];
  breakEvenPct: number;
}

/**
 * Soiling since the start of the window, against the break-even line.
 *
 * Withheld days are drawn as hatched gaps in the line, not as low points. A
 * withheld day is a day with no soiling estimate; drawing its raw deficit would
 * put a number on the chart that the rest of the system refuses to use.
 */
export function HistoryChart({ history, breakEvenPct }: HistoryChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (history.length === 0) {
    return <p className="text-[13px] text-ink-soft">No history returned for this plant.</p>;
  }

  const usableValues = history
    .filter((point) => point.flag === "USABLE" && point.soiling_loss_pct !== null)
    .map((point) => point.soiling_loss_pct as number);
  const axisMax = Math.max(breakEvenPct, ...usableValues, 1) * 1.15;

  const x = (index: number) =>
    history.length === 1
      ? PADDING.left + PLOT_WIDTH / 2
      : PADDING.left + (index / (history.length - 1)) * PLOT_WIDTH;
  const y = (value: number) => PADDING.top + PLOT_HEIGHT - (value / axisMax) * PLOT_HEIGHT;

  const segments = usableSegments(history);
  const bandWidth = history.length > 1 ? PLOT_WIDTH / (history.length - 1) : PLOT_WIDTH;
  const breakEvenY = y(breakEvenPct);
  const hovered = hoverIndex === null ? null : history[hoverIndex];

  return (
    <figure className="m-0">
      <div
        className="relative"
        onPointerLeave={() => setHoverIndex(null)}
        onPointerMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const fraction = (event.clientX - bounds.left) / bounds.width;
          const plotFraction =
            (fraction * VIEW_WIDTH - PADDING.left) / PLOT_WIDTH;
          const index = Math.round(plotFraction * (history.length - 1));
          setHoverIndex(Math.min(history.length - 1, Math.max(0, index)));
        }}
      >
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          className="w-full"
          role="img"
          aria-label={chartSummary(history, breakEvenPct)}
        >
          <defs>
            <pattern
              id="withheld-hatch"
              width="6"
              height="6"
              patternTransform="rotate(135)"
              patternUnits="userSpaceOnUse"
            >
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--color-rule-strong)" strokeWidth="1.4" />
            </pattern>
          </defs>

          <line
            x1={PADDING.left}
            y1={PADDING.top + PLOT_HEIGHT}
            x2={VIEW_WIDTH - PADDING.right}
            y2={PADDING.top + PLOT_HEIGHT}
            stroke="var(--color-rule)"
          />

          {history.map((point, index) =>
            point.flag === "USABLE" ? null : (
              <rect
                key={`withheld-${point.date}`}
                x={x(index) - bandWidth / 2}
                y={PADDING.top}
                width={bandWidth}
                height={PLOT_HEIGHT}
                fill="url(#withheld-hatch)"
                opacity={0.55}
              />
            ),
          )}

          <line
            x1={PADDING.left}
            y1={breakEvenY}
            x2={VIEW_WIDTH - PADDING.right}
            y2={breakEvenY}
            stroke="var(--color-signal)"
            strokeWidth="1.5"
            strokeDasharray="5 4"
          />

          {segments.map((segment) =>
            // A run of one usable day between two withheld days has no line to
            // draw, so it is shown as the single reading it is.
            segment.length === 1 ? (
              <circle
                key={`series-${segment[0].index}`}
                cx={x(segment[0].index)}
                cy={y(segment[0].value)}
                r="2.5"
                fill="var(--color-ink-soft)"
              />
            ) : (
              <polyline
                key={`series-${segment[0].index}`}
                points={segment
                  .map(({ index, value }) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`)
                  .join(" ")}
                fill="none"
                stroke="var(--color-ink-soft)"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ),
          )}

          {history.map((point, index) =>
            point.cleaned ? (
              <EventTick key={`clean-${point.date}`} x={x(index)} kind="cleaned" />
            ) : null,
          )}
          {history.map((point, index) =>
            (point.rain_mm ?? 0) >= WASHING_RAIN_MM ? (
              <EventTick key={`rain-${point.date}`} x={x(index)} kind="rain" />
            ) : null,
          )}

          {hovered && (
            <line
              x1={x(hoverIndex as number)}
              y1={PADDING.top}
              x2={x(hoverIndex as number)}
              y2={PADDING.top + PLOT_HEIGHT}
              stroke="var(--color-ink)"
              strokeWidth="1"
            />
          )}
          {hovered && hovered.flag === "USABLE" && hovered.soiling_loss_pct !== null && (
            <circle
              cx={x(hoverIndex as number)}
              cy={y(hovered.soiling_loss_pct)}
              r="4"
              fill="var(--color-surface)"
              stroke="var(--color-ink)"
              strokeWidth="2"
            />
          )}

          <text x="0" y={PADDING.top + 4} className="fill-ink-faint text-[11px]">
            {axisMax.toFixed(1)}%
          </text>
          <text x="0" y={PADDING.top + PLOT_HEIGHT} className="fill-ink-faint text-[11px]">
            0%
          </text>
          <text
            x={PADDING.left}
            y={VIEW_HEIGHT - 6}
            className="fill-ink-faint text-[11px]"
          >
            {formatDateShort(history[0].date)}
          </text>
          <text
            x={VIEW_WIDTH - PADDING.right}
            y={VIEW_HEIGHT - 6}
            textAnchor="end"
            className="fill-ink-faint text-[11px]"
          >
            {formatDateShort(history[history.length - 1].date)}
          </text>
        </svg>

        {hovered && (
          <div
            className="tabular pointer-events-none absolute top-0 z-10 w-max max-w-[220px] -translate-x-1/2 border border-rule bg-surface px-2 py-1 text-[12px] shadow-sm"
            style={{
              left: `${Math.min(88, Math.max(12, ((x(hoverIndex as number) / VIEW_WIDTH) * 100)))}%`,
            }}
          >
            <p className="font-medium">{formatDateShort(hovered.date)}</p>
            <p className="text-ink-soft">
              {hovered.flag === "USABLE" && hovered.soiling_loss_pct !== null
                ? `soiling ${formatPct(hovered.soiling_loss_pct)}`
                : "withheld from the estimate"}
            </p>
            {(hovered.rain_mm ?? 0) > 0 && (
              <p className="text-ink-soft">rain {(hovered.rain_mm ?? 0).toFixed(1)} mm</p>
            )}
            {hovered.cleaned && <p className="text-ink-soft">cleaned</p>}
          </div>
        )}
      </div>

      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-faint">
        <LegendKey swatch={<span className="h-0.5 w-4 bg-ink-soft" />} label="soiling" />
        <LegendKey
          swatch={
            <span className="h-0 w-4 border-t-2 border-dashed border-signal" aria-hidden />
          }
          label={`break-even ${formatPct(breakEvenPct)}`}
        />
        <LegendKey
          swatch={
            <span
              className="h-3 w-4 border border-rule"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(135deg, var(--color-rule-strong) 0 1.5px, transparent 1.5px 5px)",
              }}
            />
          }
          label="withheld day, no estimate"
        />
        <LegendKey
          swatch={<span className="h-3 w-px bg-ink-faint" />}
          label={`rain ≥ ${WASHING_RAIN_MM} mm`}
        />
        <LegendKey swatch={<span className="h-2 w-2 bg-ink" />} label="cleaned" />
      </figcaption>
    </figure>
  );
}

function EventTick({ x, kind }: { x: number; kind: "rain" | "cleaned" }) {
  const baseline = PADDING.top + PLOT_HEIGHT;
  if (kind === "cleaned") {
    return <rect x={x - 2.5} y={baseline - 5} width="5" height="5" fill="var(--color-ink)" />;
  }
  return (
    <line
      x1={x}
      y1={baseline}
      x2={x}
      y2={baseline - 6}
      stroke="var(--color-ink-faint)"
      strokeWidth="1.5"
    />
  );
}

function LegendKey({ swatch, label }: { swatch: React.ReactNode; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {swatch}
      {label}
    </span>
  );
}

/** Consecutive runs of usable readings, so withheld days break the line. */
function usableSegments(
  history: HistoryPoint[],
): Array<Array<{ index: number; value: number }>> {
  const segments: Array<Array<{ index: number; value: number }>> = [];
  let current: Array<{ index: number; value: number }> = [];

  history.forEach((point, index) => {
    if (point.flag === "USABLE" && point.soiling_loss_pct !== null) {
      current.push({ index, value: point.soiling_loss_pct });
      return;
    }
    if (current.length > 0) {
      segments.push(current);
      current = [];
    }
  });
  if (current.length > 0) segments.push(current);
  return segments;
}

function chartSummary(history: HistoryPoint[], breakEvenPct: number): string {
  const withheld = history.filter((point) => point.flag !== "USABLE").length;
  return `Daily soiling from ${history[0].date} to ${history[history.length - 1].date} against a break-even of ${formatPct(breakEvenPct)}. ${withheld} of ${history.length} days were withheld from the estimate and are drawn as gaps.`;
}
