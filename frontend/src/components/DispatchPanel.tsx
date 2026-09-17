"use client";

import { useState } from "react";
import { DispatchError, postDispatch, type DataSource } from "@/lib/api";
import type { DispatchRecord, PlantDetail } from "@/lib/contract";
import { verdictFor } from "@/lib/decision";
import { formatDate, formatDays, formatEnergyMwh, formatPct, formatUsd } from "@/lib/format";
import { WorkOrder } from "@/components/WorkOrder";

type DispatchPhase =
  | { phase: "idle" }
  | { phase: "confirming" }
  | { phase: "sending" }
  | { phase: "sent"; record: DispatchRecord }
  | { phase: "failed"; status: number | null; message: string };

interface DispatchPanelProps {
  plant: PlantDetail;
  asOf: string;
  /** Where the plant on screen came from. The sample cannot be dispatched. */
  source: DataSource;
  onDispatched: (record: DispatchRecord) => void;
}

/**
 * The spend. A dispatch books a truck for roughly what it expects to recover,
 * so the confirmation restates every number the decision rests on — including
 * how few days the estimate is built from — before anything is sent.
 */
export function DispatchPanel({ plant, asOf, source, onDispatched }: DispatchPanelProps) {
  const [state, setState] = useState<DispatchPhase>({ phase: "idle" });
  const verdict = verdictFor(plant);
  const crew = plant.suggested_crew;

  if (state.phase === "sent") {
    return (
      <section className="border border-ink bg-surface p-4">
        <h3 className="font-medium">Crew dispatched</h3>
        <p className="tabular mt-1 text-[13px] text-ink-soft">
          {state.record.dispatch_id} · {state.record.crew_id ?? "crew unassigned"} ·{" "}
          {formatDate(state.record.as_of)}
        </p>
        <div className="mt-3">
          <WorkOrder text={state.record.work_order} />
        </div>
      </section>
    );
  }

  if (plant.dispatched) {
    return (
      <Notice title="Already dispatched">
        A crew is booked for this plant for {formatDate(asOf)}. The work order is above.
      </Notice>
    );
  }

  if (plant.status !== "ACTIONABLE") {
    return (
      <Notice title="Not dispatchable today">
        {plant.status === "INSUFFICIENT_HISTORY"
          ? "There is no soiling estimate to spend against yet."
          : "Soiling has not reached the point where a wash repays itself before the next rain."}
      </Notice>
    );
  }

  if (source === "fixture") {
    return (
      <Notice title="Dispatch needs the API">
        This screen is showing the bundled sample, so there is nothing to write to. Start the
        backend and reload to dispatch.
      </Notice>
    );
  }

  const send = async () => {
    setState({ phase: "sending" });
    try {
      const record = await postDispatch({
        plant_id: plant.plant_id,
        as_of: asOf,
        ...(crew ? { crew_id: crew.crew_id } : {}),
      });
      setState({ phase: "sent", record });
      onDispatched(record);
    } catch (error) {
      if (error instanceof DispatchError) {
        setState({ phase: "failed", status: error.status, message: error.message });
        return;
      }
      setState({
        phase: "failed",
        status: null,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const grossRecovery =
    plant.recoverable_usd === null ? null : plant.recoverable_usd + plant.cleaning_cost_usd;

  return (
    <section className="border border-rule bg-surface p-4">
      {state.phase === "idle" ? (
        <>
          <h3 className="font-medium">Send a crew</h3>
          <p className="mt-1 max-w-[62ch] text-[13px] text-ink-soft">
            {crew
              ? `${crew.crew_id} out of ${crew.home_base}, ${formatDays(crew.crew_days)} of crew time.`
              : "No crew suggested for this plant; the backend will assign one."}
          </p>
          <button
            type="button"
            onClick={() => setState({ phase: "confirming" })}
            className={
              verdict.kind === "CLEAR"
                ? "mt-3 bg-ink px-4 py-2 text-[14px] text-surface transition-colors hover:bg-ink-soft"
                : "mt-3 border border-ink px-4 py-2 text-[14px] text-ink transition-colors hover:bg-paper"
            }
          >
            Review dispatch
          </button>
          {verdict.kind === "MARGINAL" && (
            <p className="mt-2 max-w-[62ch] text-[13px] text-ink-soft">
              This one is inside the noise. Read the numbers before committing the truck.
            </p>
          )}
        </>
      ) : (
        <>
          <h3 className="font-medium">Confirm the spend</h3>
          <dl className="tabular mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2">
            <Line label="Wash cost, committed now" value={formatUsd(plant.cleaning_cost_usd)} />
            <Line
              label="Recovered before the next rain"
              value={grossRecovery === null ? "—" : formatUsd(grossRecovery)}
            />
            <Line
              label="Net"
              value={plant.recoverable_usd === null ? "—" : formatUsd(plant.recoverable_usd)}
            />
            <Line
              label="Crew time"
              value={crew ? formatDays(crew.crew_days) : "assigned by the backend"}
            />
          </dl>

          <p className="mt-3 max-w-[64ch] text-[13px] text-ink-soft">
            Based on soiling of{" "}
            {plant.soiling_loss_pct === null ? "—" : formatPct(plant.soiling_loss_pct)} against a
            break-even of {formatPct(plant.break_even_soiling_pct)}, over{" "}
            {plant.days_until_next_reset} days to the next expected rain reset, on{" "}
            {formatEnergyMwh(plant.expected_energy_kwh_per_day)} at $
            {plant.tariff_per_kwh.toFixed(3)}/kWh. The soiling figure comes from{" "}
            {plant.usable_days} usable {plant.usable_days === 1 ? "day" : "days"} of readings.
          </p>

          {state.phase === "failed" && (
            <p className="mt-3 border-l-2 border-alert bg-alert-wash px-3 py-2 text-[13px] text-ink">
              {failureCopy(state.status, state.message)}
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={send}
              disabled={state.phase === "sending"}
              className="bg-ink px-4 py-2 text-[14px] text-surface transition-colors hover:bg-ink-soft disabled:opacity-50"
            >
              {state.phase === "sending"
                ? "Dispatching…"
                : `Dispatch and spend ${formatUsd(plant.cleaning_cost_usd)}`}
            </button>
            <button
              type="button"
              onClick={() => setState({ phase: "idle" })}
              disabled={state.phase === "sending"}
              className="px-4 py-2 text-[14px] text-ink-soft underline decoration-rule-strong underline-offset-4 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/** The refusals the contract defines, in words that say what to do next. */
function failureCopy(status: number | null, message: string): string {
  switch (status) {
    case 409:
      return `${message} A plant can be dispatched once per date, and the snapshot is rebuilt each morning. Reload to see the current state.`;
    case 422:
      return `${message} Crews work their home region only, so this plant needs a crew based in its own region.`;
    case 404:
      return `${message} This plant is not in the current snapshot.`;
    default:
      return message;
  }
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-1">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border border-rule bg-paper/60 p-4">
      <h3 className="text-[14px] font-medium">{title}</h3>
      <p className="mt-1 max-w-[62ch] text-[13px] text-ink-soft">{children}</p>
    </section>
  );
}
