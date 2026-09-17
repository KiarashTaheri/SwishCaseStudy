"use client";

import { SoilingBar, soilingBarLabel } from "@/components/SoilingBar";
import type { PlantRow } from "@/lib/contract";
import { verdictFor } from "@/lib/decision";
import { verdictDetail, verdictTitle } from "@/lib/copy";
import { formatPct, formatPoints } from "@/lib/format";

interface PlantRowButtonProps {
  plant: PlantRow;
  /** Shared axis maximum for the region, so bars compare across the band. */
  axisMax: number;
  onOpen: (plantId: string) => void;
}

/**
 * One plant, as a row in its region's band. The whole row opens the plant, so
 * there is no second click target inside it; spending money happens one level
 * deeper, behind the confirmation.
 */
export function PlantRowButton({ plant, axisMax, onOpen }: PlantRowButtonProps) {
  const verdict = verdictFor(plant);
  const isRecommended = verdict.kind === "CLEAR";
  const marginText = plant.margin_pct === null ? "—" : formatPoints(plant.margin_pct);

  return (
    <button
      type="button"
      onClick={() => onOpen(plant.plant_id)}
      className="group grid w-full grid-cols-1 items-start gap-x-6 gap-y-3 border-t border-rule px-4 py-4 text-left transition-colors hover:bg-paper/70 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,1fr)]"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="truncate font-medium">{plant.name}</span>
          {plant.dispatched && (
            <span className="rounded-full bg-ink px-2 py-0.5 text-[11px] text-surface">
              Dispatched
            </span>
          )}
        </div>
        <p className="tabular mt-0.5 text-[13px] text-ink-faint">
          {plant.plant_id} · {plant.capacity_mw.toFixed(1)} MW ·{" "}
          {plant.usable_days} usable {plant.usable_days === 1 ? "day" : "days"}
        </p>
        {plant.quality.note && <QualityNote note={plant.quality.note} />}
      </div>

      <div className="min-w-0 lg:pt-1">
        <SoilingBar
          soilingPct={plant.soiling_loss_pct}
          breakEvenPct={plant.break_even_soiling_pct}
          axisMax={axisMax}
          isRecommended={isRecommended}
          label={soilingBarLabel(plant.soiling_loss_pct, plant.break_even_soiling_pct)}
        />
        <p className="tabular mt-1.5 text-[13px] text-ink-soft">
          soiling{" "}
          {plant.soiling_loss_pct === null ? "—" : formatPct(plant.soiling_loss_pct)} · break-even{" "}
          {formatPct(plant.break_even_soiling_pct)}
        </p>
      </div>

      <div className="min-w-0">
        <p
          className={`tabular text-[17px] leading-tight font-medium ${
            isRecommended ? "text-signal" : "text-ink"
          }`}
        >
          {marginText}
          <span className="ml-2 text-[13px] font-normal text-ink-soft">
            {verdictTitle(verdict)}
          </span>
        </p>
        <p className="mt-0.5 text-[13px] text-ink-soft">{verdictDetail(verdict, plant)}</p>
      </div>
    </button>
  );
}

/**
 * The backend's evidence line, verbatim. It says what was withheld and that the
 * cause is not determinable; anything added here would be a guess at the cause.
 */
function QualityNote({ note }: { note: string }) {
  return (
    <p className="mt-2 border-l-2 border-rule-strong pl-2 text-[13px] text-ink-soft">{note}</p>
  );
}
