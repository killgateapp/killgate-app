import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { SlotMeter } from "@/components/killgate/slot-meter";
import { slotStatus } from "@/lib/killgate/slots.ts";
import { useKillgate } from "@/lib/killgate/store.ts";
import { useHydrated } from "@/lib/killgate/use-hydrated.ts";

export function AppShell({ children }: { children: ReactNode }) {
  const ready = useHydrated();
  const ventures = useKillgate((s) => s.ventures);
  const slots = slotStatus(ventures);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link to="/" className="flex shrink-0 items-center gap-3 whitespace-nowrap text-foreground">
            <img
              src="/favicon.svg"
              alt=""
              width={36}
              height={36}
              className="size-9 rounded-md"
            />
            <span className="grid leading-none">
              <strong className="font-display text-lg font-medium tracking-tight">
                Killgate
              </strong>
              <small className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted">
                Private validation
              </small>
            </span>
          </Link>
          {ready ? (
            <SlotMeter used={slots.used} compact />
          ) : (
            <p className="hidden max-w-xs text-right text-xs text-muted sm:block">
              AI may summarize. It cannot open the gate.
            </p>
          )}
        </div>
      </header>
      {children}
    </div>
  );
}
