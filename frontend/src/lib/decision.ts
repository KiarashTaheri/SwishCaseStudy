/**
 * Turns a PlantRow into the one thing the asset manager has to decide about it.
 *
 * The contract carries no uncertainty on `soiling_loss_pct`, so confidence has
 * to be expressed in a unit that is on the page anyway. This module measures
 * the distance to break-even in days of accumulated dust: `|margin_pct| / r`.
 * Its two virtues are that it self-calibrates per plant (a dusty Atacama site
 * and a slow Queensland one are judged on their own accumulation rate rather
 * than a fleet-wide dollar threshold) and that it is checkable by hand from two
 * printed numbers. For plants below break-even it reproduces the contract's own
 * `days_to_break_even`, so the two never disagree.
 */

import type { PlantRow } from "./contract";

/**
 * Less than one day of dust either side of break-even is inside the noise: a
 * single reading joining or leaving the 14-day median moves the estimate
 * further than this. Such a plant is reported as too close to call, never as a
 * recommendation.
 */
export const MARGINAL_DAYS_OF_DUST = 1;

/**
 * A crossing this far out is worth knowing about when planning tomorrow's
 * route, because the crew is being scheduled today. Beyond it, the plant is
 * simply not this week's problem.
 */
export const APPROACHING_DAYS = 3;

export type Verdict =
  | { kind: "CLEAR"; daysPastBreakEven: number | null }
  | { kind: "MARGINAL"; daysPastBreakEven: number }
  | { kind: "APPROACHING"; daysToBreakEven: number }
  | { kind: "BELOW"; daysToBreakEven: number | null }
  | { kind: "NO_ESTIMATE"; usableDays: number };

/**
 * Days of accumulation between today's estimate and break-even, or null when
 * the accumulation rate is unknown or flat (dividing by it would invent a
 * number).
 */
export function daysOfDustFromBreakEven(plant: PlantRow): number | null {
  const { margin_pct: margin, accumulation_rate_pct_per_day: rate } = plant;
  if (margin === null || rate === null || rate <= 0) return null;
  return Math.abs(margin) / rate;
}

export function verdictFor(plant: PlantRow): Verdict {
  if (plant.status === "INSUFFICIENT_HISTORY" || plant.margin_pct === null) {
    return { kind: "NO_ESTIMATE", usableDays: plant.usable_days };
  }

  const daysOfDust = daysOfDustFromBreakEven(plant);

  if (plant.status === "ACTIONABLE") {
    if (daysOfDust !== null && daysOfDust < MARGINAL_DAYS_OF_DUST) {
      return { kind: "MARGINAL", daysPastBreakEven: daysOfDust };
    }
    return { kind: "CLEAR", daysPastBreakEven: daysOfDust };
  }

  const daysToBreakEven = plant.days_to_break_even ?? daysOfDust;
  if (daysToBreakEven !== null && daysToBreakEven <= APPROACHING_DAYS) {
    return { kind: "APPROACHING", daysToBreakEven };
  }
  return { kind: "BELOW", daysToBreakEven };
}

/** True where the numbers support committing a truck today. */
export function isConfidentRecommendation(verdict: Verdict): boolean {
  return verdict.kind === "CLEAR";
}

/**
 * The upper bound of a region's soiling axis. Every bar in a band is drawn to
 * the same scale so plants can be compared within the region — and only within
 * it, because a crew cannot cross one.
 */
export function regionAxisMax(plants: PlantRow[]): number {
  const values = plants.flatMap((plant) => [
    plant.soiling_loss_pct ?? 0,
    plant.break_even_soiling_pct,
  ]);
  const max = values.reduce((highest, value) => Math.max(highest, value), 0);
  // Headroom so a bar that sits at the maximum still reads as a bar.
  return max > 0 ? max * 1.15 : 1;
}

/** Every plant in a region, recommendations first. */
export function allPlants(region: {
  recommendations: PlantRow[];
  withheld: PlantRow[];
}): PlantRow[] {
  return [...region.recommendations, ...region.withheld];
}
