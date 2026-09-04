import { identityKey, newId, nowIso } from "./ids.ts";
import {
  EVALUATOR_VERSION,
  THRESHOLDS,
  type AdaptiveGateEvaluation,
  type BuyerValidationRecord,
  type CommitmentType,
  type GateRecommendation,
  type GateThresholds,
  type IdeaProfile,
  type NextAction,
  type ProductTrialRecord,
  type ResearchRun,
  type ResearchStatus,
  type SourceEvidence,
  type SystemState,
  type ValidationProfile,
} from "./types.ts";

export function activeIdeaProfile(state: SystemState): IdeaProfile | null {
  if (!state.ideaProfiles.length) return null;
  if (state.activeIdeaProfileId) {
    return (
      state.ideaProfiles.find(
        (profile) =>
          profile.profileId === state.activeIdeaProfileId &&
          profile.supersededAt === null,
      ) ?? null
    );
  }
  const active = state.ideaProfiles.filter((profile) => profile.supersededAt === null);
  if (!active.length) return null;
  return active.reduce((best, profile) =>
    profile.version > best.version ? profile : best,
  );
}

function validReference(value: string): boolean {
  const reference = value.trim().replace(/\s+/g, " ");
  return (
    reference.length >= 5 &&
    !["cash", "paid", "yes", "none", "n/a", "receipt", "payment", "done"].includes(
      reference.toLowerCase(),
    )
  );
}

export function isVerifiedPayment(amount: number, reference: string): boolean {
  return amount > 0 && validReference(reference);
}

export function isPricePositive(record: BuyerValidationRecord): boolean {
  return Boolean(
    record.pricePositive && record.pilotPriceTested > 0 && record.priceResponse.trim(),
  );
}

export function isMeaningfulCommitment(
  commitmentType: CommitmentType,
  detail: string,
  commitmentDate: string | null,
  reference: string,
  paymentAmount: number,
  paymentReference: string,
): boolean {
  const detailPresent = Boolean(detail.trim());
  if (commitmentType === "DATED_PILOT") return detailPresent && commitmentDate !== null;
  if (commitmentType === "SIGNED_INTENT") return detailPresent && validReference(reference);
  if (commitmentType === "WORKFLOW_OR_DATA_ACCESS") {
    return detailPresent && validReference(reference);
  }
  if (commitmentType === "NAMED_IMPLEMENTATION_STEP") {
    return detailPresent && commitmentDate !== null;
  }
  if (commitmentType === "PURCHASE") {
    return isVerifiedPayment(paymentAmount, paymentReference);
  }
  return false;
}

function buyerCommitment(record: BuyerValidationRecord): boolean {
  return isMeaningfulCommitment(
    record.commitmentType,
    record.commitmentDetail,
    record.commitmentDate,
    record.commitmentReference,
    record.paymentAmount,
    record.paymentReference,
  );
}

function trialPurchaseCommitment(record: ProductTrialRecord): boolean {
  if (
    record.commitmentType !== "DATED_PILOT" &&
    record.commitmentType !== "SIGNED_INTENT" &&
    record.commitmentType !== "PURCHASE"
  ) {
    return false;
  }
  return isMeaningfulCommitment(
    record.commitmentType,
    record.commitmentDetail,
    record.commitmentDate,
    record.commitmentReference,
    record.paymentAmount,
    record.paymentReference,
  );
}

function latestByIdentity<T>(
  records: T[],
  identity: (row: T) => string,
  voidedAt: (row: T) => string | null,
  createdAt: (row: T) => string,
): Map<string, T> {
  const latest = new Map<string, T>();
  const ordered = [...records].sort((a, b) => createdAt(a).localeCompare(createdAt(b)));
  for (const record of ordered) {
    if (voidedAt(record) !== null) continue;
    const key = identityKey(identity(record));
    if (key) latest.set(key, record);
  }
  return latest;
}

function groupBuyers(
  records: BuyerValidationRecord[],
): Map<string, BuyerValidationRecord[]> {
  const groups = new Map<string, BuyerValidationRecord[]>();
  const ordered = [...records].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  for (const record of ordered) {
    if (record.voidedAt !== null) continue;
    const key = identityKey(record.buyerIdentifier);
    if (!key) continue;
    const list = groups.get(key) ?? [];
    list.push(record);
    groups.set(key, list);
  }
  return groups;
}

function currentResearchRun(
  state: SystemState,
  profile: IdeaProfile,
): ResearchRun | null {
  const matching = state.researchRuns.filter(
    (run) =>
      run.ideaProfileId === profile.profileId &&
      (run.state === "SUCCEEDED" || run.state === "FAILED"),
  );
  if (!matching.length) return null;
  return matching.reduce((best, run) =>
    run.createdAt > best.createdAt ? run : best,
  );
}

function verifiedSourcesForRun(state: SystemState, runId: string): SourceEvidence[] {
  return state.sourceEvidence.filter(
    (source) =>
      source.researchRunId === runId &&
      source.verificationStatus === "VERIFIED" &&
      (source.evidenceLevel === 1 || source.evidenceLevel === 2),
  );
}

function researchEvidence(
  state: SystemState,
  profile: IdeaProfile,
): {
  status: ResearchStatus | null;
  qualified: boolean;
  completeness: Record<string, unknown>;
} {
  const run = currentResearchRun(state, profile);
  if (!run) {
    if (state.researchPass) {
      return {
        status: "QUALIFIED",
        qualified: true,
        completeness: {
          research_status: "QUALIFIED",
          legacy_research_packet: true,
          verified_source_count: null,
          independent_domain_count: null,
        },
      };
    }
    return {
      status: null,
      qualified: false,
      completeness: {
        research_status: null,
        legacy_research_packet: false,
        verified_source_count: 0,
        independent_domain_count: 0,
      },
    };
  }

  const sources = verifiedSourcesForRun(state, run.runId);
  const domains = new Set(
    sources.map((source) => source.domain.trim().toLowerCase()).filter(Boolean),
  );
  const themes = new Set(
    sources.map((source) => source.queryTheme.trim().toLowerCase().replace(/-/g, "_")),
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
  const qualified = Boolean(
    run.state === "SUCCEEDED" &&
      run.status === "QUALIFIED" &&
      sources.length >= 3 &&
      domains.size >= 2 &&
      hasProblem &&
      hasAlternative,
  );
  return {
    status: run.status,
    qualified,
    completeness: {
      research_status: run.status,
      legacy_research_packet: false,
      verified_source_count: sources.length,
      independent_domain_count: domains.size,
      has_problem_evidence: hasProblem,
      has_current_alternative_evidence: hasAlternative,
    },
  };
}

function fatalConstraintIsVerified(state: SystemState, profile: IdeaProfile): boolean {
  const verifiedSourceIds = new Set(
    state.sourceEvidence
      .filter(
        (source) =>
          source.verificationStatus === "VERIFIED" &&
          (source.evidenceLevel === 1 || source.evidenceLevel === 2),
      )
      .map((source) => source.sourceId),
  );
  return state.fatalConstraints.some(
    (constraint) =>
      constraint.ideaProfileId === profile.profileId &&
      constraint.voidedAt === null &&
      constraint.independentlyVerified &&
      constraint.ownerConfirmedAt !== null &&
      constraint.sourceEvidenceIds.some((id) => verifiedSourceIds.has(id)),
  );
}

function commercialGate(
  thresholds: GateThresholds,
  latestBuyers: BuyerValidationRecord[],
  buyerGroups: Map<string, BuyerValidationRecord[]>,
): {
  met: boolean;
  pricePositive: number;
  commitments: number;
  combined: number;
} {
  const pricePositive = latestBuyers.filter(isPricePositive).length;
  const commitmentBuyers = new Set<string>();
  for (const [identity, records] of buyerGroups) {
    if (records.some(buyerCommitment)) commitmentBuyers.add(identity);
  }
  const meaningfulCommitments = commitmentBuyers.size;
  const combinedBuyers = new Set<string>([
    ...latestBuyers.filter(isPricePositive).map((record) => identityKey(record.buyerIdentifier)),
    ...commitmentBuyers,
  ]);
  if (thresholds.commercialSignalsAreCombined) {
    return {
      met: combinedBuyers.size >= thresholds.minPricePositive,
      pricePositive,
      commitments: meaningfulCommitments,
      combined: combinedBuyers.size,
    };
  }
  return {
    met:
      pricePositive >= thresholds.minPricePositive ||
      meaningfulCommitments >= thresholds.minMeaningfulCommitments,
    pricePositive,
    commitments: meaningfulCommitments,
    combined: combinedBuyers.size,
  };
}

function buyerPaymentIdentities(
  buyerGroups: Map<string, BuyerValidationRecord[]>,
): Set<string> {
  const identities = new Set<string>();
  for (const [identity, records] of buyerGroups) {
    if (records.some((record) => isVerifiedPayment(record.paymentAmount, record.paymentReference))) {
      identities.add(identity);
    }
  }
  return identities;
}

function trialPaymentIdentities(records: ProductTrialRecord[]): Set<string> {
  const identities = new Set<string>();
  for (const record of records) {
    if (
      record.voidedAt === null &&
      isVerifiedPayment(record.paymentAmount, record.paymentReference)
    ) {
      identities.add(identityKey(record.participantIdentifier));
    }
  }
  return identities;
}

function makeAction(
  profile: IdeaProfile | null,
  actionType: string,
  instruction: string,
): NextAction {
  return {
    actionId: newId(),
    ideaProfileId: profile?.profileId ?? null,
    actionType,
    instruction,
    completedAt: null,
    createdAt: nowIso(),
  };
}

function result(
  recommendation: GateRecommendation,
  profile: IdeaProfile | null,
  passed: string[],
  blockers: string[],
  completeness: Record<string, unknown>,
  actionType: string,
  instruction: string,
  scaleReady = false,
): AdaptiveGateEvaluation {
  return {
    recommendation,
    evaluatorVersion: EVALUATOR_VERSION,
    passedGates: passed,
    blockers,
    evidenceCompleteness: completeness,
    nextAction: makeAction(profile, actionType, instruction),
    scaleReady,
  };
}

export function evaluateAdaptiveGate(state: SystemState): AdaptiveGateEvaluation {
  const profile = activeIdeaProfile(state);
  if (state.ownerStoppedAt !== null) {
    return result(
      "OWNER_STOPPED",
      profile,
      ["The owner explicitly stopped this idea."],
      [],
      { owner_stopped: true },
      "REVIEW_OR_ARCHIVE",
      "Export or archive the evidence, or create a new pivot profile when ready.",
    );
  }
  if (!profile) {
    if (state.validationDecision === "go") {
      return result(
        "GO_BUILD",
        null,
        ["Legacy accepted GO migrated to GO_BUILD."],
        [],
        { legacy_migration: true },
        "CONFIRM_IDEA_PROFILE",
        "Confirm the buyer, sales motion, price, cadence, problem, and offer before the next research run.",
      );
    }
    return result(
      "CONTINUE",
      null,
      [],
      ["The versioned idea profile is incomplete."],
      { idea_profile_complete: false },
      "COMPLETE_IDEA_PROFILE",
      "Confirm the buyer, sales motion, target price, billing cadence, problem, and proposed offer.",
    );
  }

  const thresholds = THRESHOLDS[profile.systemProfile];
  const research = researchEvidence(state, profile);
  const completeness: Record<string, unknown> = {
    ...research.completeness,
    idea_profile_complete: true,
    validation_profile: profile.systemProfile,
    required_buyers: thresholds.minBuyers,
    required_strong_pain: thresholds.minStrongPain,
  };
  const passed = [`Locked profile selected: ${profile.systemProfile}.`];
  const blockers: string[] = [];

  if (fatalConstraintIsVerified(state, profile)) {
    passed.push(
      "A fatal constraint has non-AI source evidence and explicit owner confirmation.",
    );
    return result(
      "KILL",
      profile,
      passed,
      blockers,
      completeness,
      "ARCHIVE_FATAL_CONSTRAINT",
      "Archive the idea with the verified fatal constraint and its linked evidence.",
    );
  }

  const profileBuyers = state.buyerValidationRecords.filter(
    (record) => record.ideaProfileId === profile.profileId,
  );
  const buyerGroups = groupBuyers(profileBuyers);
  const latestBuyers = [...buyerGroups.values()].map((records) => records[records.length - 1]);
  const buyerCount = latestBuyers.length;
  const strongPain = latestBuyers.filter((record) => record.painStrength === "STRONG").length;
  const negativeCount = latestBuyers.filter(
    (record) => record.priorityStatus === "NO_PRIORITY" || !record.hasCurrentWorkaround,
  ).length;
  const majorityNegativeRequired = Math.floor(buyerCount / 2) + 1;
  const commercial = commercialGate(thresholds, latestBuyers, buyerGroups);
  const paymentIdentities = buyerPaymentIdentities(buyerGroups);

  Object.assign(completeness, {
    qualified_buyer_count: buyerCount,
    strong_pain_count: strongPain,
    price_positive_count: commercial.pricePositive,
    meaningful_commitment_count: commercial.commitments,
    combined_commercial_signal_count: commercial.combined,
    no_priority_or_no_workaround_count: negativeCount,
    strict_majority_negative_required: majorityNegativeRequired,
    verified_payment_count: paymentIdentities.size,
  });

  if (!research.qualified) {
    if (research.status === "UNAVAILABLE") {
      blockers.push(
        "Research is unavailable; an outage or missing provider access can never produce KILL.",
      );
    } else if (research.status === "CONTRADICTED") {
      blockers.push("Public research contradicts the current buyer/problem/offer profile.");
    } else {
      blockers.push(
        "Research is incomplete or lacks three verified sources across two domains with problem and alternative evidence.",
      );
    }
    const action =
      research.status === "UNAVAILABLE"
        ? "Retry the same persisted research run after provider access is restored."
        : research.status === "CONTRADICTED"
          ? "Review the contradictions and create a new pivot profile if they invalidate the current one."
          : "Complete a hosted-search run with verified problem and current-alternative sources.";
    const recommendation: GateRecommendation =
      research.status === "CONTRADICTED" && strongPain > 0 ? "PIVOT" : "CONTINUE";
    return result(recommendation, profile, passed, blockers, completeness, "RESOLVE_RESEARCH", action);
  }
  passed.push("Research qualification passed with provider-ledger sources.");

  if (buyerCount < thresholds.minBuyers) {
    const remaining = thresholds.minBuyers - buyerCount;
    blockers.push(`Need ${remaining} more unique qualified buyer record(s).`);
    return result(
      "CONTINUE",
      profile,
      passed,
      blockers,
      completeness,
      "INTERVIEW_BUYERS",
      `Interview and record ${remaining} more unique qualified buyer(s).`,
    );
  }
  passed.push(`Required direct sample reached with ${buyerCount} unique qualified buyers.`);

  const painMet = strongPain >= thresholds.minStrongPain;
  if (painMet) {
    passed.push(`Strong-pain gate passed (${strongPain}/${thresholds.minStrongPain}).`);
  } else {
    blockers.push(`Strong-pain gate failed (${strongPain}/${thresholds.minStrongPain}).`);
  }

  if (commercial.met) passed.push("Price-positive/meaningful-commitment gate passed.");
  else blockers.push("The locked price-positive/meaningful-commitment gate is not met.");

  if (!painMet && negativeCount >= majorityNegativeRequired) {
    if (paymentIdentities.size) {
      blockers.push("Verified payment evidence prevents an automatic KILL.");
      return result(
        "PIVOT",
        profile,
        passed,
        blockers,
        completeness,
        "PIVOT_PROFILE",
        "Create a fresh profile around the paying buyer, offer, price, or workflow and lock a new contract.",
      );
    }
    return result(
      "KILL",
      profile,
      passed,
      blockers,
      completeness,
      "ARCHIVE_LOW_PAIN",
      "Archive this profile with the completed low-pain, low-priority evidence sample.",
    );
  }

  if (!painMet || !commercial.met) {
    return result(
      "PIVOT",
      profile,
      passed,
      blockers,
      completeness,
      "PIVOT_PROFILE",
      "Create a fresh profile that changes the contradicted buyer, offer, price, positioning, or workflow.",
    );
  }

  passed.push("GO BUILD direct-validation contract passed.");

  const profileTrials = state.productTrialRecords.filter(
    (record) => record.ideaProfileId === profile.profileId,
  );
  const latestTrials = [
    ...latestByIdentity(
      profileTrials,
      (record) => record.participantIdentifier,
      (record) => record.voidedAt,
      (record) => record.createdAt,
    ).values(),
  ];
  const allPaymentIdentities = new Set([
    ...paymentIdentities,
    ...trialPaymentIdentities(profileTrials),
  ]);
  const scaleReady = allPaymentIdentities.size >= thresholds.minVerifiedPaymentsForScale;
  completeness.scale_ready_payment_count = allPaymentIdentities.size;
  completeness.scale_ready_payment_required = thresholds.minVerifiedPaymentsForScale;

  if (state.phase === "validation") {
    return result(
      "GO_BUILD",
      profile,
      passed,
      blockers,
      completeness,
      "BUILD_TESTABLE_MVP",
      "Build the smallest testable MVP for the validated core outcome.",
      scaleReady,
    );
  }

  const readiness = state.mvpReadiness;
  const mvpTestable = Boolean(
    readiness &&
      readiness.ideaProfileId === profile.profileId &&
      readiness.testable &&
      readiness.artifactReference.trim() &&
      readiness.coreOutcome.trim(),
  );
  completeness.mvp_testable = mvpTestable;
  if (!mvpTestable) {
    blockers.push("A testable MVP with an artifact reference and core outcome is required.");
    return result(
      "CONTINUE",
      profile,
      passed,
      blockers,
      completeness,
      "MAKE_MVP_TESTABLE",
      "Provide a testable MVP and define the observable core outcome before recruiting trials.",
      scaleReady,
    );
  }
  passed.push("A testable MVP and observable core outcome are recorded.");

  const handsOn = latestTrials.filter((record) => record.handsOn);
  const successful = handsOn.filter(
    (record) =>
      record.coreOutcomeAttempted &&
      record.coreOutcomeSucceeded &&
      record.outcomeDetail.trim(),
  );
  const purchaseCommitments = handsOn.filter(trialPurchaseCommitment);
  Object.assign(completeness, {
    hands_on_trial_count: handsOn.length,
    required_trial_count: thresholds.minTrials,
    successful_core_outcome_count: successful.length,
    required_successful_outcomes: thresholds.minSuccessfulOutcomes,
    purchase_or_pilot_commitment_count: purchaseCommitments.length,
    required_purchase_or_pilot_commitments: thresholds.minPurchaseCommitments,
  });

  if (handsOn.length < thresholds.minTrials) {
    const remaining = thresholds.minTrials - handsOn.length;
    blockers.push(`Need ${remaining} more unique hands-on trial(s).`);
    return result(
      "CONTINUE",
      profile,
      passed,
      blockers,
      completeness,
      "RUN_PRODUCT_TRIALS",
      `Run ${remaining} more hands-on trial(s) with unique qualified participants.`,
      scaleReady,
    );
  }

  if (
    successful.length < thresholds.minSuccessfulOutcomes ||
    purchaseCommitments.length < thresholds.minPurchaseCommitments
  ) {
    blockers.push(
      "The MVP outcome or purchase/pilot commitment threshold is contradicted after the required trial sample.",
    );
    return result(
      "PIVOT",
      profile,
      passed,
      blockers,
      completeness,
      "PIVOT_MVP_OR_OFFER",
      "Revise the MVP workflow or commercial offer, then lock the changed profile before more trials.",
      scaleReady,
    );
  }

  passed.push("GO SELL product-trial contract passed.");
  return result(
    "GO_SELL",
    profile,
    passed,
    blockers,
    completeness,
    "SELL_VALIDATED_OFFER",
    "Ask the successful trial participants to begin the committed purchase or pilot.",
    scaleReady,
  );
}

export function profileLabel(profile: ValidationProfile): string {
  return profile === "SALES_ASSISTED_HIGH_PRICE"
    ? "Sales-assisted / high-price"
    : "Self-serve / low-price";
}
