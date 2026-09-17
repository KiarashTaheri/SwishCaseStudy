/**
 * The one client for the backend described in `docs/api-contract.md`.
 *
 * Reads and dispatches are treated differently on purpose. A read falls back to
 * the bundled sample so the screen is demonstrable before the backend is up; a
 * dispatch never falls back, because it spends money and there is nothing
 * honest to return when the write did not happen.
 */

import fleetFixture from "@/fixtures/fleet.json";
import historyFixture from "@/fixtures/history.json";
import type {
  DispatchRecord,
  DispatchRequest,
  FleetSnapshot,
  HistoryPoint,
  PlantDetail,
  PlantRow,
} from "./contract";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

/** How long to wait before deciding the backend is not there. */
const REQUEST_TIMEOUT_MS = 4000;

export type DataSource = "api" | "fixture";

export interface Loaded<T> {
  data: T;
  source: DataSource;
  /** Why the fixture was used. Present only when `source` is "fixture". */
  fallbackReason?: string;
}

/** A dispatch that the backend refused, carrying the status the UI branches on. */
export class DispatchError extends Error {
  constructor(
    readonly status: number | null,
    message: string,
  ) {
    super(message);
    this.name = "DispatchError";
  }
}

const SAMPLE_FLEET = fleetFixture as unknown as FleetSnapshot;
const SAMPLE_HISTORY = historyFixture as unknown as Record<string, HistoryPoint[]>;

export async function fetchFleet(): Promise<Loaded<FleetSnapshot>> {
  try {
    const payload = await getJson(`${API_BASE}/api/fleet`);
    if (!isFleetSnapshot(payload)) {
      throw new Error("response did not match the fleet contract");
    }
    return { data: payload, source: "api" };
  } catch (error) {
    return {
      data: SAMPLE_FLEET,
      source: "fixture",
      fallbackReason: describe(error),
    };
  }
}

export async function fetchPlant(plantId: string): Promise<Loaded<PlantDetail>> {
  try {
    const payload = await getJson(`${API_BASE}/api/plants/${encodeURIComponent(plantId)}`);
    if (!isPlantDetail(payload)) {
      throw new Error("response did not match the plant contract");
    }
    return { data: payload, source: "api" };
  } catch (error) {
    const sample = samplePlantDetail(plantId);
    if (!sample) throw error;
    return { data: sample, source: "fixture", fallbackReason: describe(error) };
  }
}

export async function postDispatch(request: DispatchRequest): Promise<DispatchRecord> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/dispatch`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    throw new DispatchError(
      null,
      `Could not reach the API at ${API_BASE}. Nothing was dispatched. (${describe(error)})`,
    );
  }

  if (!response.ok) {
    throw new DispatchError(response.status, await readErrorMessage(response));
  }

  const payload: unknown = await response.json();
  if (!isDispatchRecord(payload)) {
    throw new DispatchError(
      response.status,
      "The API accepted the dispatch but returned a record this screen could not read. Check /api/dispatches before re-sending.",
    );
  }
  return payload;
}

/** The sample detail the fixtures can support: a row plus its real history. */
function samplePlantDetail(plantId: string): PlantDetail | null {
  const row = findPlant(SAMPLE_FLEET, plantId);
  if (!row) return null;
  return {
    ...row,
    history: SAMPLE_HISTORY[plantId] ?? [],
    // The briefing and work order are generated server-side. Inventing them
    // here would put prose on screen that no model or template produced.
    briefing: null,
    work_order: null,
  };
}

export function findPlant(fleet: FleetSnapshot, plantId: string): PlantRow | null {
  for (const region of fleet.regions) {
    const match = [...region.recommendations, ...region.withheld].find(
      (plant) => plant.plant_id === plantId,
    );
    if (match) return match;
  }
  return null;
}

async function getJson(url: string): Promise<unknown> {
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}

/** FastAPI puts the message in `detail`, as a string or a validation array. */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body)) {
      const detail = body.detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) => (isRecord(item) && typeof item.msg === "string" ? item.msg : null))
          .filter((message): message is string => message !== null);
        if (messages.length > 0) return messages.join("; ");
      }
    }
  } catch {
    // A non-JSON error body is not itself an error; fall through to the status.
  }
  return `The API refused the dispatch (HTTP ${response.status}).`;
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/*
 * Structural checks at the trust boundary. They confirm the shape the screen
 * indexes into rather than every field: a deeper schema would need a validation
 * dependency, and the contract is frozen, so drift shows up as a missing top
 * level key first.
 */

function isFleetSnapshot(value: unknown): value is FleetSnapshot {
  return (
    isRecord(value) &&
    typeof value.as_of === "string" &&
    isRecord(value.summary) &&
    Array.isArray(value.regions) &&
    value.regions.every(
      (region) =>
        isRecord(region) &&
        typeof region.region === "string" &&
        Array.isArray(region.crews) &&
        Array.isArray(region.recommendations) &&
        Array.isArray(region.withheld),
    )
  );
}

function isPlantDetail(value: unknown): value is PlantDetail {
  return (
    isRecord(value) &&
    typeof value.plant_id === "string" &&
    typeof value.break_even_soiling_pct === "number" &&
    isRecord(value.quality) &&
    Array.isArray(value.history)
  );
}

function isDispatchRecord(value: unknown): value is DispatchRecord {
  return (
    isRecord(value) &&
    typeof value.dispatch_id === "string" &&
    typeof value.plant_id === "string" &&
    isRecord(value.snapshot) &&
    typeof value.work_order === "string"
  );
}
