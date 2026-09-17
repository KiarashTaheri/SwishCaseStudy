/**
 * Display formatting. One rule throughout: never print more precision than the
 * estimate carries. Money to the dollar, soiling and margin to 2dp, day counts
 * to 1dp.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Dollars, to the dollar. `$25,844`. */
export function formatUsd(value: number): string {
  const rounded = Math.round(value);
  const sign = rounded < 0 ? "-" : "";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

/** A percentage of expected output, 2dp. `5.23%`. */
export function formatPct(value: number): string {
  return `${value.toFixed(2)}%`;
}

/** A margin in percentage points, always signed. `+2.29 pts`. */
export function formatPoints(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(2)} pts`;
}

/** A count of days, 1dp, singular where it reads better. `1.1 days`. */
export function formatDays(value: number): string {
  return `${value.toFixed(1)} days`;
}

/** `2026-09-14` -> `14 Sep 2026`. Locale-independent so SSR and client agree. */
export function formatDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const [year, month, day] = parts;
  const monthIndex = Number(month) - 1;
  const monthName = MONTHS[monthIndex] ?? month;
  return `${Number(day)} ${monthName} ${year}`;
}

/** `2026-09-14` -> `14 Sep`, for dense axis labels. */
export function formatDateShort(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const monthName = MONTHS[Number(parts[1]) - 1] ?? parts[1];
  return `${Number(parts[2])} ${monthName}`;
}

/** Energy in MWh/day, which is the unit an asset manager thinks in. */
export function formatEnergyMwh(kwhPerDay: number): string {
  return `${(kwhPerDay / 1000).toFixed(1)} MWh/day`;
}
