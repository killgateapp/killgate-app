import { create } from "zustand";
import { persist } from "zustand/middleware";
import { evaluateAdaptiveGate, activeIdeaProfile } from "./evaluator.ts";
import { confirmIdeaProfile, createIdeaProfile, type IdeaProfileDraft } from "./profile.ts";
import { domainFromUrl, newId, nowIso } from "./ids.ts";
import { canOpenLiveLock, canUnarchive, slotFullError, type SlotResult } from "./slots.ts";
import type {
  AdaptiveGateEvaluation,
  BuyerValidationRecord,
  FatalConstraint,
  ProductTrialRecord,
  SourceEvidence,
  SystemState,
} from "./types.ts";

const STORAGE_KEY = "killgate.adaptive.v1";

export function emptyVenture(hypothesis: string, name?: string): SystemState {
  const now = nowIso();
  const id = newId();
  return {
    id,
    name: name?.trim() || hypothesis.trim().slice(0, 72) || "Untitled idea",
    hypothesis: hypothesis.trim(),
    phase: "validation",
    validationDecision: null,
    researchPass: false,
    ideaProfiles: [],
    activeIdeaProfileId: null,
    researchRuns: [],
    sourceEvidence: [],
    buyerValidationRecords: [],
    mvpReadiness: null,
    productTrialRecords: [],
    fatalConstraints: [],
    gateRecommendation: "CONTINUE",
    recommendationLog: [],
    nextActions: [],
    ownerStoppedAt: null,
    archivedAt: null,
    validationContract: null,
    createdAt: now,
    lastUpdated: now,
  };
}

function applyGate(state: SystemState): SystemState {
  const evaluation = evaluateAdaptiveGate(state);
  state.gateRecommendation = evaluation.recommendation;
  const last = state.recommendationLog.at(-1);
  const changed =
    !last ||
    last.recommendation !== evaluation.recommendation ||
    last.nextAction.actionType !== evaluation.nextAction.actionType;
  if (changed) {
    state.recommendationLog.push({
      recommendationId: newId(),
      ideaProfileId: evaluation.nextAction.ideaProfileId,
      recommendation: evaluation.recommendation,
      evaluatorVersion: evaluation.evaluatorVersion,
      passedGates: evaluation.passedGates,
      blockers: evaluation.blockers,
      evidenceCompleteness: evaluation.evidenceCompleteness,
      nextAction: evaluation.nextAction,
      createdAt: nowIso(),
    });
  }
  state.lastUpdated = nowIso();
  return state;
}

function patch(
  ventures: SystemState[],
  id: string,
  fn: (state: SystemState) => void,
): SystemState[] {
  return ventures.map((venture) => {
    if (venture.id !== id) return venture;
    const next = structuredClone(venture);
    fn(next);
    return applyGate(next);
  });
}

type Store = {
  ventures: SystemState[];
  createVenture: (hypothesis: string) => string;
  removeVenture: (id: string) => void;
  archiveVenture: (id: string) => SlotResult;
  unarchiveVenture: (id: string) => SlotResult;
  lockProfile: (id: string, draft: IdeaProfileDraft) => SlotResult;
  startResearchRun: (id: string) => string | null;
  addSource: (
    id: string,
    input: {
      url: string;
      title: string;
      theme: string;
      evidenceLevel: 1 | 2;
    },
  ) => void;
  rejectSource: (id: string, sourceId: string) => void;
  completeResearch: (id: string, contradicted: boolean) => void;
  addBuyer: (id: string, record: Omit<BuyerValidationRecord, "recordId" | "ideaProfileId" | "createdAt" | "voidedAt" | "voidReason">) => void;
  voidBuyer: (id: string, recordId: string, reason: string) => void;
  setMvp: (
    id: string,
    input: { artifactReference: string; coreOutcome: string },
  ) => void;
  advanceToBuild: (id: string) => void;
  addTrial: (id: string, record: Omit<ProductTrialRecord, "trialId" | "ideaProfileId" | "createdAt" | "voidedAt" | "voidReason">) => void;
  voidTrial: (id: string, trialId: string, reason: string) => void;
  addConstraint: (
    id: string,
    input: Omit<FatalConstraint, "constraintId" | "ideaProfileId" | "createdAt" | "voidedAt" | "voidReason" | "ownerConfirmedAt">,
  ) => void;
  confirmConstraint: (id: string, constraintId: string) => void;
  ownerStop: (id: string) => void;
  resumeOwnerStop: (id: string) => void;
  loadSample: (kind: "empty" | "go-build") => SlotResult<{ id: string }>;
};

export const useKillgate = create<Store>()(
  persist(
    (set, get) => ({
      ventures: [],
      createVenture: (hypothesis) => {
        const venture = applyGate(emptyVenture(hypothesis));
        set({ ventures: [venture, ...get().ventures] });
        return venture.id;
      },
      removeVenture: (id) => {
        set({ ventures: get().ventures.filter((row) => row.id !== id) });
      },
      archiveVenture: (id) => {
        const current = get().ventures.find((row) => row.id === id);
        if (!current) return { ok: false, code: "NOT_FOUND", message: "Workspace not found." };
        set({
          ventures: get().ventures.map((row) =>
            row.id === id
              ? { ...row, archivedAt: row.archivedAt ?? nowIso(), lastUpdated: nowIso() }
              : row,
          ),
        });
        return { ok: true };
      },
      unarchiveVenture: (id) => {
        const current = get().ventures.find((row) => row.id === id);
        if (!current) return { ok: false, code: "NOT_FOUND", message: "Workspace not found." };
        if (!current.archivedAt) return { ok: true };
        if (!canUnarchive(get().ventures, id)) return slotFullError();
        set({
          ventures: get().ventures.map((row) =>
            row.id === id ? { ...row, archivedAt: null, lastUpdated: nowIso() } : row,
          ),
        });
        return { ok: true };
      },
      lockProfile: (id, draft) => {
        const current = get().ventures.find((row) => row.id === id);
        if (!current) return { ok: false, code: "NOT_FOUND", message: "Workspace not found." };
        if (current.archivedAt) {
          return {
            ok: false,
            code: "ARCHIVED",
            message: "Unarchive this workspace before changing the contract.",
          };
        }
        if (!canOpenLiveLock(get().ventures, id)) return slotFullError();
        set({
          ventures: patch(get().ventures, id, (state) => {
            const candidate = createIdeaProfile(draft);
            confirmIdeaProfile(state, candidate);
          }),
        });
        return { ok: true };
      },
      startResearchRun: (id) => {
        let runId: string | null = null;
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            runId = newId();
            const now = nowIso();
            state.researchRuns.push({
              runId,
              ideaProfileId: profile.profileId,
              state: "RUNNING",
              status: null,
              queryThemes: ["problem", "current_alternative"],
              provider: "owner_attested_ledger",
              failureCode: "",
              failureMessage: "",
              startedAt: now,
              completedAt: null,
              createdAt: now,
            });
          }),
        });
        return runId;
      },
      addSource: (id, input) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            let run = [...state.researchRuns]
              .reverse()
              .find(
                (row) =>
                  row.ideaProfileId === profile.profileId &&
                  (row.state === "RUNNING" || row.state === "PENDING"),
              );
            if (!run) {
              const now = nowIso();
              run = {
                runId: newId(),
                ideaProfileId: profile.profileId,
                state: "RUNNING",
                status: null,
                queryThemes: ["problem", "current_alternative"],
                provider: "owner_attested_ledger",
                failureCode: "",
                failureMessage: "",
                startedAt: now,
                completedAt: null,
                createdAt: now,
              };
              state.researchRuns.push(run);
            }
            const domain = domainFromUrl(input.url);
            if (!domain) return;
            const source: SourceEvidence = {
              sourceId: newId(),
              researchRunId: run.runId,
              sourceUrl: input.url.trim(),
              title: input.title.trim(),
              domain,
              queryTheme: input.theme.trim() || "general",
              verificationStatus: "VERIFIED",
              evidenceLevel: input.evidenceLevel,
              claimMappings: [],
              accessedAt: nowIso(),
            };
            state.sourceEvidence.push(source);
          }),
        });
      },
      rejectSource: (id: string, sourceId: string) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const source = state.sourceEvidence.find((row) => row.sourceId === sourceId);
            if (source) source.verificationStatus = "REJECTED";
          }),
        });
      },
      completeResearch: (id, contradicted) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            const run = [...state.researchRuns]
              .reverse()
              .find((row) => row.ideaProfileId === profile.profileId);
            if (!run) return;
            run.state = "SUCCEEDED";
            run.completedAt = nowIso();
            if (contradicted) {
              run.status = "CONTRADICTED";
              return;
            }
            const sources = state.sourceEvidence.filter(
              (source) =>
                source.researchRunId === run.runId &&
                source.verificationStatus === "VERIFIED" &&
                (source.evidenceLevel === 1 || source.evidenceLevel === 2),
            );
            const domains = new Set(sources.map((source) => source.domain.toLowerCase()));
            const themes = new Set(
              sources.map((source) => source.queryTheme.toLowerCase().replace(/-/g, "_")),
            );
            const hasProblem = [...themes].some((theme) =>
              ["problem", "pain", "problem_evidence"].includes(theme),
            );
            const hasAlternative = [...themes].some((theme) =>
              [
                "alternative",
                "alternatives",
                "current_alternative",
                "current_behavior",
                "workaround",
              ].includes(theme),
            );
            run.status =
              sources.length >= 3 && domains.size >= 2 && hasProblem && hasAlternative
                ? "QUALIFIED"
                : "INCOMPLETE";
          }),
        });
      },
      addBuyer: (id, record) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            const row: BuyerValidationRecord = {
              ...record,
              recordId: newId(),
              ideaProfileId: profile.profileId,
              createdAt: nowIso(),
              voidedAt: null,
              voidReason: "",
            };
            state.buyerValidationRecords.push(row);
          }),
        });
      },
      voidBuyer: (id, recordId, reason) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const row = state.buyerValidationRecords.find((item) => item.recordId === recordId);
            if (!row || !reason.trim()) return;
            row.voidedAt = nowIso();
            row.voidReason = reason.trim();
          }),
        });
      },
      setMvp: (id, input) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            state.mvpReadiness = {
              ideaProfileId: profile.profileId,
              testable: Boolean(input.artifactReference.trim() && input.coreOutcome.trim()),
              artifactReference: input.artifactReference.trim(),
              coreOutcome: input.coreOutcome.trim(),
              confirmedAt: nowIso(),
            };
          }),
        });
      },
      advanceToBuild: (id) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            if (state.gateRecommendation === "GO_BUILD") state.phase = "build";
          }),
        });
      },
      addTrial: (id, record) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            state.productTrialRecords.push({
              ...record,
              trialId: newId(),
              ideaProfileId: profile.profileId,
              createdAt: nowIso(),
              voidedAt: null,
              voidReason: "",
            });
          }),
        });
      },
      voidTrial: (id, trialId, reason) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const row = state.productTrialRecords.find((item) => item.trialId === trialId);
            if (!row || !reason.trim()) return;
            row.voidedAt = nowIso();
            row.voidReason = reason.trim();
          }),
        });
      },
      addConstraint: (id, input) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const profile = activeIdeaProfile(state);
            if (!profile) return;
            state.fatalConstraints.push({
              ...input,
              constraintId: newId(),
              ideaProfileId: profile.profileId,
              ownerConfirmedAt: null,
              createdAt: nowIso(),
              voidedAt: null,
              voidReason: "",
            });
          }),
        });
      },
      confirmConstraint: (id, constraintId) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            const row = state.fatalConstraints.find((item) => item.constraintId === constraintId);
            if (row) row.ownerConfirmedAt = nowIso();
          }),
        });
      },
      ownerStop: (id) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            state.ownerStoppedAt = nowIso();
          }),
        });
      },
      resumeOwnerStop: (id) => {
        set({
          ventures: patch(get().ventures, id, (state) => {
            state.ownerStoppedAt = null;
          }),
        });
      },
      loadSample: (kind) => {
        if (kind === "go-build" && !canOpenLiveLock(get().ventures)) {
          return slotFullError();
        }
        const venture =
          kind === "go-build" ? sampleGoBuild() : sampleEmptyRepairShop();
        set({ ventures: [venture, ...get().ventures] });
        return { ok: true, id: venture.id };
      },
    }),
    {
      name: STORAGE_KEY,
      version: 2,
      migrate: (persistedState) => {
        const state = (persistedState ?? { ventures: [] }) as { ventures?: SystemState[] };
        return {
          ventures: (state.ventures ?? []).map((venture) => ({
            ...venture,
            archivedAt: venture.archivedAt ?? null,
          })),
        };
      },
    },
  ),
);

export function evaluationFor(state: SystemState): AdaptiveGateEvaluation {
  return evaluateAdaptiveGate(state);
}

function sampleEmptyRepairShop(): SystemState {
  const state = applyGate(
    emptyVenture(
      "Independent auto repair shops miss customer calls while technicians are busy. I want to sell a simple call-capture assistant that qualifies the repair and books a callback.",
      "Call-capture for independent shops",
    ),
  );
  return state;
}

function sampleGoBuild(): SystemState {
  const state = emptyVenture(
    "Founders build products before they have evidence that anyone will pay. Killgate is a locked validation workflow.",
    "Killgate itself (GO BUILD sample)",
  );
  const candidate = createIdeaProfile({
    buyerType: "Independent software founder",
    salesMotion: "SALES_ASSISTED",
    salesCallRequired: true,
    targetPrice: 149,
    billingCadence: "MONTHLY",
    problem: "Founders waste months building products nobody will pay for.",
    proposedOffer: "A locked, deterministic validation gate with evidence records.",
  });
  confirmIdeaProfile(state, candidate);
  const profile = activeIdeaProfile(state)!;
  const runId = newId();
  const now = nowIso();
  state.researchRuns.push({
    runId,
    ideaProfileId: profile.profileId,
    state: "SUCCEEDED",
    status: "QUALIFIED",
    queryThemes: ["problem", "current_alternative"],
    provider: "owner_attested_ledger",
    failureCode: "",
    failureMessage: "",
    startedAt: now,
    completedAt: now,
    createdAt: now,
  });
  state.sourceEvidence.push(
    {
      sourceId: newId(),
      researchRunId: runId,
      sourceUrl: "https://www.cbinsights.com/research/startup-failure-reasons-top/",
      title: "The top reasons startups fail",
      domain: "cbinsights.com",
      queryTheme: "problem",
      verificationStatus: "VERIFIED",
      evidenceLevel: 1,
      claimMappings: [],
      accessedAt: now,
    },
    {
      sourceId: newId(),
      researchRunId: runId,
      sourceUrl: "https://leanstartup.co/",
      title: "Lean Startup methodology",
      domain: "leanstartup.co",
      queryTheme: "current_alternative",
      verificationStatus: "VERIFIED",
      evidenceLevel: 1,
      claimMappings: [],
      accessedAt: now,
    },
    {
      sourceId: newId(),
      researchRunId: runId,
      sourceUrl: "https://www.ycombinator.com/library/4D-yc-s-essential-startup-advice",
      title: "YC essential startup advice",
      domain: "ycombinator.com",
      queryTheme: "spending",
      verificationStatus: "VERIFIED",
      evidenceLevel: 2,
      claimMappings: [],
      accessedAt: now,
    },
  );
  for (let i = 1; i <= 6; i++) {
    state.buyerValidationRecords.push({
      recordId: newId(),
      ideaProfileId: profile.profileId,
      buyerIdentifier: `founder-${i}`,
      buyerRole: "Founder",
      qualificationBasis: "Owns product and budget decisions at a pre-seed company.",
      recentRealExample: "Shipped a feature last quarter that no customer adopted.",
      hasCurrentWorkaround: true,
      currentWorkaround: "Spreadsheets and Notion docs of interviews.",
      painStrength: i <= 3 ? "STRONG" : "MODERATE",
      priorityStatus: "PRIORITY",
      pilotPriceTested: i <= 3 ? 149 : 0,
      priceResponse: i <= 3 ? "Would pay $149/mo for a locked gate." : "Not asked.",
      pricePositive: i <= 3,
      commitmentType: "NONE",
      commitmentDetail: "",
      commitmentDate: null,
      commitmentReference: "",
      paymentAmount: 0,
      paymentReference: "",
      objectionOrNoReason: "Worried about interview volume.",
      createdAt: now,
      voidedAt: null,
      voidReason: "",
    });
  }
  return applyGate(state);
}
