import type { PlantRow } from "@/lib/contract";
import type { Verdict } from "@/lib/decision";
import { formatDate, formatDays, formatUsd } from "@/lib/format";

/**
 * The words attached to each verdict, in one place so the table, the detail
 * page and the confirmation cannot describe the same plant differently.
 */

/** Two or three words, sitting above the margin figure. */
export function verdictTitle(verdict: Verdict): string {
  switch (verdict.kind) {
    case "CLEAR":
      return "Past break-even";
    case "MARGINAL":
      return "Too close to call";
    case "APPROACHING":
      return "Coming up";
    case "BELOW":
      return "Below break-even";
    case "NO_ESTIMATE":
      return "No estimate";
  }
}

/** One sentence a person can check against the numbers beside it. */
export function verdictDetail(verdict: Verdict, plant: PlantRow): string {
  switch (verdict.kind) {
    case "CLEAR": {
      const dollars =
        plant.recoverable_usd === null
          ? null
          : `${formatUsd(plant.recoverable_usd)} recoverable before the next rain`;
      const dust =
        verdict.daysPastBreakEven === null
          ? null
          : `${formatDays(verdict.daysPastBreakEven)} of dust past break-even`;
      return [dust, dollars].filter(Boolean).join(" · ");
    }
    case "MARGINAL": {
      const dollars =
        plant.recoverable_usd === null ? "" : ` Worth ${formatUsd(plant.recoverable_usd)}.`;
      return `Under a day of dust separates this from break-even, which is inside the noise on the estimate.${dollars}`;
    }
    case "APPROACHING":
      return `Worth cleaning in ${formatDays(verdict.daysToBreakEven)} if it keeps getting dirtier at this rate.`;
    case "BELOW":
      return verdict.daysToBreakEven === null
        ? "Not worth cleaning before the next rain."
        : `Worth cleaning in ${formatDays(verdict.daysToBreakEven)} if it keeps getting dirtier at this rate.`;
    case "NO_ESTIMATE":
      return insufficientHistoryReason(plant, verdict.usableDays);
  }
}

function insufficientHistoryReason(plant: PlantRow, usableDays: number): string {
  // Not "three days are needed" — that described the 3-day median the estimator
  // used to run and no longer does. Today's reading is the estimate, so the only
  // way to have none is for today's reading to be blank or withheld.
  const since = plant.last_reset_on
    ? `, last cleaned or rained on ${formatDate(plant.last_reset_on)}`
    : "";
  return usableDays === 0
    ? `Today's reading was withheld or has no clean baseline to compare against${since}, so there is no soiling figure to act on.`
    : `Standing on ${usableDays} usable reading${since}.`;
}
