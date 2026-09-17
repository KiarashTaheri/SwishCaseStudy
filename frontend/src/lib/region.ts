/**
 * Region-level facts, derived from the plant rows already on screen so that
 * every sentence in a band header can be checked against the table under it.
 */

import type { PlantRow, RegionBlock } from "./contract";
import { allPlants } from "./decision";

function range(values: number[]): { low: number; high: number } | null {
  if (values.length === 0) return null;
  return {
    low: values.reduce((a, b) => Math.min(a, b)),
    high: values.reduce((a, b) => Math.max(a, b)),
  };
}

function formatRange(
  span: { low: number; high: number } | null,
  render: (value: number) => string,
  join: string,
): string | null {
  if (!span) return null;
  return span.low === span.high
    ? render(span.low)
    : `${render(span.low)}${join}${render(span.high)}`;
}

/** "about every 7 days", or a span when the plants disagree. */
export function resetHorizonPhrase(plants: PlantRow[]): string | null {
  const span = range(plants.map((plant) => plant.days_until_next_reset));
  const text = formatRange(span, (value) => `${value}`, " to ");
  if (!text) return null;
  return span && span.low === span.high ? `about every ${text} days` : `every ${text} days`;
}

/** "14.08%", or "13.76-14.08%" across the region. */
export function breakEvenPhrase(plants: PlantRow[]): string | null {
  const span = range(plants.map((plant) => plant.break_even_soiling_pct));
  return formatRange(span, (value) => `${value.toFixed(2)}%`, "–");
}

/**
 * One sentence tying a region's rain horizon to the break-even it produces.
 * This is what keeps Queensland legible: nothing there is worth cleaning
 * because rain arrives before a wash can repay itself, which is a fact about
 * the region rather than a broken row.
 */
export function regionHorizonNote(region: RegionBlock): string | null {
  const plants = allPlants(region);
  const horizon = resetHorizonPhrase(plants);
  const breakEven = breakEvenPhrase(plants);
  if (!horizon || !breakEven) return null;
  return `Rain resets these plants ${horizon}, so a wash has to repay itself inside that window. Break-even ${breakEven} of expected output.`;
}

/** Crew days available per day, against the plant a crew would be sent to. */
export function crewCapacityNote(region: RegionBlock): string {
  const crewCount = region.crews.length;
  const noun = crewCount === 1 ? "crew" : "crews";
  return `${crewCount} ${noun} · ${region.capacity_mw_per_day.toFixed(1)} MW/day`;
}
