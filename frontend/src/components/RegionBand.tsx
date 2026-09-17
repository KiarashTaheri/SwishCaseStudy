"use client";

import { PlantRowButton } from "@/components/PlantRowButton";
import type { RegionBlock } from "@/lib/contract";
import { allPlants, regionAxisMax } from "@/lib/decision";
import { crewCapacityNote, regionHorizonNote } from "@/lib/region";
import { formatUsd } from "@/lib/format";

interface RegionBandProps {
  region: RegionBlock;
  onOpenPlant: (plantId: string) => void;
}

/**
 * A region is the unit of dispatch: a crew works its home region only, so
 * plants are ranked inside a band and never against another band. The screen
 * has no global ranking for that reason — it would suggest a truck movement
 * that cannot happen.
 */
export function RegionBand({ region, onOpenPlant }: RegionBandProps) {
  const plants = allPlants(region);
  const axisMax = regionAxisMax(plants);
  const horizonNote = regionHorizonNote(region);
  const recoverable = region.recommendations.reduce(
    (total, plant) => total + (plant.recoverable_usd ?? 0),
    0,
  );

  return (
    <section className="border border-rule bg-surface">
      <header className="border-b border-rule px-4 pt-5 pb-4 sm:px-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="text-[19px] font-medium tracking-[-0.01em]">{region.region}</h2>
          <p className="tabular text-[13px] text-ink-soft">{crewCapacityNote(region)}</p>
        </div>

        <ul className="tabular mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-faint">
          {region.crews.map((crew) => (
            <li key={crew.crew_id}>
              {crew.crew_id} · {crew.home_base} · {crew.mw_per_day.toFixed(1)} MW/day ·{" "}
              {formatUsd(crew.day_rate_usd)}/day
            </li>
          ))}
        </ul>

        {horizonNote && (
          <p className="mt-3 max-w-[70ch] text-[13px] text-ink-soft">{horizonNote}</p>
        )}
      </header>

      <div>
        <GroupHeading
          title={
            region.recommendations.length > 0
              ? `Clears break-even (${region.recommendations.length})`
              : "Clears break-even"
          }
          note={
            region.recommendations.length > 0
              ? `${formatUsd(recoverable)} recoverable if every one is cleaned`
              : null
          }
        />
        {region.recommendations.length === 0 ? (
          <p className="border-t border-rule px-4 py-4 text-[14px] text-ink-soft sm:px-6">
            Nothing here is worth cleaning today. Every plant below sits under its own
            break-even.
          </p>
        ) : (
          region.recommendations.map((plant) => (
            <PlantRowButton
              key={plant.plant_id}
              plant={plant}
              axisMax={axisMax}
              onOpen={onOpenPlant}
            />
          ))
        )}

        {region.withheld.length > 0 && (
          <>
            <GroupHeading
              title={`Not worth cleaning today (${region.withheld.length})`}
              note="Kept on screen: a plant that stops earning matters more than any wash"
            />
            {region.withheld.map((plant) => (
              <PlantRowButton
                key={plant.plant_id}
                plant={plant}
                axisMax={axisMax}
                onOpen={onOpenPlant}
              />
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function GroupHeading({ title, note }: { title: string; note: string | null }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-0.5 bg-paper/60 px-4 pt-3 pb-2 sm:px-6">
      <h3 className="text-[13px] font-medium text-ink">{title}</h3>
      {note && <p className="tabular text-[13px] text-ink-faint">{note}</p>}
    </div>
  );
}
