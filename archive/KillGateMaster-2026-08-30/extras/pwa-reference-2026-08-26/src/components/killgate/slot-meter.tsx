import { MAX_LIVE_LOCKS } from "@/lib/killgate/slots.ts";
import { cn } from "@/lib/utils";

export function SlotMeter({
  used,
  compact = false,
}: {
  used: number;
  compact?: boolean;
}) {
  const clamped = Math.min(MAX_LIVE_LOCKS, Math.max(0, used));
  return (
    <div className={cn("grid gap-2", compact && "justify-items-end")}>
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted">
        Live locks {clamped}/{MAX_LIVE_LOCKS}
      </p>
      <div className="flex gap-1.5" aria-hidden>
        {Array.from({ length: MAX_LIVE_LOCKS }, (_, index) => (
          <span
            key={index}
            className={cn(
              "h-2 w-6 rounded-sm border",
              index < clamped
                ? "border-accent bg-accent"
                : "border-border-strong bg-transparent",
            )}
          />
        ))}
      </div>
    </div>
  );
}
