import type { PlantRow } from "@/lib/contract";
import { formatUsd } from "@/lib/format";

/*
 * The money the asset manager is actually approving: what a wash today costs
 * against what it returns before the next rain.
 *
 * Forward-looking only, and deliberately so. The obvious alternative chart is
 * "what dirt has already cost you since the last reset", which is a bigger,
 * more dramatic number — and it is sunk. It cannot be recovered by any decision
 * available today, and putting it in front of someone approving a spend invites
 * exactly the wrong reasoning ("we've lost so much, we have to clean"). The only
 * dollars on this chart are dollars still in play.
 *
 * The recovery line is straight because the rate of accumulation cancels out of
 * the gain: cleaning recovers the constant GAP between the cleaned and uncleaned
 * trajectories, and both accumulate at the same rate. See DECISIONS.md #1 and
 * the derivation in `economics.py`.
 */

const VIEW_WIDTH = 1100;
const VIEW_HEIGHT = 260;
const PADDING = { left: 62, right: 108, top: 18, bottom: 40 };
const PLOT_WIDTH = VIEW_WIDTH - PADDING.left - PADDING.right;
const PLOT_HEIGHT = VIEW_HEIGHT - PADDING.top - PADDING.bottom;

interface PaybackChartProps {
  plant: PlantRow;
}

export function PaybackChart({ plant }: PaybackChartProps) {
  const horizon = plant.days_until_next_reset;
  const cost = plant.cleaning_cost_usd;

  if (plant.recoverable_usd === null || horizon <= 0) {
    return (
      <p className="text-[13px] text-ink-soft">
        No soiling estimate for this plant today, so there is no value to project.
        The wash would cost {formatUsd(cost)}.
      </p>
    );
  }

  /*
   * Derived from the backend's own `recoverable_usd` rather than recomputed from
   * s0/E/tau/T. Both routes give the same number, but only this one cannot drift
   * from the figure on the KPI card above if the estimator changes.
   */
  const grossAtHorizon = plant.recoverable_usd + cost;
  const perDay = grossAtHorizon / horizon;
  const paybackDay = perDay > 0 ? cost / perDay : null;
  const paysBack = paybackDay !== null && paybackDay <= horizon;

  const axisMax = Math.max(grossAtHorizon, cost) * 1.18;
  const x = (day: number) => PADDING.left + (day / horizon) * PLOT_WIDTH;
  const y = (usd: number) => PADDING.top + PLOT_HEIGHT - (usd / axisMax) * PLOT_HEIGHT;

  const costY = y(cost);
  const endY = y(grossAtHorizon);

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={summary(plant, grossAtHorizon, paybackDay, paysBack)}
      >
        {/* Profit: the wedge between what the wash returns and what it cost,
            drawn only past the day it stops being a loss. */}
        {paysBack && (
          <polygon
            points={[
              `${x(paybackDay)},${costY}`,
              `${x(horizon)},${endY}`,
              `${x(horizon)},${costY}`,
            ].join(" ")}
            fill="var(--color-signal-wash)"
          />
        )}

        <line
          x1={PADDING.left}
          y1={PADDING.top + PLOT_HEIGHT}
          x2={PADDING.left + PLOT_WIDTH}
          y2={PADDING.top + PLOT_HEIGHT}
          stroke="var(--color-rule)"
        />

        {/* What the wash costs. Flat: it is paid once, on day zero. */}
        <line
          x1={PADDING.left}
          y1={costY}
          x2={PADDING.left + PLOT_WIDTH}
          y2={costY}
          stroke="var(--color-signal)"
          strokeWidth="2"
          strokeDasharray="7 5"
        />
        <text
          x={PADDING.left + PLOT_WIDTH + 8}
          y={costY + 4}
          className="fill-signal text-[12px] font-semibold"
        >
          {formatUsd(cost)} wash
        </text>

        {/* What it returns, accumulating to the next rain. */}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(horizon)}
          y2={endY}
          stroke="var(--color-ink)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle cx={x(horizon)} cy={endY} r="4" fill="var(--color-ink)" />
        <text
          x={PADDING.left + PLOT_WIDTH + 8}
          y={endY + 4}
          className="fill-ink-strong text-[12px] font-semibold"
        >
          {formatUsd(grossAtHorizon)}
        </text>

        {paysBack && (
          <>
            <line
              x1={x(paybackDay)}
              y1={costY}
              x2={x(paybackDay)}
              y2={PADDING.top + PLOT_HEIGHT}
              stroke="var(--color-signal)"
              strokeWidth="1.5"
            />
            <circle cx={x(paybackDay)} cy={costY} r="4" fill="var(--color-signal)" />
            <text
              x={x(paybackDay) + 7}
              y={PADDING.top + 14}
              className="fill-signal text-[12px] font-semibold"
            >
              pays for itself on day {Math.ceil(paybackDay)}
            </text>
          </>
        )}

        <text x="0" y={PADDING.top + 10} className="fill-ink-faint text-[11px]">
          {formatUsd(axisMax)}
        </text>
        <text x="0" y={PADDING.top + PLOT_HEIGHT} className="fill-ink-faint text-[11px]">
          $0
        </text>
        <text
          x={PADDING.left}
          y={VIEW_HEIGHT - 12}
          className="fill-ink-faint text-[11px]"
        >
          today
        </text>
        <text
          x={PADDING.left + PLOT_WIDTH}
          y={VIEW_HEIGHT - 12}
          textAnchor="end"
          className="fill-ink-faint text-[11px]"
        >
          next rain expected · day {horizon}
        </text>
      </svg>

      <figcaption className="tabular mt-1 text-[12.5px] text-ink-soft">
        {paysBack ? (
          <>
            The wash returns {formatUsd(perDay)}/day. It clears its own{" "}
            {formatUsd(cost)} on day {Math.ceil(paybackDay)} and is{" "}
            <strong className="font-semibold text-ink-strong">
              {formatUsd(plant.recoverable_usd)} ahead
            </strong>{" "}
            by the next rain.
          </>
        ) : (
          <>
            The wash returns {formatUsd(perDay)}/day, reaching{" "}
            {formatUsd(grossAtHorizon)} by the next rain — {formatUsd(-plant.recoverable_usd)}{" "}
            short of the {formatUsd(cost)} it costs. Rain is expected before it
            can repay itself.
          </>
        )}
      </figcaption>
    </figure>
  );
}

function summary(
  plant: PlantRow,
  gross: number,
  paybackDay: number | null,
  paysBack: boolean,
): string {
  const base = `Cleaning ${plant.name} costs ${formatUsd(plant.cleaning_cost_usd)} and returns ${formatUsd(gross)} over the ${plant.days_until_next_reset} days to the next rain.`;
  return paysBack && paybackDay !== null
    ? `${base} It repays itself on day ${Math.ceil(paybackDay)}, ending ${formatUsd(plant.recoverable_usd ?? 0)} ahead.`
    : `${base} It does not repay itself before the rain resets the plant.`;
}
