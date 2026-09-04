import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/killgate/app-shell";
import { SlotMeter } from "@/components/killgate/slot-meter";
import { GateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHint, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { isLiveLocked, slotStatus } from "@/lib/killgate/slots.ts";
import { useKillgate } from "@/lib/killgate/store.ts";
import type { SystemState } from "@/lib/killgate/types.ts";
import { useHydrated } from "@/lib/killgate/use-hydrated.ts";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  const navigate = useNavigate();
  const ventures = useKillgate((s) => s.ventures);
  const createVenture = useKillgate((s) => s.createVenture);
  const loadSample = useKillgate((s) => s.loadSample);
  const removeVenture = useKillgate((s) => s.removeVenture);
  const archiveVenture = useKillgate((s) => s.archiveVenture);
  const unarchiveVenture = useKillgate((s) => s.unarchiveVenture);
  const [hypothesis, setHypothesis] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const ready = useHydrated();
  const slots = slotStatus(ventures);

  const live = ventures.filter(isLiveLocked);
  const drafts = ventures.filter((row) => !row.archivedAt && !isLiveLocked(row));
  const archived = ventures.filter((row) => Boolean(row.archivedAt));

  const open = (id: string) => {
    void navigate({ to: "/v/$ventureId", params: { ventureId: id } });
  };

  const trySample = (kind: "empty" | "go-build") => {
    const result = loadSample(kind);
    if (result.ok) {
      setNotice(null);
      open(result.id);
      return;
    }
    setNotice(result.message);
  };

  return (
    <AppShell>
      <main className="mx-auto grid max-w-6xl gap-10 px-4 py-10 sm:px-6 sm:py-14">
        <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted">
              Adaptive validation · v2
            </p>
            <h1 className="mt-4 max-w-xl text-3xl">
              Most ideas should not be built. This gate makes that decision expensive to fake.
            </h1>
            <p className="mt-4 max-w-xl text-muted">
              Three live locks. Drafts are cheap. A lock is not. Archive a finished or killed
              idea to free a slot. The thing you keep is the evidence packet, not a pile of
              verdicts.
            </p>
          </div>
          <Card>
            <CardTitle>Open a draft</CardTitle>
            <CardHint className="mt-2">
              One paragraph. Private to this browser. Locking the buyer and price uses a live
              slot.
            </CardHint>
            <form
              className="mt-4 grid gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!hypothesis.trim()) return;
                const id = createVenture(hypothesis.trim());
                setHypothesis("");
                setNotice(null);
                open(id);
              }}
            >
              <Textarea
                required
                maxLength={4000}
                value={hypothesis}
                onChange={(event) => setHypothesis(event.target.value)}
                placeholder="Who hurts, what they do today, and what you want to sell."
              />
              <Button type="submit">Start a draft</Button>
            </form>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={() => trySample("empty")}>
                Load repair-shop draft
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={slots.full}
                onClick={() => trySample("go-build")}
              >
                Load GO BUILD sample
              </Button>
            </div>
            {notice ? <p className="mt-3 text-sm text-kill">{notice}</p> : null}
          </Card>
        </section>

        <section className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[auto_1fr] sm:items-center sm:p-5">
          <SlotMeter used={ready ? slots.used : 0} />
          <p className="text-sm text-muted">
            {slots.full
              ? "All three live locks are taken. Archive one before you confirm another buyer, price, and offer."
              : "A live lock is a confirmed buyer, price, and offer. Pivot inside a lock. Do not open a fourth."}
          </p>
        </section>

        <WorkspaceGroup
          title="Live locks"
          empty="No live contracts. Confirm a buyer and price on a draft to occupy a slot."
          rows={ready ? live : []}
          ready={ready}
          onOpen={open}
          onArchive={(id) => {
            archiveVenture(id);
            setNotice(null);
          }}
          onRemove={removeVenture}
        />

        <WorkspaceGroup
          title="Drafts"
          empty="No open drafts."
          rows={ready ? drafts : []}
          ready={ready}
          onOpen={open}
          onRemove={removeVenture}
        />

        <WorkspaceGroup
          title="Archive"
          empty="Archive keeps the ledger and frees a live slot."
          rows={ready ? archived : []}
          ready={ready}
          onOpen={open}
          onUnarchive={(id) => {
            const result = unarchiveVenture(id);
            setNotice(result.ok ? null : result.message);
          }}
          onRemove={removeVenture}
          archived
        />

        <section className="grid gap-3 border-t border-border pt-8 sm:grid-cols-2 lg:grid-cols-4">
          <Rule
            title="Slots, not ideas"
            body="Unlimited drafts. Three live locks. Archive is free. That is how Killgate refuses to be an idea mill."
          />
          <Rule
            title="The system picks the profile"
            body="Sales-assisted or self-serve is chosen from price, cadence, and whether a sales call is required. You cannot pick the easier gate."
          />
          <Rule
            title="KILL is expensive"
            body="Only a completed low-pain sample or a fatal constraint with verified non-AI sources plus your confirmation. Outages never kill."
          />
          <Rule
            title="Keep the packet"
            body="Export the evidence ledger. A GO is a contract against that file, not a month of software you can binge."
          />
        </section>
      </main>
    </AppShell>
  );
}

function WorkspaceGroup({
  title,
  empty,
  rows,
  ready,
  onOpen,
  onArchive,
  onUnarchive,
  onRemove,
  archived = false,
}: {
  title: string;
  empty: string;
  rows: SystemState[];
  ready: boolean;
  onOpen: (id: string) => void;
  onArchive?: (id: string) => void;
  onUnarchive?: (id: string) => void;
  onRemove: (id: string) => void;
  archived?: boolean;
}) {
  return (
    <section className="grid gap-3">
      <div className="flex items-end justify-between gap-4">
        <h2 className="font-display text-xl">{title}</h2>
        <p className="text-xs text-muted">
          {ready ? `${rows.length} here` : "Restoring…"}
        </p>
      </div>
      {!ready ? (
        <Card className="text-sm text-muted">Restoring local evidence…</Card>
      ) : rows.length === 0 ? (
        <Card>
          <p className="text-sm text-muted">{empty}</p>
        </Card>
      ) : (
        <ul className="grid gap-3">
          {rows.map((venture) => (
            <li key={venture.id}>
              <Card className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <button
                  className="min-w-0 flex-1 text-left"
                  onClick={() => onOpen(venture.id)}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {venture.gateRecommendation ? (
                      <GateBadge recommendation={venture.gateRecommendation} />
                    ) : null}
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
                      {archived ? "archived" : venture.phase}
                    </span>
                  </div>
                  <p className="mt-2 font-display text-lg leading-snug">
                    {venture.name}
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-muted">
                    {venture.hypothesis}
                  </p>
                </button>
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => onOpen(venture.id)}>
                    Open
                  </Button>
                  {onArchive ? (
                    <Button variant="ghost" onClick={() => onArchive(venture.id)}>
                      Archive
                    </Button>
                  ) : null}
                  {onUnarchive ? (
                    <Button variant="secondary" onClick={() => onUnarchive(venture.id)}>
                      Unarchive
                    </Button>
                  ) : null}
                  <Button variant="ghost" onClick={() => onRemove(venture.id)}>
                    Remove
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Rule({ title, body }: { title: string; body: string }) {
  return (
    <div className="grid gap-2">
      <h3 className="font-display text-lg">{title}</h3>
      <p className="text-sm text-muted">{body}</p>
    </div>
  );
}
