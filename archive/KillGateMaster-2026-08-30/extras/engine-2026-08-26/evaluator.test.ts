import assert from "node:assert/strict";
import { test } from "node:test";
import { evaluateAdaptiveGate } from "./evaluator.ts";
import { confirmIdeaProfile, createIdeaProfile } from "./profile.ts";
import { sha256Hex } from "./sha256.ts";
import type {
  BillingCadence,
  BuyerValidationRecord,
  IdeaProfile,
  ProductTrialRecord,
  SalesMotion,
  SystemState,
  ValidationProfile,
} from "./types";

const NOW = "2026-08-25T12:00:00.000Z";

function emptyState(hypothesis = "idea"): SystemState {
  return {
    id: "v-test",
    name: hypothesis,
    hypothesis,
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
    gateRecommendation: null,
    recommendationLog: [],
    nextActions: [],
    ownerStoppedAt: null,
    archivedAt: null,
    validationContract: null,
    createdAt: NOW,
    lastUpdated: NOW,
  };
}

function profile(opts?: {
  price?: number;
  cadence?: BillingCadence;
  motion?: SalesMotion;
  salesCallRequired?: boolean;
}): IdeaProfile {
  return createIdeaProfile({
    buyerType: "Independent software founder",
    salesMotion: opts?.motion ?? "SELF_SERVE",
    salesCallRequired: opts?.salesCallRequired ?? false,
    targetPrice: opts?.price ?? 100,
    billingCadence: opts?.cadence ?? "MONTHLY",
    problem: "Founders build before validating demand.",
    proposedOffer: "A deterministic validation workflow.",
    createdAt: NOW,
  });
}

function stateWithProfile(ideaProfile: IdeaProfile): SystemState {
  const state = emptyState("Validation workflow");
  state.ideaProfiles = [ideaProfile];
  state.activeIdeaProfileId = ideaProfile.profileId;
  return state;
}

function addQualifiedResearch(state: SystemState, evidenceLevel: 0 | 1 | 2 = 1) {
  const ideaProfile = state.ideaProfiles[0];
  const runId = "run-1";
  state.researchRuns.push({
    runId,
    ideaProfileId: ideaProfile.profileId,
    state: "SUCCEEDED",
    status: "QUALIFIED",
    queryThemes: ["problem", "current_alternative"],
    provider: "ledger",
    failureCode: "",
    failureMessage: "",
    startedAt: NOW,
    completedAt: "2026-08-25T12:01:00.000Z",
    createdAt: NOW,
  });
  state.sourceEvidence.push(
    {
      sourceId: "s1",
      researchRunId: runId,
      sourceUrl: "https://one.example/problem",
      title: "Problem",
      domain: "one.example",
      queryTheme: "problem",
      verificationStatus: "VERIFIED",
      evidenceLevel,
      claimMappings: [],
      accessedAt: NOW,
    },
    {
      sourceId: "s2",
      researchRunId: runId,
      sourceUrl: "https://two.example/alternative",
      title: "Alt",
      domain: "two.example",
      queryTheme: "current_alternative",
      verificationStatus: "VERIFIED",
      evidenceLevel,
      claimMappings: [],
      accessedAt: NOW,
    },
    {
      sourceId: "s3",
      researchRunId: runId,
      sourceUrl: "https://two.example/spending",
      title: "Spend",
      domain: "two.example",
      queryTheme: "spending",
      verificationStatus: "VERIFIED",
      evidenceLevel,
      claimMappings: [],
      accessedAt: NOW,
    },
  );
}

function buyer(
  ideaProfile: IdeaProfile,
  number: number,
  opts?: {
    strong?: boolean;
    pricePositive?: boolean;
    noPriority?: boolean;
    hasWorkaround?: boolean;
    commitment?: boolean;
    paid?: boolean;
    createdAt?: string;
  },
): BuyerValidationRecord {
  const createdAt = opts?.createdAt ?? NOW;
  return {
    recordId: `b-${number}`,
    ideaProfileId: ideaProfile.profileId,
    buyerIdentifier: `buyer-${number}`,
    buyerRole: "Founder",
    qualificationBasis: "Owns the product decision and budget.",
    recentRealExample: "Built a feature that customers did not adopt.",
    hasCurrentWorkaround: opts?.hasWorkaround ?? true,
    currentWorkaround: (opts?.hasWorkaround ?? true) ? "Spreadsheets" : "No current workaround",
    painStrength: opts?.strong ? "STRONG" : "WEAK",
    priorityStatus: opts?.noPriority ? "NO_PRIORITY" : "PRIORITY",
    pilotPriceTested: opts?.pricePositive ? 100 : 0,
    priceResponse: opts?.pricePositive
      ? "Accepted the concrete monthly price."
      : "Not price positive.",
    pricePositive: Boolean(opts?.pricePositive),
    commitmentType: opts?.commitment ? "DATED_PILOT" : "NONE",
    commitmentDetail: opts?.commitment ? "Pilot scheduled with implementation owner." : "",
    commitmentDate: opts?.commitment ? "2026-09-01T00:00:00.000Z" : null,
    commitmentReference: "",
    paymentAmount: opts?.paid ? 100 : 0,
    paymentReference: opts?.paid ? `invoice-${String(number).padStart(4, "0")}` : "",
    objectionOrNoReason: "none stated",
    createdAt,
    voidedAt: null,
    voidReason: "",
  };
}

function trial(
  ideaProfile: IdeaProfile,
  number: number,
  opts?: { success?: boolean; commitment?: boolean; paid?: boolean },
): ProductTrialRecord {
  return {
    trialId: `t-${number}`,
    ideaProfileId: ideaProfile.profileId,
    participantIdentifier: `trial-${number}`,
    qualificationBasis: "Qualified user of the target workflow.",
    handsOn: true,
    coreOutcomeAttempted: true,
    coreOutcomeSucceeded: Boolean(opts?.success),
    outcomeDetail: opts?.success
      ? "Completed the idea decision workflow."
      : "Could not complete the core workflow.",
    commitmentType: opts?.commitment ? "DATED_PILOT" : "NONE",
    commitmentDetail: opts?.commitment ? "Dated paid pilot is scheduled." : "",
    commitmentDate: opts?.commitment ? "2026-09-08T00:00:00.000Z" : null,
    commitmentReference: "",
    paymentAmount: opts?.paid ? 15 : 0,
    paymentReference: opts?.paid ? `trial-payment-${String(number).padStart(4, "0")}` : "",
    createdAt: `2026-08-25T12:${String(number).padStart(2, "0")}:00.000Z`,
    voidedAt: null,
    voidReason: "",
  };
}

test("sha256 known vector", () => {
  assert.equal(
    sha256Hex("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

const profileCases: Array<{
  price: number;
  cadence: BillingCadence;
  motion: SalesMotion;
  call: boolean;
  expected: ValidationProfile;
}> = [
  { price: 99.99, cadence: "MONTHLY", motion: "SELF_SERVE", call: false, expected: "SELF_SERVE_LOW_PRICE" },
  { price: 100, cadence: "MONTHLY", motion: "SELF_SERVE", call: false, expected: "SALES_ASSISTED_HIGH_PRICE" },
  { price: 1199, cadence: "ANNUAL", motion: "SELF_SERVE", call: false, expected: "SELF_SERVE_LOW_PRICE" },
  { price: 1200, cadence: "ANNUAL", motion: "SELF_SERVE", call: false, expected: "SALES_ASSISTED_HIGH_PRICE" },
  { price: 499.99, cadence: "ONE_TIME", motion: "SELF_SERVE", call: false, expected: "SELF_SERVE_LOW_PRICE" },
  { price: 500, cadence: "ONE_TIME", motion: "SELF_SERVE", call: false, expected: "SALES_ASSISTED_HIGH_PRICE" },
  { price: 10, cadence: "MONTHLY", motion: "SALES_ASSISTED", call: false, expected: "SALES_ASSISTED_HIGH_PRICE" },
  { price: 10, cadence: "MONTHLY", motion: "SELF_SERVE", call: true, expected: "SALES_ASSISTED_HIGH_PRICE" },
];

for (const row of profileCases) {
  test(`system selects ${row.expected} at ${row.price} ${row.cadence}`, () => {
    assert.equal(
      profile({
        price: row.price,
        cadence: row.cadence,
        motion: row.motion,
        salesCallRequired: row.call,
      }).systemProfile,
      row.expected,
    );
  });
}

test("client cannot supply a lower validation profile", () => {
  const ideaProfile = createIdeaProfile({
    buyerType: "Enterprise buyer",
    salesMotion: "SALES_ASSISTED",
    salesCallRequired: false,
    targetPrice: 5000,
    billingCadence: "ANNUAL",
    problem: "Manual compliance review",
    proposedOffer: "Automated review",
  });
  assert.equal(ideaProfile.systemProfile, "SALES_ASSISTED_HIGH_PRICE");
});

test("equivalent profiles share a 64-char fingerprint", () => {
  const a = createIdeaProfile({
    buyerType: "Founder",
    salesMotion: "SELF_SERVE",
    salesCallRequired: false,
    targetPrice: 14.99,
    billingCadence: "MONTHLY",
    problem: "  Hard   problem ",
    proposedOffer: "Focused offer",
  });
  const b = createIdeaProfile({
    buyerType: "founder",
    salesMotion: "SELF_SERVE",
    salesCallRequired: false,
    targetPrice: 14.99,
    billingCadence: "MONTHLY",
    problem: "hard problem",
    proposedOffer: "focused offer",
  });
  assert.equal(a.contractFingerprint.length, 64);
  assert.equal(a.contractFingerprint, b.contractFingerprint);
});

test("missing profile continues with one concrete action", () => {
  const result = evaluateAdaptiveGate(emptyState());
  assert.equal(result.recommendation, "CONTINUE");
  assert.equal(result.nextAction.actionType, "COMPLETE_IDEA_PROFILE");
});

test("material profile change creates a fresh pivot contract without erasing history", () => {
  const original = profile({ price: 14.99 });
  const state = emptyState();
  const first = confirmIdeaProfile(state, original, NOW);
  assert.equal(first.changed, true);
  assert.equal(state.validationContract?.ideaProfileId, first.profile.profileId);
  assert.equal(state.validationContract?.contractVersion, "2.0");

  state.buyerValidationRecords.push(buyer(first.profile, 1, { strong: true, pricePositive: true }));
  const pivot = confirmIdeaProfile(
    state,
    profile({ price: 149 }),
    "2026-08-26T12:00:00.000Z",
  );
  assert.equal(pivot.changed, true);
  assert.equal(original.supersededAt, "2026-08-26T12:00:00.000Z");
  assert.equal(pivot.profile.version, 2);
  assert.equal(state.gateRecommendation, "PIVOT");
  assert.equal(state.buyerValidationRecords[0].ideaProfileId, original.profileId);
  assert.equal(evaluateAdaptiveGate(state).evidenceCompleteness.qualified_buyer_count, 0);
});

test("reconfirming same normalized profile is idempotent", () => {
  const state = emptyState();
  const first = confirmIdeaProfile(state, profile({ price: 14.99 }), NOW);
  const equivalent = createIdeaProfile({
    buyerType: "independent software founder",
    salesMotion: "SELF_SERVE",
    salesCallRequired: false,
    targetPrice: 14.99,
    billingCadence: "MONTHLY",
    problem: "founders build before validating demand.",
    proposedOffer: "a deterministic validation workflow.",
  });
  const again = confirmIdeaProfile(state, equivalent, "2026-08-26T12:00:00.000Z");
  assert.equal(again.changed, false);
  assert.equal(again.profile.profileId, first.profile.profileId);
  assert.equal(state.ideaProfiles.length, 1);
  assert.equal(state.nextActions.length, 1);
});

test("legacy accepted GO maps to GO_BUILD without rewriting legacy field", () => {
  const state = emptyState("legacy");
  state.validationDecision = "go";
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "GO_BUILD");
  assert.equal(state.validationDecision, "go");
  assert.equal(result.evidenceCompleteness.legacy_migration, true);
});

test("AI level-zero sources never qualify research or kill", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state, 0);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { noPriority: true, hasWorkaround: false }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "CONTINUE");
  assert.equal(result.evidenceCompleteness.verified_source_count, 0);
});

test("unavailable research can never kill even with a terrible direct sample", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  state.researchRuns.push({
    runId: "run-fail",
    ideaProfileId: ideaProfile.profileId,
    state: "FAILED",
    status: "UNAVAILABLE",
    queryThemes: [],
    provider: "ledger",
    failureCode: "provider_outage",
    failureMessage: "",
    startedAt: NOW,
    completedAt: NOW,
    createdAt: NOW,
  });
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { noPriority: true, hasWorkaround: false }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "CONTINUE");
  assert.match(String(result.blockers[0]), /never produce KILL/);
});

test("sales-assisted GO BUILD boundary requires no buyer payments", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { strong: i + 1 <= 3, pricePositive: i + 1 <= 3 }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "GO_BUILD");
  assert.equal(result.evidenceCompleteness.qualified_buyer_count, 6);
  assert.equal(result.evidenceCompleteness.verified_payment_count, 0);
});

test("sales-assisted GO BUILD accepts two meaningful commitments", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { strong: i + 1 <= 3, commitment: i + 1 <= 2 }),
  );
  assert.equal(evaluateAdaptiveGate(state).recommendation, "GO_BUILD");
});

test("self-serve combines unique price-positive and commitment buyers", () => {
  const ideaProfile = profile({ price: 14.99 });
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 12 }, (_, i) =>
    buyer(ideaProfile, i + 1, {
      strong: i + 1 <= 5,
      pricePositive: i + 1 <= 3,
      commitment: i + 1 === 4 || i + 1 === 5,
    }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "GO_BUILD");
  assert.equal(result.evidenceCompleteness.combined_commercial_signal_count, 5);
});

test("duplicate buyer and voided records cannot inflate GO BUILD", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  const records = Array.from({ length: 5 }, (_, i) =>
    buyer(ideaProfile, i + 1, { strong: i + 1 <= 3, pricePositive: i + 1 <= 3 }),
  );
  const duplicate = buyer(ideaProfile, 1, {
    strong: true,
    pricePositive: true,
    createdAt: "2026-08-25T13:00:00.000Z",
  });
  duplicate.buyerIdentifier = "  BUYER-1 ";
  const voided = buyer(ideaProfile, 6, { strong: true, pricePositive: true });
  voided.voidedAt = "2026-08-25T14:00:00.000Z";
  voided.voidReason = "Wrong person recorded";
  state.buyerValidationRecords = [...records, duplicate, voided];
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "CONTINUE");
  assert.equal(result.evidenceCompleteness.qualified_buyer_count, 5);
});

test("required low-pain majority sample kills", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, {
      noPriority: i + 1 <= 4,
      hasWorkaround: i + 1 > 4,
    }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "KILL");
  assert.equal(result.evidenceCompleteness.strict_majority_negative_required, 4);
});

test("exactly half negative is not a majority and produces pivot", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { noPriority: i + 1 <= 3 }),
  );
  assert.equal(evaluateAdaptiveGate(state).recommendation, "PIVOT");
});

test("verified payment prevents automatic KILL", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, {
      noPriority: true,
      hasWorkaround: false,
      paid: i + 1 === 1,
    }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "PIVOT");
  assert.ok(result.blockers.some((row) => row.includes("prevents an automatic KILL")));
});

test("fatal constraint requires non-AI source and owner confirmation", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  const source = state.sourceEvidence[0];
  state.fatalConstraints.push({
    constraintId: "c1",
    ideaProfileId: ideaProfile.profileId,
    constraintType: "LEGAL",
    description: "Verified law prohibits the proposed workflow.",
    sourceEvidenceIds: [source.sourceId],
    independentlyVerified: true,
    ownerConfirmedAt: null,
    createdAt: NOW,
    voidedAt: null,
    voidReason: "",
  });
  assert.equal(evaluateAdaptiveGate(state).recommendation, "CONTINUE");
  state.fatalConstraints[0].ownerConfirmedAt = NOW;
  assert.equal(evaluateAdaptiveGate(state).recommendation, "KILL");
  source.evidenceLevel = 0;
  assert.notEqual(evaluateAdaptiveGate(state).recommendation, "KILL");
});

test("owner stop is never recorded as evidence-backed KILL", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  state.ownerStoppedAt = NOW;
  assert.equal(evaluateAdaptiveGate(state).recommendation, "OWNER_STOPPED");
});

test("sales-assisted GO SELL boundary and scale signal are separate", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, {
      strong: i + 1 <= 3,
      pricePositive: i + 1 <= 3,
      paid: i + 1 <= 2,
    }),
  );
  state.phase = "build";
  state.mvpReadiness = {
    ideaProfileId: ideaProfile.profileId,
    testable: true,
    artifactReference: "https://app.example/mvp",
    coreOutcome: "Founder reaches an evidence-backed decision.",
    confirmedAt: NOW,
  };
  state.productTrialRecords = Array.from({ length: 3 }, (_, i) =>
    trial(ideaProfile, i + 1, { success: i + 1 <= 2, commitment: i + 1 <= 2 }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "GO_SELL");
  assert.equal(result.scaleReady, true);
});

test("self-serve GO SELL boundary", () => {
  const ideaProfile = profile({ price: 14.99 });
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 12 }, (_, i) =>
    buyer(ideaProfile, i + 1, { strong: i + 1 <= 5, pricePositive: i + 1 <= 5 }),
  );
  state.phase = "build";
  state.mvpReadiness = {
    ideaProfileId: ideaProfile.profileId,
    testable: true,
    artifactReference: "build-42",
    coreOutcome: "Complete validation plan",
    confirmedAt: NOW,
  };
  state.productTrialRecords = Array.from({ length: 8 }, (_, i) =>
    trial(ideaProfile, i + 1, { success: i + 1 <= 5, commitment: i + 1 <= 3 }),
  );
  const result = evaluateAdaptiveGate(state);
  assert.equal(result.recommendation, "GO_SELL");
  assert.equal(result.scaleReady, false);
});

test("completed trial sample with failed outcomes pivots instead of killing", () => {
  const ideaProfile = profile();
  const state = stateWithProfile(ideaProfile);
  addQualifiedResearch(state);
  state.buyerValidationRecords = Array.from({ length: 6 }, (_, i) =>
    buyer(ideaProfile, i + 1, { strong: i + 1 <= 3, pricePositive: i + 1 <= 3 }),
  );
  state.phase = "build";
  state.mvpReadiness = {
    ideaProfileId: ideaProfile.profileId,
    testable: true,
    artifactReference: "mvp",
    coreOutcome: "Core outcome",
    confirmedAt: NOW,
  };
  state.productTrialRecords = Array.from({ length: 3 }, (_, i) => trial(ideaProfile, i + 1));
  assert.equal(evaluateAdaptiveGate(state).recommendation, "PIVOT");
});
