"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useFleet } from "@/components/AppShell";
import { DispatchPanel } from "@/components/DispatchPanel";
import { HistoryChart } from "@/components/HistoryChart";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PaybackChart } from "@/components/PaybackChart";
import { fetchPlant, type DataSource } from "@/lib/api";
import type { PlantDetail } from "@/lib/contract";
import { verdictFor } from "@/lib/decision";
import { verdictDetail, verdictTitle } from "@/lib/copy";
import { formatDate, formatPct, formatPoints, formatUsd } from "@/lib/format";

type State =
  | { phase: "loading" }
  | { phase: "loaded"; detail: PlantDetail; source: DataSource }
  | { phase: "error"; message: string };

/**
 * One plant: the case for cleaning it, the history behind that case, and the
 * button that spends the money.
 *
 * A route rather than the drawer this used to be. The drawer was undiscoverable
 * — nothing about a row said it could be opened — and a URL per plant is also
 * something the asset manager can send to somebody.
 *
 * `useParams()` rather than the `params` prop: in Next 16 that prop is a
 * Promise, and this page is a client component anyway because dispatching needs
 * local state.
 */
export default function PlantPage() {
  const params = useParams<{ id: string }>();
  const plantId = params.id;
  const { reload } = useFleet();
  const [state, setState] = useState<State>({ phase: "loading" });

  const load = useCallback(async () => {
    setState({ phase: "loading" });
    try {
      const loaded = await fetchPlant(plantId);
      setState({ phase: "loaded", detail: loaded.data, source: loaded.source });
    } catch (error) {
      setState({
        phase: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }, [plantId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.phase === "loading") {
    return (
      <>
        <PageHeader title="Loading…" backHref="/" backLabel="Fleet overview" />
      </>
    );
  }

  if (state.phase === "error") {
    return (
      <>
        <PageHeader title={plantId} backHref="/" backLabel="Fleet overview" />
        <main className="px-6 py-6">
          <p className="rounded-lg border border-alert/25 bg-alert-wash px-4 py-3 text-[13.5px]">
            {state.message}
          </p>
        </main>
      </>
    );
  }

  const plant = state.detail;
  const verdict = verdictFor(plant);
  const clear = verdict.kind === "CLEAR";

  return (
    <>
      <PageHeader
        title={plant.name}
        subtitle={`${plant.plant_id} · ${plant.region} · ${plant.capacity_mw} MW`}
        backHref="/"
        backLabel="Fleet overview"
        action={
          <span
            className={`rounded-full px-3 py-1 text-[12.5px] font-medium ${
              clear ? "bg-signal-wash text-signal-strong" : "bg-subtle text-ink-soft"
            }`}
          >
            {clear
              ? `Clean — ${formatPoints(plant.margin_pct ?? 0)} past break-even`
              : plant.status === "NO_USABLE_READING"
                ? "No usable reading today"
                : "Not worth cleaning today"}
          </span>
        }
      />

      <main className="min-w-0 px-6 pb-10">
        {/* The one sentence a person can check against the figures below it,
            and the only place that says WHEN a plant below break-even becomes
            worth cleaning. */}
        <div className="mt-6 rounded-lg border border-rule bg-surface px-4 py-3">
          <p className="text-[13px] font-semibold text-ink-strong">
            {verdictTitle(verdict)}
          </p>
          <p className="mt-0.5 text-[13.5px] text-ink-soft">
            {verdictDetail(verdict, plant)}
          </p>
        </div>

        <SectionLabel>What the decision rests on</SectionLabel>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard
            label="Soiling today"
            value={
              plant.soiling_loss_pct === null
                ? "—"
                : formatPct(plant.soiling_loss_pct)
            }
            unit={`${plant.usable_days} usable reading`}
          />
          <KpiCard
            label="Break-even"
            value={formatPct(plant.break_even_soiling_pct)}
            unit="where a wash repays itself"
          />
          <KpiCard
            label="Recoverable"
            value={
              plant.recoverable_usd === null
                ? "—"
                : formatUsd(plant.recoverable_usd)
            }
            unit={`over ${plant.days_until_next_reset} days to the next rain`}
            emphasis={clear}
          />
          <KpiCard
            label="Wash cost"
            value={formatUsd(plant.cleaning_cost_usd)}
            unit={
              plant.suggested_crew
                ? `${plant.suggested_crew.crew_id} · ${plant.suggested_crew.crew_days.toFixed(1)} crew-days`
                : "no crew in this region"
            }
          />
        </div>

        <p className="tabular mt-3 rounded-lg border border-rule bg-subtle px-4 py-2.5 text-[12.5px] text-ink-soft">
          Break-even is the wash cost divided by what the lost output would earn
          before the next rain: {formatUsd(plant.cleaning_cost_usd)} ÷ (
          {(plant.expected_energy_kwh_per_day / 1000).toFixed(1)} MWh/day × $
          {plant.tariff_per_kwh}/kWh × {plant.days_until_next_reset} days).
        </p>

        <SectionLabel>Soiling trend &amp; cleaning schedule</SectionLabel>
        <div className="rounded-lg border border-rule bg-surface p-4">
          <HistoryChart
            history={plant.history}
            breakEvenPct={plant.break_even_soiling_pct}
          />
        </div>

        {/* The chart above answers "is it dirty enough". This one answers the
            question the asset manager is actually signing off on: what the
            money does between today and the next rain. */}
        <SectionLabel>What the wash costs, and what it returns</SectionLabel>
        <div className="rounded-lg border border-rule bg-surface p-4">
          <PaybackChart plant={plant} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div>
            <SectionLabel>
              Briefing
              <span className="ml-2 font-normal text-ink-faint">
                {plant.briefing
                  ? plant.briefing.source === "anthropic"
                    ? "written by Claude from the computed figures"
                    : "written by the deterministic template"
                  : ""}
              </span>
            </SectionLabel>
            <div className="rounded-lg border border-rule bg-surface p-4">
              {plant.briefing ? (
                <>
                  <p className="font-doc text-[16px] leading-relaxed text-ink-strong">
                    {plant.briefing.headline}
                  </p>
                  <p className="font-doc mt-2 text-[15px] leading-relaxed">
                    {plant.briefing.body}
                  </p>
                </>
              ) : (
                <p className="text-[13.5px] text-ink-soft">
                  The briefing is generated by the backend. The bundled sample
                  carries measurements only, so none is shown here.
                </p>
              )}
            </div>

            <SectionLabel>Data quality</SectionLabel>
            <div className="rounded-lg border border-rule bg-surface px-4 py-3 text-[13.5px]">
              {plant.quality.note ? (
                <p>{plant.quality.note}</p>
              ) : (
                <p className="text-ink-soft">
                  None of the last 14 readings were withheld.
                </p>
              )}
            </div>
          </div>

          <div>
            <SectionLabel>Dispatch</SectionLabel>
            <DispatchPanel
              plant={plant}
              asOf={plant.history.at(-1)?.date ?? ""}
              source={state.source}
              onDispatched={() => {
                void load();
                void reload();
              }}
            />
          </div>
        </div>

        <p className="mt-6 text-[12.5px] text-ink-faint">
          Last reset {plant.last_reset_on ? formatDate(plant.last_reset_on) : "—"}
          {plant.days_since_reset !== null
            ? ` · ${plant.days_since_reset} days ago`
            : ""}
          . Losing{" "}
          {plant.accumulation_rate_pct_per_day === null
            ? "an unmeasured amount"
            : `another ${plant.accumulation_rate_pct_per_day.toFixed(2)}% of its output`}{" "}
          each day it stays dirty. That rate is not used to value a cleaning — it
          cancels out of the gain — only to say how soon a plant becomes worth
          cleaning.
        </p>
      </main>
    </>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="pb-2.5 pt-6 text-[13px] font-semibold text-ink-strong">
      {children}
    </h2>
  );
}
