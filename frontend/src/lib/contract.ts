/**
 * Types for the frozen API contract in `docs/api-contract.md`.
 *
 * Field names mirror the contract exactly. Nothing is renamed for convenience:
 * a second vocabulary in the UI layer is a second thing to keep in sync.
 */

/** Why a reading was kept out of the soiling estimate. Never a cause. */
export type QualityFlag =
  | "USABLE"
  | "AVAILABILITY_ANOMALY"
  | "MISSING_SOILING_BASELINE"
  | "MISSING_PERFORMANCE_RATIO"
  | "NEGATIVE_SOILING";

export type PlantStatus = "ACTIONABLE" | "BELOW_BREAK_EVEN" | "INSUFFICIENT_HISTORY";

export interface Crew {
  crew_id: string;
  home_base: string;
  mw_per_day: number;
  day_rate_usd: number;
}

export interface SuggestedCrew {
  crew_id: string;
  home_base: string;
  crew_days: number;
}

export interface PlantQuality {
  withheld_days_last_14: number;
  /** Evidence, never a diagnosis. Rendered verbatim. */
  note: string | null;
}

export interface PlantRow {
  plant_id: string;
  name: string;
  region: string;
  capacity_mw: number;
  status: PlantStatus;
  /** s0. Null when the quality gate left too little to estimate from. */
  soiling_loss_pct: number | null;
  /** s* = C / (E * tau * T), in percent. Always present. */
  break_even_soiling_pct: number;
  /** s0 - s*, in percentage points. Null when s0 is null. */
  margin_pct: number | null;
  recoverable_usd: number | null;
  cleaning_cost_usd: number;
  expected_energy_kwh_per_day: number;
  tariff_per_kwh: number;
  /** T. A fixed horizon, never decremented. */
  days_until_next_reset: number;
  /** r, percentage points per day. */
  accumulation_rate_pct_per_day: number | null;
  /** (s* - s0) / r. Null when above break-even or unknown. */
  days_to_break_even: number | null;
  days_since_reset: number | null;
  last_reset_on: string | null;
  /** Readings behind s0. Fewer than three means no estimate. */
  usable_days: number;
  quality: PlantQuality;
  suggested_crew: SuggestedCrew | null;
  dispatched: boolean;
}

export interface RegionBlock {
  region: string;
  crews: Crew[];
  capacity_mw_per_day: number;
  /** Ranked by recoverable_usd desc. Competes only within this region. */
  recommendations: PlantRow[];
  withheld: PlantRow[];
}

export interface FleetSummary {
  plants_total: number;
  actionable: number;
  withheld: number;
  total_recoverable_usd: number;
}

export interface FleetSnapshot {
  /** Latest date in the data, not wall-clock time. */
  as_of: string;
  summary: FleetSummary;
  regions: RegionBlock[];
}

export interface HistoryPoint {
  date: string;
  soiling_loss_pct: number | null;
  pr: number | null;
  flag: QualityFlag;
  rain_mm: number | null;
  cleaned: boolean;
}

export interface Briefing {
  headline: string;
  body: string;
  source: "anthropic" | "template";
}

export interface PlantDetail extends PlantRow {
  history: HistoryPoint[];
  briefing: Briefing | null;
  work_order: string | null;
}

export interface DispatchSnapshot {
  soiling_loss_pct: number | null;
  break_even_soiling_pct: number;
  margin_pct: number | null;
  recoverable_usd: number | null;
  cleaning_cost_usd: number;
  expected_energy_kwh_per_day: number;
  tariff_per_kwh: number;
  days_until_next_reset: number;
  usable_days: number;
  last_reset_on: string | null;
}

export interface DispatchRecord {
  dispatch_id: string;
  plant_id: string;
  as_of: string;
  created_at: string;
  crew_id: string | null;
  crew_days: number | null;
  snapshot: DispatchSnapshot;
  work_order: string;
}

export interface DispatchRequest {
  plant_id: string;
  as_of: string;
  crew_id?: string;
}
