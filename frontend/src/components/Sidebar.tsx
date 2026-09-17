"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { FleetSnapshot, PlantRow } from "@/lib/contract";

interface SidebarProps {
  fleet: FleetSnapshot | null;
}

/**
 * Persistent navigation, matching the SwishOS product shell.
 *
 * It exists for one reason beyond wayfinding: it makes the plants visibly
 * *navigable*. In the previous build the only way to open a plant was to click
 * a row that did not look like a link, so nobody discovered that a detail view
 * existed at all.
 *
 * Plants worth cleaning carry the signal dot, so the sidebar answers "is there
 * anything to do" before the page has been read.
 */
export function Sidebar({ fleet }: SidebarProps) {
  const pathname = usePathname();
  const plants = fleet ? allPlants(fleet) : [];
  const actionable = plants.filter((p) => p.status === "ACTIONABLE");

  return (
    <nav className="flex w-60 shrink-0 flex-col bg-shell text-on-shell max-lg:hidden">
      <div className="flex items-center gap-2.5 px-5 py-4">
        <Mark />
        <span className="text-[15px] font-semibold tracking-[-0.01em] text-white">
          SwishOS
        </span>
      </div>

      <div className="px-3 pb-2">
        <NavLink href="/" active={pathname === "/"} icon={<GridIcon />}>
          Fleet overview
        </NavLink>
        <NavLink
          href="/dispatches"
          active={pathname === "/dispatches"}
          icon={<TruckIcon />}
        >
          Dispatches
        </NavLink>
      </div>

      {plants.length > 0 && (
        <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          <p className="px-2.5 pb-2 pt-3 text-[11px] uppercase tracking-[0.1em] text-on-shell-soft">
            Plants
          </p>
          {plants.map((plant) => {
            const href = `/plants/${plant.plant_id}`;
            const isActionable = actionable.some(
              (a) => a.plant_id === plant.plant_id,
            );
            return (
              <Link
                key={plant.plant_id}
                href={href}
                className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors ${
                  pathname === href
                    ? "bg-shell-active text-white"
                    : "text-on-shell-soft hover:bg-shell-hover hover:text-on-shell"
                }`}
              >
                <span
                  aria-hidden
                  className={`size-1.5 shrink-0 rounded-full ${
                    isActionable ? "bg-signal" : "bg-white/15"
                  }`}
                />
                <span className="truncate">{plant.name}</span>
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-auto border-t border-white/8 px-5 py-4">
        <p className="text-[13px] text-white">Asset manager</p>
        <p className="text-[12px] text-on-shell-soft">
          {fleet ? `${plants.length} plants` : "—"}
        </p>
      </div>
    </nav>
  );
}

function NavLink({
  href,
  active,
  icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] transition-colors ${
        active
          ? "bg-shell-active text-white"
          : "text-on-shell-soft hover:bg-shell-hover hover:text-on-shell"
      }`}
    >
      {icon}
      {children}
    </Link>
  );
}

function allPlants(fleet: FleetSnapshot): PlantRow[] {
  return fleet.regions.flatMap((r) => [...r.recommendations, ...r.withheld]);
}

function Mark() {
  return (
    <span className="grid size-7 place-items-center rounded-md bg-signal">
      <svg viewBox="0 0 16 16" className="size-4 fill-white" aria-hidden>
        <path d="M2 10.5 8 7l6 3.5-6 3.5-6-3.5Z" opacity=".55" />
        <path d="M2 6.5 8 3l6 3.5L8 10 2 6.5Z" />
      </svg>
    </span>
  );
}

function GridIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-4 fill-current" aria-hidden>
      <path d="M2 2h5v5H2V2Zm7 0h5v5H9V2ZM2 9h5v5H2V9Zm7 0h5v5H9V9Z" />
    </svg>
  );
}

function TruckIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-4 fill-current" aria-hidden>
      <path d="M1 3h8v7H1V3Zm9 2h2.6L15 7.6V10h-5V5ZM4 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm8 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
    </svg>
  );
}
