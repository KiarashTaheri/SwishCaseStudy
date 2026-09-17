import Link from "next/link";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Rendered on the right — the page's primary action, if it has one. */
  action?: ReactNode;
  /** Shown above the title as a way back, for pages below the fleet view. */
  backHref?: string;
  backLabel?: string;
}

/**
 * The bar every page opens with: where you are, when the data is from, and the
 * one action the page offers.
 */
export function PageHeader({
  title,
  subtitle,
  action,
  backHref,
  backLabel,
}: PageHeaderProps) {
  return (
    <header className="border-b border-rule bg-surface px-6 py-4">
      {backHref && (
        <Link
          href={backHref}
          className="mb-1 inline-flex items-center gap-1 text-[12.5px] text-ink-soft transition-colors hover:text-signal"
        >
          <span aria-hidden>‹</span> {backLabel ?? "Back"}
        </Link>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-[19px] font-semibold tracking-[-0.01em] text-ink-strong">
            {title}
          </h1>
          {subtitle && (
            <p className="tabular mt-0.5 text-[13px] text-ink-soft">{subtitle}</p>
          )}
        </div>
        {action}
      </div>
    </header>
  );
}
