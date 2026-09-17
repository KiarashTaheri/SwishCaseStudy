"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { Sidebar } from "@/components/Sidebar";
import { fetchFleet, type DataSource } from "@/lib/api";
import type { FleetSnapshot } from "@/lib/contract";

interface FleetContextValue {
  fleet: FleetSnapshot | null;
  source: DataSource | null;
  fallbackReason?: string;
  /** Re-read the fleet. Called after a dispatch so totals and badges catch up. */
  reload: () => Promise<void>;
}

const FleetContext = createContext<FleetContextValue>({
  fleet: null,
  source: null,
  reload: async () => {},
});

export function useFleet() {
  return useContext(FleetContext);
}

/**
 * The application shell: sidebar, and one fleet load shared by every page.
 *
 * Fetched once here rather than per page because the sidebar needs the plant
 * list on every route, and a detail page that re-fetched the whole fleet to
 * draw its own navigation would issue two requests for one screen.
 *
 * Client-rendered on purpose. The screen has to work with the backend down —
 * falling back to the bundled sample and saying so — and a server component
 * would fail the whole route instead of degrading.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<FleetContextValue, "reload">>({
    fleet: null,
    source: null,
  });

  const reload = useCallback(async () => {
    const loaded = await fetchFleet();
    setState({
      fleet: loaded.data,
      source: loaded.source,
      fallbackReason: loaded.fallbackReason,
    });
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <FleetContext.Provider value={{ ...state, reload }}>
      <div className="flex min-h-screen">
        <Sidebar fleet={state.fleet} />
        <div className="flex min-w-0 flex-1 flex-col">
          {state.source === "fixture" && <SampleBanner reason={state.fallbackReason} />}
          {children}
        </div>
      </div>
    </FleetContext.Provider>
  );
}

function SampleBanner({ reason }: { reason?: string }) {
  return (
    <p className="border-b border-alert/20 bg-alert-wash px-6 py-2.5 text-[13px] text-ink">
      <strong className="font-medium">Showing the bundled sample.</strong> The API
      could not be reached, so nothing here can be dispatched.
      {reason ? <span className="text-ink-soft"> ({reason})</span> : null}
    </p>
  );
}
