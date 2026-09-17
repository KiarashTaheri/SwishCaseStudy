"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { WorkOrder } from "@/components/WorkOrder";
import { API_BASE } from "@/lib/api";
import type { DispatchRecord } from "@/lib/contract";
import { formatDate, formatPct, formatUsd } from "@/lib/format";

/**
 * The audit trail: every cleaning that was approved, and what was believed at
 * the time.
 *
 * Each record stores its own copy of the numbers rather than pointing at
 * today's. The estimate moves daily, so when a cleaning under-recovers the only
 * useful question is what the decision was made on — and that is unanswerable
 * from a plant id and a date.
 *
 * No fixture fallback here, unlike the fleet view. A sample dispatch history
 * would be a screen full of decisions nobody made.
 */
export default function DispatchesPage() {
  const [records, setRecords] = useState<DispatchRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/dispatches`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        return response.json() as Promise<{ dispatches: DispatchRecord[] }>;
      })
      .then((payload) => setRecords(payload.dispatches))
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : String(cause)),
      );
  }, []);

  return (
    <>
      <PageHeader
        title="Dispatches"
        subtitle="Approved cleanings, newest first — each with the figures it was approved on"
      />

      <main className="min-w-0 px-6 py-6">
        {error && (
          <p className="rounded-lg border border-alert/25 bg-alert-wash px-4 py-3 text-[13.5px]">
            Could not reach the API at {API_BASE}. ({error})
          </p>
        )}

        {!error && records === null && (
          <p className="text-[14px] text-ink-soft">Loading…</p>
        )}

        {records?.length === 0 && (
          <div className="rounded-lg border border-rule bg-surface px-4 py-8 text-center">
            <p className="text-[14px] text-ink-soft">Nothing dispatched yet.</p>
            <Link
              href="/"
              className="mt-1 inline-block text-[13.5px] text-signal hover:underline"
            >
              Go to the fleet overview
            </Link>
          </div>
        )}

        {records && records.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-rule bg-surface">
            <table className="w-full text-[13.5px]">
              <thead>
                <tr className="border-b border-rule bg-subtle text-left text-[11.5px] uppercase tracking-[0.06em] text-ink-soft">
                  <th className="px-4 py-2.5 font-semibold">Approved</th>
                  <th className="px-4 py-2.5 font-semibold">Plant</th>
                  <th className="px-4 py-2.5 font-semibold">Crew</th>
                  <th className="px-4 py-2.5 text-right font-semibold">
                    Soiling then
                  </th>
                  <th className="px-4 py-2.5 text-right font-semibold">
                    Expected recovery
                  </th>
                  <th className="px-4 py-2.5 font-semibold">Work order</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <Fragment key={record.dispatch_id}>
                    <tr className="border-b border-rule/70">
                      <td className="tabular px-4 py-2.5">
                        {formatDate(record.as_of)}
                        <span className="block text-[12px] text-ink-faint">
                          {record.dispatch_id}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <Link
                          href={`/plants/${record.plant_id}`}
                          className="font-medium text-ink-strong hover:text-signal"
                        >
                          {record.plant_id}
                        </Link>
                      </td>
                      <td className="tabular px-4 py-2.5 text-ink-soft">
                        {record.crew_id ?? "unassigned"}
                        {record.crew_days === null
                          ? ""
                          : ` · ${record.crew_days.toFixed(1)}d`}
                      </td>
                      <td className="tabular px-4 py-2.5 text-right">
                        {record.snapshot.soiling_loss_pct === null
                          ? "—"
                          : formatPct(record.snapshot.soiling_loss_pct)}
                        <span className="block text-[12px] text-ink-faint">
                          break-even{" "}
                          {formatPct(record.snapshot.break_even_soiling_pct)}
                        </span>
                      </td>
                      <td className="tabular px-4 py-2.5 text-right font-medium text-positive">
                        {record.snapshot.recoverable_usd === null
                          ? "—"
                          : `+${formatUsd(record.snapshot.recoverable_usd)}`}
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          type="button"
                          onClick={() =>
                            setOpenId(
                              openId === record.dispatch_id
                                ? null
                                : record.dispatch_id,
                            )
                          }
                          className="text-[13px] text-signal hover:underline"
                        >
                          {openId === record.dispatch_id ? "Hide" : "Show"}
                        </button>
                      </td>
                    </tr>
                    {openId === record.dispatch_id && (
                      <tr>
                        <td colSpan={6} className="bg-subtle px-4 py-3">
                          <WorkOrder text={record.work_order} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}
