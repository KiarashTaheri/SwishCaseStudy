"use client";

import { useState } from "react";

/**
 * The crew lead's half of the system: generated text, shown verbatim and
 * copyable so it can be sent on. There is no second interface for him.
 */
export function WorkOrder({ text }: { text: string }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      // Clipboard access is blocked in some contexts; the text stays selectable.
      setCopyState("failed");
    }
  };

  return (
    <div className="border border-rule bg-paper/50">
      <div className="flex items-center justify-between gap-4 border-b border-rule px-3 py-2">
        <h4 className="text-[13px] font-medium">Work order</h4>
        <button
          type="button"
          onClick={copy}
          className="text-[13px] text-ink-soft underline decoration-rule-strong underline-offset-4"
        >
          {copyState === "copied"
            ? "Copied"
            : copyState === "failed"
              ? "Select and copy"
              : "Copy"}
        </button>
      </div>
      <pre className="font-doc max-h-72 overflow-auto px-3 py-3 text-[14px] leading-relaxed whitespace-pre-wrap">
        {text}
      </pre>
    </div>
  );
}
