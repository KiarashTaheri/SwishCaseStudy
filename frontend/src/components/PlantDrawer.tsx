"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DispatchPanel } from "@/components/DispatchPanel";
import { HistoryChart } from "@/components/HistoryChart";
import { WorkOrder } from "@/components/WorkOrder";
import { fetchPlant, type DataSource } from "@/lib/api";
import type { DispatchRecord, PlantDetail } from "@/lib/contract";
import { verdictFor } from "@/lib/decision";
import { verdictDetail, verdictTitle } from "@/lib/copy";
import {
  formatDate,
  formatEnergyMwh,
  formatPct,
  formatPoints,
  formatUsd,
} from "@/lib/format";

type DetailState =
  | { phase: "loading" }
  | { phase: "loaded"; detail: PlantDetail; source: DataSource }
  | { phase: "error"; message: string };

interface PlantDrawerProps {
  plantId: string;
  asOf: string;
  onClose: () => void;
  onDispatched: (record: DispatchRecord) => void;
}

/**
 * The plant, opened over the fleet rather than on a second page: the asset
 * manager is comparing plants inside one region, and losing the band she was
 * reading costs her that context.
 */
export function PlantDrawer({ plantId, asOf, onClose, onDispatched }: PlantDrawerProps) {
  const [state, setState] = useState<DetailState>({ phase: "loading" });
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setState({ phase: "loading" });
    fetchPlant(plantId)
      .then((loaded) => {
        if (active) setState({ phase: "loaded", detail: loaded.data, source: loaded.source });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          phase: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => {
      active = false;
    };
  }, [plantId]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close plant detail"
        onClick={onClose}
        className="absolute inset-0 bg-ink/30"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Plant detail for ${plantId}`}
        tabIndex={-1}
        className="relative h-full w-full max-w-[600px] overflow-y-auto border-l border-rule bg-surface"
      >
        {state.phase === "loading" && (
          <p className="p-6 text-[14px] text-ink-soft">Loading {plantId}…</p>
        )}

        {state.phase === "error" && (
          <div className="p-6">
            <h2 className="font-medium">Could not open {plantId}</h2>
            <p className="mt-1 text-[13px] text-ink-soft">{state.message}</p>
            <button
              type="button"
              onClick={onClose}
              className="mt-4 border border-ink px-3 py-1.5 text-[14px]"
            >
              Close
            </button>
          </div>
        )}

        {state.phase === "loaded" && (
          <DetailBody
            detail={state.detail}
            source={state.source}
            asOf={asOf}
            onClose={onClose}
            onDispatched={onDispatched}
          />
        )}
      </div>
    </div>
  );
}

function DetailBody({
  detail,
  source,
  asOf,
  onClose,
  onDispatched,
}: {
  detail: PlantDetail;
  source: DataSource;
  asOf: string;
  onClose: () => void;
  onDispatched: (record: DispatchRecord) => void;
}) {
  const verdict = verdictFor(detail);
  const isRecommended = verdict.kind === "CLEAR";

  return (
    <>
      <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-rule bg-surface px-5 py-4">
        <div className="min-w-0">
          <h2 className="truncate text-[18px] font-medium">{detail.name}</h2>
          <p className="tabular mt-0.5 text-[13px] text-ink-faint">
            {detail.plant_id} · {detail.region} · {detail.capacity_mw.toFixed(1)} MW
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 px-2 py-1 text-[13px] text-ink-soft underline decoration-rule-strong underline-offset-4"
        >
          Close
        </button>
      </header>

      <div className="space-y-6 px-5 py-5">
        <section>
          <p
            className={`tabular text-[28px] leading-none font-medium ${
              isRecommended ? "text-signal" : "text-ink"
            }`}
          >
            {detail.margin_pct === null ? "No estimate" : formatPoints(detail.margin_pct)}
          </p>
          <p className="mt-1 text-[14px] font-medium">{verdictTitle(verdict)}</p>
          <p className="mt-1 max-w-[62ch] text-[14px] text-ink-soft">
            {verdictDetail(verdict, detail)}
          </p>
        </section>

        <section>
          <h3 className="text-[13px] font-medium">What the decision rests on</h3>
          <dl className="tabular mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-[13px]">
            <Figure
              label="Soiling today"
              value={detail.soiling_loss_pct === null ? "—" : formatPct(detail.soiling_loss_pct)}
            />
            <Figure label="Break-even" value={formatPct(detail.break_even_soiling_pct)} />
            <Figure label="Wash cost" value={formatUsd(detail.cleaning_cost_usd)} />
            <Figure
              label="Days to the next rain reset"
              value={`${detail.days_until_next_reset}`}
            />
            <Figure
              label="Expected output"
              value={formatEnergyMwh(detail.expected_energy_kwh_per_day)}
            />
            <Figure label="Tariff" value={`$${detail.tariff_per_kwh.toFixed(3)}/kWh`} />
            <Figure
              label="Accumulation"
              value={
                detail.accumulation_rate_pct_per_day === null
                  ? "—"
                  : `${detail.accumulation_rate_pct_per_day.toFixed(3)} pts/day`
              }
            />
            <Figure
              label="Usable readings behind the estimate"
              value={`${detail.usable_days}`}
            />
            <Figure
              label="Last reset"
              value={detail.last_reset_on ? formatDate(detail.last_reset_on) : "—"}
            />
            <Figure
              label="Days since reset"
              value={detail.days_since_reset === null ? "—" : `${detail.days_since_reset}`}
            />
          </dl>
          <p className="mt-3 max-w-[64ch] text-[13px] text-ink-faint">
            Break-even is the wash cost divided by what the lost output would earn before the next
            rain: {formatUsd(detail.cleaning_cost_usd)} ÷ (
            {formatEnergyMwh(detail.expected_energy_kwh_per_day)} × $
            {detail.tariff_per_kwh.toFixed(3)} × {detail.days_until_next_reset} days).
          </p>
        </section>

        <section>
          <h3 className="text-[13px] font-medium">Data quality</h3>
          <p className="tabular mt-1 text-[13px] text-ink-soft">
            {detail.quality.withheld_days_last_14} of the last 14 days withheld from the estimate.
          </p>
          {detail.quality.note && (
            <p className="mt-2 max-w-[64ch] border-l-2 border-rule-strong pl-3 text-[13px] text-ink">
              {detail.quality.note}
            </p>
          )}
        </section>

        <section>
          <h3 className="text-[13px] font-medium">Soiling since {formatDate(detail.history[0]?.date ?? asOf)}</h3>
          <div className="mt-2">
            <HistoryChart history={detail.history} breakEvenPct={detail.break_even_soiling_pct} />
          </div>
        </section>

        {detail.briefing ? (
          <section>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4">
              <h3 className="text-[13px] font-medium">Briefing</h3>
              <p className="text-[12px] text-ink-faint">
                {detail.briefing.source === "anthropic"
                  ? "written by Claude from the numbers above"
                  : "written by the deterministic template"}
              </p>
            </div>
            <p className="font-doc mt-2 max-w-[68ch] text-[16px] leading-snug">
              {detail.briefing.headline}
            </p>
            <p className="font-doc mt-2 max-w-[68ch] text-[15px] leading-relaxed text-ink-soft">
              {detail.briefing.body}
            </p>
          </section>
        ) : (
          <section>
            <h3 className="text-[13px] font-medium">Briefing</h3>
            <p className="mt-1 max-w-[64ch] text-[13px] text-ink-soft">
              The briefing and work order are generated by the backend. The bundled sample carries
              measurements only, so neither is shown here.
            </p>
          </section>
        )}

        {detail.work_order && <WorkOrder text={detail.work_order} />}

        <DispatchPanel
          plant={detail}
          asOf={asOf}
          source={source}
          onDispatched={onDispatched}
        />
      </div>
    </>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-rule pb-1">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}
