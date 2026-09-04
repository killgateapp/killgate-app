import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/killgate/app-shell";
import { GateBoard } from "@/components/killgate/gate-board";
import { Button } from "@/components/ui/button";
import { Card, CardHint, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { GateBadge } from "@/components/ui/badge";
import { activeIdeaProfile } from "@/lib/killgate/evaluator.ts";
import { downloadEvidencePacket } from "@/lib/killgate/packet.ts";
import { canOpenLiveLock } from "@/lib/killgate/slots.ts";
import { evaluationFor, useKillgate } from "@/lib/killgate/store.ts";
import { profileLabel } from "@/lib/killgate/evaluator.ts";
import type {
  BillingCadence,
  BuyerValidationRecord,
  CommitmentType,
  FatalConstraintType,
  PainStrength,
  PriorityStatus,
  SalesMotion,
} from "@/lib/killgate/types.ts";
import { useHydrated } from "@/lib/killgate/use-hydrated.ts";
import { cn } from "@/lib/utils";

type BuyerDraft = Omit<
  BuyerValidationRecord,
  "recordId" | "ideaProfileId" | "createdAt" | "voidedAt" | "voidReason"
>;

export const Route = createFileRoute("/v/$ventureId")({ component: VenturePage });

const TABS = [
  "contract",
  "research",
  "buyers",
  "build",
  "risk",
  "log",
] as const;
type Tab = (typeof TABS)[number];

function VenturePage() {
  const { ventureId } = Route.useParams();
  const hydrated = useHydrated();
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === ventureId));
  const ventures = useKillgate((s) => s.ventures);
  const archiveVenture = useKillgate((s) => s.archiveVenture);
  const unarchiveVenture = useKillgate((s) => s.unarchiveVenture);
  const [tab, setTab] = useState<Tab>("contract");
  const [slotNotice, setSlotNotice] = useState<string | null>(null);

  if (!hydrated) {
    return (
      <AppShell>
        <main className="mx-auto max-w-xl px-4 py-16 text-sm text-muted">
          Restoring local evidence…
        </main>
      </AppShell>
    );
  }

  if (!venture) {
    return (
      <AppShell>
        <main className="mx-auto max-w-xl px-4 py-16">
          <h1 className="font-display text-2xl">Workspace not on this device</h1>
          <p className="mt-3 text-muted">
            Killgate stores evidence locally. This link has no matching venture here.
          </p>
          <Link to="/" className="mt-6 inline-flex min-h-11 items-center text-sm text-accent">
            Back to workspaces
          </Link>
        </main>
      </AppShell>
    );
  }

  const evaluation = evaluationFor(venture);
  const profile = activeIdeaProfile(venture);
  const archived = Boolean(venture.archivedAt);

  return (
    <AppShell>
      <main className="mx-auto grid max-w-6xl gap-6 overflow-x-hidden px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <Link to="/" className="text-sm text-muted hover:text-foreground">
            All workspaces
          </Link>
          <p className="max-w-full truncate font-mono text-[11px] uppercase tracking-[0.16em] text-muted">
            {venture.name}
          </p>
        </div>
        <GateBoard state={venture} evaluation={evaluation} />
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => downloadEvidencePacket(venture)}>
            Export evidence packet
          </Button>
          {archived ? (
            <Button
              variant="secondary"
              onClick={() => {
                const result = unarchiveVenture(venture.id);
                setSlotNotice(result.ok ? null : result.message);
              }}
            >
              Unarchive into a live slot
            </Button>
          ) : (
            <Button
              variant="ghost"
              onClick={() => {
                archiveVenture(venture.id);
                setSlotNotice(null);
              }}
            >
              Archive and free a slot
            </Button>
          )}
        </div>
        {archived ? (
          <p className="text-sm text-muted">
            Archived. Evidence is read-only. Unarchive uses a live slot if this contract is
            still locked.
          </p>
        ) : evaluation.recommendation === "KILL" ||
          evaluation.recommendation === "GO_SELL" ||
          evaluation.recommendation === "GO_BUILD" ? (
          <p className="text-sm text-muted">
            This decision still occupies a live slot until you archive it. Export the packet
            first if you need the ledger.
          </p>
        ) : null}
        {slotNotice ? <p className="text-sm text-kill">{slotNotice}</p> : null}
        <nav className="flex gap-1 overflow-x-auto pb-1">
          {TABS.map((item) => (
            <button
              key={item}
              onClick={() => setTab(item)}
              className={cn(
                "min-h-11 shrink-0 rounded-sm px-3 font-mono text-[11px] uppercase tracking-[0.14em]",
                tab === item
                  ? "bg-accent text-accent-foreground"
                  : "text-muted hover:bg-card hover:text-foreground",
              )}
            >
              {item}
            </button>
          ))}
        </nav>
        <fieldset disabled={archived} className="grid w-full min-w-0 gap-6 border-0 p-0">
          {tab === "contract" ? <ContractPanel id={venture.id} /> : null}
          {tab === "research" ? <ResearchPanel id={venture.id} /> : null}
          {tab === "buyers" ? <BuyersPanel id={venture.id} /> : null}
          {tab === "build" ? <BuildPanel id={venture.id} /> : null}
          {tab === "risk" ? <RiskPanel id={venture.id} /> : null}
          {tab === "log" ? <LogPanel id={venture.id} /> : null}
        </fieldset>
        {profile ? (
          <p className="max-w-full text-xs break-words text-muted">
            Active profile {profileLabel(profile.systemProfile)} · fingerprint{" "}
            <span className="font-mono">{profile.contractFingerprint.slice(0, 12)}</span>
          </p>
        ) : !archived && !canOpenLiveLock(ventures, venture.id) ? (
          <p className="text-sm text-kill">
            All three live locks are taken. Archive one before confirming this contract.
          </p>
        ) : null}
      </main>
    </AppShell>
  );
}

function ContractPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const lockProfile = useKillgate((s) => s.lockProfile);
  const ownerStop = useKillgate((s) => s.ownerStop);
  const resumeOwnerStop = useKillgate((s) => s.resumeOwnerStop);
  const ventures = useKillgate((s) => s.ventures);
  const profile = activeIdeaProfile(venture);
  const canLock = canOpenLiveLock(ventures, id);
  const [lockError, setLockError] = useState<string | null>(null);
  const [buyerType, setBuyerType] = useState(profile?.buyerType ?? "");
  const [salesMotion, setSalesMotion] = useState<SalesMotion>(
    profile?.salesMotion ?? "SELF_SERVE",
  );
  const [salesCallRequired, setSalesCallRequired] = useState(
    profile?.salesCallRequired ?? false,
  );
  const [targetPrice, setTargetPrice] = useState(String(profile?.targetPrice ?? "14.99"));
  const [cadence, setCadence] = useState<BillingCadence>(
    profile?.billingCadence ?? "MONTHLY",
  );
  const [problem, setProblem] = useState(profile?.problem ?? "");
  const [offer, setOffer] = useState(profile?.proposedOffer ?? "");

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_0.9fr]">
      <Card>
        <CardTitle>{profile ? "Pivot the locked profile" : "Confirm the idea profile"}</CardTitle>
        <CardHint className="mt-2">
          Killgate classifies sales-assisted vs self-serve. A material change supersedes the
          current version and starts a new contract. History is kept.
        </CardHint>
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const result = lockProfile(id, {
              buyerType,
              salesMotion,
              salesCallRequired,
              targetPrice: Number(targetPrice),
              billingCadence: cadence,
              problem,
              proposedOffer: offer,
            });
            setLockError(result.ok ? null : result.message);
          }}
        >
          <Field label="Buyer">
            <Input
              required
              value={buyerType}
              onChange={(e) => setBuyerType(e.target.value)}
              placeholder="Independent shop owner"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Sales motion">
              <NativeSelect
                value={salesMotion}
                onChange={(e) => setSalesMotion(e.target.value as SalesMotion)}
              >
                <option value="SELF_SERVE">Self-serve</option>
                <option value="SALES_ASSISTED">Sales-assisted</option>
                <option value="HYBRID">Hybrid</option>
              </NativeSelect>
            </Field>
            <Field label="Sales call required">
              <NativeSelect
                value={salesCallRequired ? "yes" : "no"}
                onChange={(e) => setSalesCallRequired(e.target.value === "yes")}
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </NativeSelect>
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Target price">
              <Input
                required
                type="number"
                min={0}
                step="0.01"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
              />
            </Field>
            <Field label="Cadence">
              <NativeSelect
                value={cadence}
                onChange={(e) => setCadence(e.target.value as BillingCadence)}
              >
                <option value="MONTHLY">Monthly</option>
                <option value="ANNUAL">Annual</option>
                <option value="WEEKLY">Weekly</option>
                <option value="ONE_TIME">One-time</option>
              </NativeSelect>
            </Field>
          </div>
          <Field label="Problem">
            <Textarea
              required
              value={problem}
              onChange={(e) => setProblem(e.target.value)}
            />
          </Field>
          <Field label="Proposed offer">
            <Textarea required value={offer} onChange={(e) => setOffer(e.target.value)} />
          </Field>
          <Button type="submit" disabled={!canLock && !profile}>
            {profile ? "Lock a pivot version" : "Lock contract"}
          </Button>
          {lockError ? <p className="text-sm text-kill">{lockError}</p> : null}
          {!canLock && !profile ? (
            <p className="text-sm text-muted">
              Archive a live lock first. Pivoting an already-locked idea does not use another
              slot.
            </p>
          ) : null}
        </form>
      </Card>
      <div className="grid gap-4">
        <Card>
          <CardTitle>Hypothesis</CardTitle>
          <p className="mt-3 text-sm leading-relaxed">{venture.hypothesis}</p>
        </Card>
        {venture.validationContract ? (
          <Card>
            <CardTitle>Locked contract {venture.validationContract.contractVersion}</CardTitle>
            <CardHint className="mt-2">
              {venture.validationContract.validationProfile
                ? profileLabel(venture.validationContract.validationProfile)
                : "Unclassified"}
            </CardHint>
            <ul className="mt-4 grid gap-2 text-sm">
              {venture.validationContract.decisionRules.GO_BUILD?.map((row) => (
                <li key={row} className="text-muted">
                  GO BUILD · {row}
                </li>
              ))}
            </ul>
            <ul className="mt-3 grid gap-2 text-sm text-muted">
              {venture.validationContract.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </Card>
        ) : null}
        <Card>
          <CardTitle>Owner control</CardTitle>
          <CardHint className="mt-2">
            Stopping is never recorded as an evidence-backed KILL.
          </CardHint>
          <div className="mt-4 flex flex-wrap gap-2">
            {venture.ownerStoppedAt ? (
              <Button variant="secondary" onClick={() => resumeOwnerStop(id)}>
                Resume evaluation
              </Button>
            ) : (
              <Button variant="kill" onClick={() => ownerStop(id)}>
                Owner stop
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function ResearchPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const addSource = useKillgate((s) => s.addSource);
  const rejectSource = useKillgate((s) => s.rejectSource);
  const completeResearch = useKillgate((s) => s.completeResearch);
  const profile = activeIdeaProfile(venture);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [theme, setTheme] = useState("problem");
  const run = [...venture.researchRuns]
    .reverse()
    .find((row) => row.ideaProfileId === profile?.profileId);
  const sources = venture.sourceEvidence.filter(
    (source) => !run || source.researchRunId === run.runId,
  );

  if (!profile) {
    return (
      <Card>
        <CardTitle>Research is locked behind a profile</CardTitle>
        <CardHint className="mt-2">Confirm the buyer and offer first.</CardHint>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
      <Card>
        <CardTitle>Attest a public source</CardTitle>
        <CardHint className="mt-2">
          You must open the URL. Killgate will not treat an AI summary as evidence.
          Need 3 verified sources, 2 domains, plus problem and current-alternative themes.
        </CardHint>
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            addSource(id, { url, title, theme, evidenceLevel: 1 });
            setUrl("");
            setTitle("");
          }}
        >
          <Field label="URL">
            <Input
              required
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://"
            />
          </Field>
          <Field label="Title as published">
            <Input required value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Query theme">
            <NativeSelect value={theme} onChange={(e) => setTheme(e.target.value)}>
              <option value="problem">Problem / pain</option>
              <option value="current_alternative">Current alternative</option>
              <option value="workaround">Workaround</option>
              <option value="spending">Spending / budget</option>
              <option value="contradiction">Contradiction</option>
            </NativeSelect>
          </Field>
          <Button type="submit">Add verified source</Button>
        </form>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => completeResearch(id, false)}>
            Close research run
          </Button>
          <Button variant="ghost" onClick={() => completeResearch(id, true)}>
            Mark contradicted
          </Button>
        </div>
      </Card>
      <Card>
        <CardTitle>Ledger</CardTitle>
        <p className="mt-2 font-mono text-xs uppercase tracking-[0.14em] text-muted">
          {run?.status ?? "no closed run"} · {run?.state ?? "idle"}
        </p>
        {sources.length === 0 ? (
          <p className="mt-4 text-sm text-muted">No sources yet.</p>
        ) : (
          <ul className="mt-4 grid gap-3">
            {sources.map((source) => (
              <li key={source.sourceId} className="rounded-md border border-border p-3">
                <p className="text-sm">{source.title || source.sourceUrl}</p>
                <p className="mt-1 font-mono text-[11px] text-muted">
                  {source.domain} · {source.queryTheme} · L{source.evidenceLevel} ·{" "}
                  {source.verificationStatus}
                </p>
                {source.verificationStatus === "VERIFIED" ? (
                  <Button
                    className="mt-2"
                    size="sm"
                    variant="ghost"
                    onClick={() => rejectSource(id, source.sourceId)}
                  >
                    Reject
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function BuyersPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const addBuyer = useKillgate((s) => s.addBuyer);
  const voidBuyer = useKillgate((s) => s.voidBuyer);
  const profile = activeIdeaProfile(venture);
  const [voidReason, setVoidReason] = useState("");

  if (!profile) {
    return (
      <Card>
        <CardTitle>Buyer records need a locked profile</CardTitle>
      </Card>
    );
  }

  const records = [...venture.buyerValidationRecords]
    .filter((row) => row.ideaProfileId === profile.profileId)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  return (
    <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
      <BuyerForm
        onSubmit={(payload) => {
          addBuyer(id, payload);
        }}
      />
      <Card>
        <CardTitle>Unique buyers</CardTitle>
        <CardHint className="mt-2">
          Duplicates collapse to the latest record. Voiding keeps the original in the audit
          trail and removes it from gate math.
        </CardHint>
        {records.length === 0 ? (
          <p className="mt-4 text-sm text-muted">No interviews recorded.</p>
        ) : (
          <ul className="mt-4 grid gap-3">
            {records.map((record) => (
              <li
                key={record.recordId}
                className={cn(
                  "rounded-md border border-border p-3",
                  record.voidedAt && "opacity-50",
                )}
              >
                <p className="text-sm font-medium">{record.buyerIdentifier}</p>
                <p className="mt-1 text-xs text-muted">
                  {record.painStrength} pain · {record.priorityStatus}
                  {record.pricePositive ? " · price-positive" : ""}
                  {record.voidedAt ? " · voided" : ""}
                </p>
                <p className="mt-2 text-sm text-muted">{record.recentRealExample}</p>
                {!record.voidedAt ? (
                  <form
                    className="mt-3 flex gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      voidBuyer(id, record.recordId, voidReason);
                      setVoidReason("");
                    }}
                  >
                    <Input
                      required
                      value={voidReason}
                      onChange={(e) => setVoidReason(e.target.value)}
                      placeholder="Correction reason"
                    />
                    <Button variant="ghost" size="sm" type="submit">
                      Void
                    </Button>
                  </form>
                ) : (
                  <p className="mt-2 text-xs text-muted">{record.voidReason}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function BuyerForm({ onSubmit }: { onSubmit: (payload: BuyerDraft) => void }) {
  const [buyerIdentifier, setBuyerIdentifier] = useState("");
  const [buyerRole, setBuyerRole] = useState("");
  const [qualificationBasis, setQualificationBasis] = useState("");
  const [recentRealExample, setRecentRealExample] = useState("");
  const [hasCurrentWorkaround, setHasCurrentWorkaround] = useState(true);
  const [currentWorkaround, setCurrentWorkaround] = useState("");
  const [painStrength, setPainStrength] = useState<PainStrength>("MODERATE");
  const [priorityStatus, setPriorityStatus] = useState<PriorityStatus>("UNKNOWN");
  const [pilotPriceTested, setPilotPriceTested] = useState("0");
  const [priceResponse, setPriceResponse] = useState("");
  const [pricePositive, setPricePositive] = useState(false);
  const [commitmentType, setCommitmentType] = useState<CommitmentType>("NONE");
  const [commitmentDetail, setCommitmentDetail] = useState("");
  const [commitmentDate, setCommitmentDate] = useState("");
  const [commitmentReference, setCommitmentReference] = useState("");
  const [paymentAmount, setPaymentAmount] = useState("0");
  const [paymentReference, setPaymentReference] = useState("");
  const [objectionOrNoReason, setObjectionOrNoReason] = useState("");

  return (
    <Card>
      <CardTitle>Record a buyer</CardTitle>
      <form
        className="mt-5 grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit({
            buyerIdentifier,
            buyerRole,
            qualificationBasis,
            recentRealExample,
            hasCurrentWorkaround,
            currentWorkaround: currentWorkaround || "None stated",
            painStrength,
            priorityStatus,
            pilotPriceTested: Number(pilotPriceTested) || 0,
            priceResponse,
            pricePositive,
            commitmentType,
            commitmentDetail,
            commitmentDate: commitmentDate ? new Date(commitmentDate).toISOString() : null,
            commitmentReference,
            paymentAmount: Number(paymentAmount) || 0,
            paymentReference,
            objectionOrNoReason,
          });
          setBuyerIdentifier("");
          setRecentRealExample("");
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Buyer identifier">
            <Input
              required
              value={buyerIdentifier}
              onChange={(e) => setBuyerIdentifier(e.target.value)}
              placeholder="Shop owner in Selma"
            />
          </Field>
          <Field label="Role">
            <Input
              required
              value={buyerRole}
              onChange={(e) => setBuyerRole(e.target.value)}
              placeholder="Owner-operator"
            />
          </Field>
        </div>
        <Field label="Why they are qualified">
          <Input
            required
            value={qualificationBasis}
            onChange={(e) => setQualificationBasis(e.target.value)}
          />
        </Field>
        <Field label="Recent real example">
          <Textarea
            required
            value={recentRealExample}
            onChange={(e) => setRecentRealExample(e.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Has workaround">
            <NativeSelect
              value={hasCurrentWorkaround ? "yes" : "no"}
              onChange={(e) => setHasCurrentWorkaround(e.target.value === "yes")}
            >
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </NativeSelect>
          </Field>
          <Field label="Workaround">
            <Input
              required
              value={currentWorkaround}
              onChange={(e) => setCurrentWorkaround(e.target.value)}
            />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Pain">
            <NativeSelect
              value={painStrength}
              onChange={(e) => setPainStrength(e.target.value as PainStrength)}
            >
              <option value="NONE">None</option>
              <option value="WEAK">Weak</option>
              <option value="MODERATE">Moderate</option>
              <option value="STRONG">Strong</option>
            </NativeSelect>
          </Field>
          <Field label="Priority">
            <NativeSelect
              value={priorityStatus}
              onChange={(e) => setPriorityStatus(e.target.value as PriorityStatus)}
            >
              <option value="UNKNOWN">Unknown</option>
              <option value="PRIORITY">Priority</option>
              <option value="NOT_NOW">Not now</option>
              <option value="NO_PRIORITY">No priority</option>
            </NativeSelect>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Price tested">
            <Input
              type="number"
              min={0}
              step="0.01"
              value={pilotPriceTested}
              onChange={(e) => setPilotPriceTested(e.target.value)}
            />
          </Field>
          <Field label="Price-positive">
            <NativeSelect
              value={pricePositive ? "yes" : "no"}
              onChange={(e) => setPricePositive(e.target.value === "yes")}
            >
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </NativeSelect>
          </Field>
        </div>
        <Field label="Price response">
          <Input value={priceResponse} onChange={(e) => setPriceResponse(e.target.value)} />
        </Field>
        <Field label="Commitment">
          <NativeSelect
            value={commitmentType}
            onChange={(e) => setCommitmentType(e.target.value as CommitmentType)}
          >
            <option value="NONE">None</option>
            <option value="DATED_PILOT">Dated pilot</option>
            <option value="SIGNED_INTENT">Signed intent</option>
            <option value="WORKFLOW_OR_DATA_ACCESS">Workflow / data access</option>
            <option value="NAMED_IMPLEMENTATION_STEP">Named implementation step</option>
            <option value="PURCHASE">Purchase</option>
          </NativeSelect>
        </Field>
        <Field label="Commitment detail">
          <Input
            value={commitmentDetail}
            onChange={(e) => setCommitmentDetail(e.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Commitment date">
            <Input
              type="date"
              value={commitmentDate}
              onChange={(e) => setCommitmentDate(e.target.value)}
            />
          </Field>
          <Field label="Commitment reference">
            <Input
              value={commitmentReference}
              onChange={(e) => setCommitmentReference(e.target.value)}
            />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Payment amount">
            <Input
              type="number"
              min={0}
              step="0.01"
              value={paymentAmount}
              onChange={(e) => setPaymentAmount(e.target.value)}
            />
          </Field>
          <Field label="Payment reference">
            <Input
              value={paymentReference}
              onChange={(e) => setPaymentReference(e.target.value)}
              placeholder="invoice-0001"
            />
          </Field>
        </div>
        <Field label="Objection / no-priority reason">
          <Input
            value={objectionOrNoReason}
            onChange={(e) => setObjectionOrNoReason(e.target.value)}
          />
        </Field>
        <Button type="submit">Add buyer record</Button>
      </form>
    </Card>
  );
}

function BuildPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const setMvp = useKillgate((s) => s.setMvp);
  const advanceToBuild = useKillgate((s) => s.advanceToBuild);
  const addTrial = useKillgate((s) => s.addTrial);
  const voidTrial = useKillgate((s) => s.voidTrial);
  const [artifact, setArtifact] = useState(venture.mvpReadiness?.artifactReference ?? "");
  const [outcome, setOutcome] = useState(venture.mvpReadiness?.coreOutcome ?? "");
  const [participant, setParticipant] = useState("");
  const [basis, setBasis] = useState("");
  const [detail, setDetail] = useState("");
  const [success, setSuccess] = useState(false);
  const [commitmentType, setCommitmentType] = useState<CommitmentType>("NONE");
  const [commitmentDetail, setCommitmentDetail] = useState("");
  const [commitmentDate, setCommitmentDate] = useState("");
  const [voidReason, setVoidReason] = useState("");
  const evaluation = useMemo(() => evaluationFor(venture), [venture]);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle>Testable MVP</CardTitle>
        <CardHint className="mt-2">
          GO BUILD permits a smallest testable artifact. GO SELL is evaluated only after
          you advance into build.
        </CardHint>
        {evaluation.recommendation === "GO_BUILD" && venture.phase === "validation" ? (
          <Button className="mt-4" variant="go" onClick={() => advanceToBuild(id)}>
            Advance to build
          </Button>
        ) : null}
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setMvp(id, { artifactReference: artifact, coreOutcome: outcome });
          }}
        >
          <Field label="Artifact reference">
            <Input
              required
              value={artifact}
              onChange={(e) => setArtifact(e.target.value)}
              placeholder="URL, build number, or repo"
            />
          </Field>
          <Field label="Observable core outcome">
            <Textarea required value={outcome} onChange={(e) => setOutcome(e.target.value)} />
          </Field>
          <Button type="submit">Record MVP</Button>
        </form>
      </Card>
      <Card>
        <CardTitle>Hands-on trial</CardTitle>
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            addTrial(id, {
              participantIdentifier: participant,
              qualificationBasis: basis,
              handsOn: true,
              coreOutcomeAttempted: true,
              coreOutcomeSucceeded: success,
              outcomeDetail: detail,
              commitmentType,
              commitmentDetail,
              commitmentDate: commitmentDate ? new Date(commitmentDate).toISOString() : null,
              commitmentReference: "",
              paymentAmount: 0,
              paymentReference: "",
            });
            setParticipant("");
            setDetail("");
          }}
        >
          <Field label="Participant">
            <Input
              required
              value={participant}
              onChange={(e) => setParticipant(e.target.value)}
            />
          </Field>
          <Field label="Qualification">
            <Input required value={basis} onChange={(e) => setBasis(e.target.value)} />
          </Field>
          <Field label="Outcome detail">
            <Textarea required value={detail} onChange={(e) => setDetail(e.target.value)} />
          </Field>
          <Field label="Core outcome succeeded">
            <NativeSelect
              value={success ? "yes" : "no"}
              onChange={(e) => setSuccess(e.target.value === "yes")}
            >
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </NativeSelect>
          </Field>
          <Field label="Purchase or pilot commitment">
            <NativeSelect
              value={commitmentType}
              onChange={(e) => setCommitmentType(e.target.value as CommitmentType)}
            >
              <option value="NONE">None</option>
              <option value="DATED_PILOT">Dated pilot</option>
              <option value="SIGNED_INTENT">Signed intent</option>
              <option value="PURCHASE">Purchase</option>
            </NativeSelect>
          </Field>
          <Field label="Commitment detail">
            <Input
              value={commitmentDetail}
              onChange={(e) => setCommitmentDetail(e.target.value)}
            />
          </Field>
          <Field label="Commitment date">
            <Input
              type="date"
              value={commitmentDate}
              onChange={(e) => setCommitmentDate(e.target.value)}
            />
          </Field>
          <Button type="submit">Add trial</Button>
        </form>
        <Separator className="my-4" />
        <ul className="grid gap-2">
          {venture.productTrialRecords.map((trial) => (
            <li key={trial.trialId} className="text-sm">
              <span className={trial.voidedAt ? "text-muted line-through" : ""}>
                {trial.participantIdentifier}
              </span>
              {trial.coreOutcomeSucceeded ? " · succeeded" : " · failed"}
              {!trial.voidedAt ? (
                <form
                  className="mt-2 flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    voidTrial(id, trial.trialId, voidReason);
                    setVoidReason("");
                  }}
                >
                  <Input
                    required
                    value={voidReason}
                    onChange={(e) => setVoidReason(e.target.value)}
                    placeholder="Correction reason"
                  />
                  <Button size="sm" variant="ghost" type="submit">
                    Void
                  </Button>
                </form>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function RiskPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const addConstraint = useKillgate((s) => s.addConstraint);
  const confirmConstraint = useKillgate((s) => s.confirmConstraint);
  const [type, setType] = useState<FatalConstraintType>("LEGAL");
  const [description, setDescription] = useState("");
  const [sourceId, setSourceId] = useState(venture.sourceEvidence[0]?.sourceId ?? "");

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle>Fatal constraint</CardTitle>
        <CardHint className="mt-2">
          KILL from a constraint requires a verified non-AI source and your explicit
          confirmation. AI-only sources (level 0) never count.
        </CardHint>
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!sourceId) return;
            addConstraint(id, {
              constraintType: type,
              description,
              sourceEvidenceIds: [sourceId],
              independentlyVerified: true,
            });
            setDescription("");
          }}
        >
          <Field label="Type">
            <NativeSelect
              value={type}
              onChange={(e) => setType(e.target.value as FatalConstraintType)}
            >
              <option value="LEGAL">Legal</option>
              <option value="TECHNICAL">Technical</option>
              <option value="TRUST">Trust</option>
              <option value="ECONOMIC">Economic</option>
            </NativeSelect>
          </Field>
          <Field label="Linked source">
            <NativeSelect value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">Select a verified source</option>
              {venture.sourceEvidence.map((source) => (
                <option key={source.sourceId} value={source.sourceId}>
                  {source.domain} · {source.title || source.sourceUrl}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Description">
            <Textarea
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Button type="submit">Record constraint</Button>
        </form>
      </Card>
      <Card>
        <CardTitle>Pending confirmation</CardTitle>
        {venture.fatalConstraints.length === 0 ? (
          <p className="mt-4 text-sm text-muted">None recorded.</p>
        ) : (
          <ul className="mt-4 grid gap-3">
            {venture.fatalConstraints.map((constraint) => (
              <li key={constraint.constraintId} className="rounded-md border border-border p-3">
                <p className="text-sm">
                  {constraint.constraintType} · {constraint.description}
                </p>
                {constraint.ownerConfirmedAt ? (
                  <p className="mt-2 font-mono text-xs uppercase tracking-[0.14em] text-kill">
                    Owner confirmed
                  </p>
                ) : (
                  <Button
                    className="mt-3"
                    variant="kill"
                    size="sm"
                    onClick={() => confirmConstraint(id, constraint.constraintId)}
                  >
                    Confirm as owner
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function LogPanel({ id }: { id: string }) {
  const venture = useKillgate((s) => s.ventures.find((row) => row.id === id)!);
  const log = [...venture.recommendationLog].reverse();
  return (
    <Card>
      <CardTitle>Recommendation log</CardTitle>
      <CardHint className="mt-2">Append-only. Voided evidence stays visible here.</CardHint>
      {log.length === 0 ? (
        <p className="mt-4 text-sm text-muted">No evaluations recorded yet.</p>
      ) : (
        <ol className="mt-5 grid gap-4">
          {log.map((row) => (
            <li key={row.recommendationId} className="grid gap-2 border-l-2 border-border pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <GateBadge recommendation={row.recommendation} />
                <span className="font-mono text-[11px] text-muted">
                  {new Date(row.createdAt).toLocaleString()}
                </span>
              </div>
              <p className="text-sm">{row.nextAction.instruction}</p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
