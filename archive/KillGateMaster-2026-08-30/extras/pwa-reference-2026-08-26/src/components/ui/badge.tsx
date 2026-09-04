import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
import type { GateRecommendation } from "@/lib/killgate/types.ts";
import { GATE_COPY } from "@/lib/killgate/types.ts";

const toneClass: Record<string, string> = {
  go: "bg-go/15 text-go border-go/40",
  wait: "bg-wait/10 text-wait border-wait/30",
  pivot: "bg-pivot/15 text-pivot border-pivot/40",
  kill: "bg-kill/15 text-kill border-kill/40",
  stop: "bg-stop/20 text-muted border-border-strong",
};

export function Badge({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-[0.14em]",
        className,
      )}
      {...props}
    />
  );
}

export function GateBadge({
  recommendation,
  className,
}: {
  recommendation: GateRecommendation;
  className?: string;
}) {
  const copy = GATE_COPY[recommendation];
  return (
    <Badge className={cn(toneClass[copy.tone], className)}>{copy.label}</Badge>
  );
}
