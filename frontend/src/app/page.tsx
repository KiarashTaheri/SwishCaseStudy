"use client";

import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";
import { KpiCard } from "@/components/KpiCard";
import { useFleet } from "@/components/AppShell";
import type { PlantRow, RegionBlock } from "@/lib/contract";
import { verdictFor } from "@/lib/decision";
import { formatDate, formatPct, formatPoints, formatUsd } from "@/lib/format";

/**
 * Fleet overview: the answer to "where does the truck go tomorrow".
 *
 * A table rather than the card stack this screen used to be. The asset manager
 * is comparing twelve plants on four numbers, and comparison down a column is
 * what a table is for — the previous layout restated the same margin four ways
 * per row and buried the five plants that mattered under two regions with
 * nothing to do.
 *
 * Regions are ordered by work outstanding, not alphabetically. Alphabetical put
 * Andalusia — which has nothing to clean — at the top of the screen.
 */
export default function FleetPage() {
  const { fleet } = useFleet();

  if (!fleet) {
    return (
      <>
        <PageHeader title="Fleet overview" />
        <main className="px-6 py-6">
          <p className="text-[14px] text-ink-soft">Loading the fleet…</p>
        </main>
      </>
    );
  }

  const regions = [...fleet.regions].sort(
    (a, b) => crewDays(b) - crewDays(a) || a.region.localeCompare(b.region),
  );
  // The longest queue, not an "over capacity" verdict. Every region takes more
  // than a day; only the slowest is worth naming on the summary row.
  const bottleneck = regions.find((r) => crewDays(r) > 0) ?? null;
  const bottleneckDays = bottleneck
    ? crewDays(bottleneck) / Math.max(capacityDays(bottleneck), 1)
    : 0;

  return (
    <>
      <PageHeader
        title="Fleet overview"
        subtitle={`As of ${formatDate(fleet.as_of)} — the latest day in the data, not today's date`}
      />

      <main className="min-w-0 px-6 pb-10">
        <SectionLabel>Today&rsquo;s decision</SectionLabel>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard
            label="Worth cleaning"
            value={String(fleet.summary.actionable)}
            unit={`of ${fleet.summary.plants_total} plants`}
            emphasis={fleet.summary.actionable > 0}
          />
          <KpiCard
            label="Recoverable"
            value={formatUsd(fleet.summary.total_recoverable_usd)}
            unit="before the next rain"
            emphasis={fleet.summary.total_recoverable_usd > 0}
          />
          <KpiCard
            label="Crew time needed"
            value={regions.reduce((t, r) => t + crewDays(r), 0).toFixed(1)}
            unit="crew-days across 5 regions"
          />
          <KpiCard
            label="Longest queue"
            value={bottleneck ? bottleneck.region.split(",")[0] : "None"}
            unit={
              bottleneck
                ? `${bottleneckDays.toFixed(1)} days for ${bottleneck.crews.length} crew to clear`
                : "nothing to clean anywhere"
            }
          />
        </div>

        <SectionLabel>Plants overview</SectionLabel>
        <div className="overflow-hidden rounded-lg border border-rule bg-surface">
          <table className="w-full text-[13.5px]">
            <thead>
              <tr className="border-b border-rule bg-subtle text-left text-[11.5px] uppercase tracking-[0.06em] text-ink-soft">
                <th className="px-4 py-2.5 font-semibold">Plant</th>
                <th className="px-4 py-2.5 text-right font-semibold">Soiling</th>
                <th className="px-4 py-2.5 text-right font-semibold">Break-even</th>
                <th className="px-4 py-2.5 text-right font-semibold">Margin</th>
                <th className="px-4 py-2.5 text-right font-semibold">Recoverable</th>
                <th className="px-4 py-2.5 font-semibold">Crew</th>
                <th className="px-4 py-2.5 font-semibold">Verdict</th>
                <th className="w-8 px-4 py-2.5" />
              </tr>
            </thead>
            {regions.map((region, regionIndex) => (
              <tbody key={region.region} className="group/region">
                {/* A group header, not a row. Tinted, uppercase and letterspaced
                    so it reads as a different tier from the plants under it —
                    previously both were near-white with near-identical weight
                    and the two blended together. */}
                <tr
                  className={`bg-canvas ${
                    regionIndex > 0 ? "border-t-4 border-t-rule" : ""
                  }`}
                >
                  <td colSpan={8} className="border-b border-rule px-4 py-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
                      <span className="flex items-center gap-2.5">
                        <span
                          aria-hidden
                          className="h-3.5 w-1 rounded-full bg-ink-faint"
                        />
                        <span className="text-[12px] font-semibold uppercase tracking-[0.09em] text-ink-strong">
                          {region.region}
                        </span>
                        <span className="rounded-full bg-surface px-2 py-0.5 text-[11.5px] text-ink-soft">
                          {region.recommendations.length > 0
                            ? `${region.recommendations.length} to clean`
                            : "nothing to clean"}
                        </span>
                      </span>
                      <CapacityMeter region={region} />
                    </div>
                  </td>
                </tr>
                {[...region.recommendations, ...region.withheld].map((plant) => (
                  <PlantTableRow key={plant.plant_id} plant={plant} />
                ))}
              </tbody>
            ))}
          </table>
        </div>

        <p className="mt-3 text-[12.5px] text-ink-faint">
          Plants are ranked inside a region and never against another, because a crew
          works its home region only. Withheld readings are excluded from every figure
          and reported with their signature — this screen never names a cause.
        </p>
      </main>
    </>
  );
}

function PlantTableRow({ plant }: { plant: PlantRow }) {
  // Orange means "the numbers say clean it", which is ACTIONABLE — both a
  // confident call and a marginal one. The pill is where the two are
  // distinguished, so a thin call is never styled as a confident one.
  const actionable = plant.status === "ACTIONABLE";
  const clear = actionable;

  return (
    <tr className="group border-b border-rule/60 bg-surface transition-colors last:border-b-0 hover:bg-subtle">
      <td className="px-4 py-2.5">
        <Link
          href={`/plants/${plant.plant_id}`}
          className="text-[14.5px] font-semibold text-ink-strong underline-offset-2 hover:text-signal hover:underline"
        >
          {plant.name}
        </Link>
        <span className="block text-[11.5px] text-ink-faint">
          {plant.plant_id} · {plant.capacity_mw} MW
        </span>
      </td>
      <td className="tabular px-4 py-2.5 text-right">
        {plant.soiling_loss_pct === null ? "—" : formatPct(plant.soiling_loss_pct)}
      </td>
      <td className="tabular px-4 py-2.5 text-right text-ink-soft">
        {formatPct(plant.break_even_soiling_pct)}
      </td>
      <td
        className={`tabular px-4 py-2.5 text-right font-medium ${
          clear ? "text-signal" : "text-ink-soft"
        }`}
      >
        {plant.margin_pct === null ? "—" : formatPoints(plant.margin_pct)}
      </td>
      <td
        className={`tabular px-4 py-2.5 text-right ${
          clear ? "font-medium text-ink-strong" : "text-ink-faint"
        }`}
      >
        {plant.recoverable_usd === null || plant.recoverable_usd <= 0
          ? "—"
          : formatUsd(plant.recoverable_usd)}
      </td>
      <td className="tabular px-4 py-2.5 text-[12.5px] text-ink-soft">
        {plant.suggested_crew
          ? `${plant.suggested_crew.crew_id} · ${plant.suggested_crew.crew_days.toFixed(1)}d`
          : "—"}
      </td>
      <td className="px-4 py-2.5">
        <VerdictPill plant={plant} />
      </td>
      <td className="px-4 py-2.5 text-right">
        {/* Spelled out, not a bare chevron. The previous build hid the detail
            view behind a row that gave no sign it could be opened. */}
        <Link
          href={`/plants/${plant.plant_id}`}
          className="whitespace-nowrap text-[13px] text-ink-faint transition-colors group-hover:text-signal"
        >
          View <span aria-hidden>›</span>
        </Link>
      </td>
    </tr>
  );
}

function VerdictPill({ plant }: { plant: PlantRow }) {
  const verdict = verdictFor(plant);
  if (plant.dispatched) {
    return <Pill className="bg-shell text-white">Dispatched</Pill>;
  }
  switch (verdict.kind) {
    case "CLEAR":
      return <Pill className="bg-signal-wash text-signal-strong">Clean</Pill>;
    case "MARGINAL":
      // Past break-even by less than a day of dust. Styled apart from a
      // confident call on purpose: plant_1005 clears by $1,692 on a 0.18pp
      // margin, which is inside the noise of a single reading.
      return (
        <Pill className="border border-signal/30 bg-signal-wash/50 text-signal-strong">
          Clean · thin
        </Pill>
      );
    case "APPROACHING":
      return <Pill className="bg-subtle text-ink-soft">Soon</Pill>;
    case "BELOW":
      return <Pill className="bg-subtle text-ink-soft">Hold</Pill>;
    default:
      return <Pill className="bg-subtle text-ink-faint">No reading</Pill>;
  }
}

function Pill({
  children,
  className,
}: {
  children: React.ReactNode;
  className: string;
}) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium ${className}`}
    >
      {children}
    </span>
  );
}

/**
 * How long this region's queue takes, against the rain horizon it is racing.
 *
 * The first version of this compared crew-days to one crew-day per crew per
 * day, which marked every region "over capacity" — including Atacama at 2.9
 * days — because a queue almost never clears in a single day. A warning that
 * fires everywhere carries no information.
 *
 * The comparison that means something is the rain horizon. `days_until_next_reset`
 * is how long these plants stay dirty before rain washes them anyway, so a queue
 * longer than that is work the crew can never get ahead of: by the time they
 * reach the last plant, the first is already clean and the spend was wasted.
 */
function CapacityMeter({ region }: { region: RegionBlock }) {
  const work = crewDays(region);
  if (work === 0) {
    return (
      <span className="text-[12px] text-ink-faint">
        {region.crews.length} crew · nothing to clean
      </span>
    );
  }

  const days = work / Math.max(capacityDays(region), 1);
  const horizon = rainHorizon(region);
  const outpaced = horizon !== null && days > horizon;
  const filled = horizon === null ? 1 : Math.min(1, days / horizon);

  return (
    <span className="flex items-center gap-2 text-[12px] text-ink-soft">
      <span className="tabular">
        {work.toFixed(1)} crew-days · {region.crews.length} crew ·{" "}
        {days.toFixed(1)} days to clear
      </span>
      <span
        className="h-1.5 w-20 overflow-hidden rounded-full bg-rule"
        title={
          horizon === null
            ? undefined
            : `${days.toFixed(1)} of the ${horizon} days before rain resets these plants`
        }
      >
        <span
          className={`block h-full ${outpaced ? "bg-alert" : "bg-signal"}`}
          style={{ width: `${filled * 100}%` }}
        />
      </span>
      {horizon !== null && (
        <span className={outpaced ? "font-medium text-alert" : "text-ink-faint"}>
          {outpaced
            ? `rain resets in ${horizon} — cannot keep up`
            : `of ${horizon} days to rain`}
        </span>
      )}
    </span>
  );
}

function crewDays(region: RegionBlock): number {
  return region.recommendations.reduce(
    (total, plant) => total + (plant.suggested_crew?.crew_days ?? 0),
    0,
  );
}

/** Crews working in parallel: how much of the queue clears per day. */
function capacityDays(region: RegionBlock): number {
  return region.crews.length;
}

/**
 * The shortest rain horizon among the plants waiting — the binding one, since
 * that plant is the first to be washed out from under the crew.
 */
function rainHorizon(region: RegionBlock): number | null {
  const horizons = region.recommendations.map((p) => p.days_until_next_reset);
  return horizons.length > 0 ? Math.min(...horizons) : null;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="pb-2.5 pt-6 text-[13px] font-semibold text-ink-strong">
      {children}
    </h2>
  );
}
