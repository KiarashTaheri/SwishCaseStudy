"use client";

import { useCallback, useEffect, useState } from "react";

import { PlantDrawer } from "@/components/PlantDrawer";
import { RegionBand } from "@/components/RegionBand";
import { fetchFleet, type DataSource } from "@/lib/api";
import type { FleetSnapshot } from "@/lib/contract";
import { formatDate, formatUsd } from "@/lib/format";

type FleetState =
  | { phase: "loading" }
  | { phase: "loaded"; fleet: FleetSnapshot; source: DataSource; reason?: string };

/**
 * The fleet, for the asset manager, on one screen.
 *
 * Ordered by region rather than by money, because a region is the unit of
 * dispatch: a crew works its home region only. A fleet-wide ranking would put a
 * Rajasthan plant above an Arizona one and imply a truck movement that cannot
 * happen — see DECISIONS.md #7.
 *
 * Rendered on the client rather than the server. The screen has to work with
 * the backend down, falling back to the bundled sample and saying so, and a
 * server component would fail the whole page instead.
 */
export default function FleetPage() {
  const [state, setState] = useState<FleetState>({ phase: "loading" });
  const [openPlantId, setOpenPlantId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await fetchFleet();
    setState({
      phase: "loaded",
      fleet: loaded.data,
      source: loaded.source,
      reason: loaded.fallbackReason,
    });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.phase === "loading") {
    return (
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-16 sm:px-6">
        <p className="text-[15px] text-ink-soft">Loading the fleet…</p>
      </main>
    );
  }

  const { fleet, source, reason } = state;
  const { summary } = fleet;

  return (
    <>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        <header className="mb-8">
          <p className="text-[12px] uppercase tracking-[0.12em] text-ink-faint">
            Fleet soiling &amp; cleaning advisor
          </p>
          <h1 className="mt-2 text-[27px] font-semibold leading-tight tracking-[-0.02em] sm:text-[32px]">
            Where to send a crew tomorrow
          </h1>
          <p className="tabular mt-2 text-[14px] text-ink-soft">
            As of {formatDate(fleet.as_of)} — the most recent day in the data, not
            today&rsquo;s date.
          </p>

          <dl className="mt-6 grid grid-cols-2 gap-px border border-rule bg-rule sm:grid-cols-4">
            <Stat label="Plants" value={String(summary.plants_total)} />
            <Stat
              label="Worth cleaning"
              value={String(summary.actionable)}
              emphasis={summary.actionable > 0}
            />
            <Stat label="Not recommended" value={String(summary.withheld)} />
            <Stat
              label="Recoverable"
              value={formatUsd(summary.total_recoverable_usd)}
              emphasis={summary.total_recoverable_usd > 0}
            />
          </dl>

          {source === "fixture" && (
            <p className="mt-4 border border-alert/30 bg-alert-wash px-4 py-3 text-[13px] leading-relaxed text-ink">
              <strong className="font-medium">Showing the bundled sample.</strong> The
              API could not be reached, so these figures are a saved snapshot and
              nothing here can be dispatched.
              {reason ? <span className="text-ink-soft"> ({reason})</span> : null}
            </p>
          )}
        </header>

        <p className="mb-5 max-w-2xl text-[14px] leading-relaxed text-ink-soft">
          Each crew works its home region only, so plants are ranked inside a region
          and never against another. There is no fleet-wide list. Plants that are not
          recommended stay on screen with their reason — a plant nobody can rank is
          information, not a gap.
        </p>

        <div className="flex flex-col gap-6">
          {fleet.regions.map((region) => (
            <RegionBand
              key={region.region}
              region={region}
              onOpenPlant={setOpenPlantId}
            />
          ))}
        </div>

        <footer className="mt-10 border-t border-rule pt-5 text-[13px] leading-relaxed text-ink-faint">
          Withheld readings are excluded from every figure above and reported with
          their signature only. The data cannot distinguish an inverter fault from
          curtailment from a metering error, so this screen never names a cause.
        </footer>
      </main>

      {openPlantId && (
        <PlantDrawer
          plantId={openPlantId}
          asOf={fleet.as_of}
          onClose={() => setOpenPlantId(null)}
          onDispatched={() => {
            // Re-read the fleet so the dispatched badge and the totals reflect
            // the spend that was just committed.
            void load();
          }}
        />
      )}
    </>
  );
}

function Stat({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="text-[12px] text-ink-faint">{label}</dt>
      <dd
        className={`tabular mt-1 text-[21px] font-medium tracking-[-0.01em] ${
          emphasis ? "text-signal" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
