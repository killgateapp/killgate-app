import { sha256Hex } from "./sha256.ts";
import { canonicalPrice, identityKey, newId, nowIso } from "./ids.ts";
import {
  ADAPTIVE_CONTRACT_VERSION,
  THRESHOLDS,
  type BillingCadence,
  type IdeaProfile,
  type NextAction,
  type SalesMotion,
  type SystemState,
  type ValidationContract,
  type ValidationProfile,
} from "./types.ts";
import { activeIdeaProfile } from "./evaluator.ts";

export function chooseValidationProfile(input: {
  salesMotion: SalesMotion;
  salesCallRequired: boolean;
  targetPrice: number;
  billingCadence: BillingCadence;
}): ValidationProfile {
  if (input.salesCallRequired || input.salesMotion === "SALES_ASSISTED") {
    return "SALES_ASSISTED_HIGH_PRICE";
  }
  if (input.billingCadence === "ONE_TIME") {
    return input.targetPrice >= 500
      ? "SALES_ASSISTED_HIGH_PRICE"
      : "SELF_SERVE_LOW_PRICE";
  }
  let monthly = input.targetPrice;
  if (input.billingCadence === "ANNUAL") monthly = input.targetPrice / 12;
  else if (input.billingCadence === "WEEKLY") {
    monthly = (input.targetPrice * 52) / 12;
  }
  return monthly >= 100 ? "SALES_ASSISTED_HIGH_PRICE" : "SELF_SERVE_LOW_PRICE";
}

function pythonCanonical(obj: Record<string, unknown>): string {
  const keys = Object.keys(obj).sort();
  const parts = keys.map((key) => {
    const value = obj[key];
    if (typeof value === "string") return `"${key}":${JSON.stringify(value)}`;
    if (typeof value === "boolean") return `"${key}":${value ? "true" : "false"}`;
    return `"${key}":${JSON.stringify(value)}`;
  });
  return `{${parts.join(",")}}`;
}

export function fingerprintIdea(profile: {
  buyerType: string;
  salesMotion: SalesMotion;
  salesCallRequired: boolean;
  targetPrice: number;
  billingCadence: BillingCadence;
  problem: string;
  proposedOffer: string;
  systemProfile: ValidationProfile;
}): string {
  const payload = {
    billing_cadence: profile.billingCadence,
    buyer_type: identityKey(profile.buyerType),
    problem: identityKey(profile.problem),
    proposed_offer: identityKey(profile.proposedOffer),
    sales_call_required: profile.salesCallRequired,
    sales_motion: profile.salesMotion,
    system_profile: profile.systemProfile,
    target_price: canonicalPrice(profile.targetPrice),
  };
  return sha256Hex(pythonCanonical(payload));
}

export type IdeaProfileDraft = {
  buyerType: string;
  salesMotion: SalesMotion;
  salesCallRequired: boolean;
  targetPrice: number;
  billingCadence: BillingCadence;
  problem: string;
  proposedOffer: string;
  createdAt?: string;
  profileId?: string;
};

export function createIdeaProfile(draft: IdeaProfileDraft): IdeaProfile {
  const systemProfile = chooseValidationProfile(draft);
  const profile: IdeaProfile = {
    profileId: draft.profileId ?? newId(),
    version: 1,
    buyerType: draft.buyerType.trim(),
    salesMotion: draft.salesMotion,
    salesCallRequired: draft.salesCallRequired,
    targetPrice: draft.targetPrice,
    billingCadence: draft.billingCadence,
    problem: draft.problem.trim(),
    proposedOffer: draft.proposedOffer.trim(),
    systemProfile,
    contractFingerprint: "",
    createdAt: draft.createdAt ?? nowIso(),
    supersededAt: null,
  };
  profile.contractFingerprint = fingerprintIdea(profile);
  return profile;
}

export function buildAdaptiveContract(profile: IdeaProfile): ValidationContract {
  const thresholds = THRESHOLDS[profile.systemProfile];
  const commercialRule =
    profile.systemProfile === "SALES_ASSISTED_HIGH_PRICE"
      ? `At least ${thresholds.minPricePositive} concrete price-positive buyers or ${thresholds.minMeaningfulCommitments} meaningful commitments.`
      : `At least ${thresholds.minPricePositive} unique buyers with a concrete price-positive response or meaningful commitment.`;

  return {
    contractVersion: ADAPTIVE_CONTRACT_VERSION,
    status: "locked",
    source: "system",
    hypothesisFingerprint: profile.contractFingerprint,
    ideaProfileId: profile.profileId,
    validationProfile: profile.systemProfile,
    createdAt: nowIso(),
    lockedAt: nowIso(),
    criticalAssumptions: [
      `The confirmed buyer (${profile.buyerType}) experiences the stated problem.`,
      "The problem is strong enough to change behavior or priority.",
      "The proposed offer improves a current alternative or workaround.",
      `The commercial signal supports ${profile.targetPrice} ${profile.billingCadence.toLowerCase()}.`,
    ],
    evidenceThatCounts: [
      "Levels 1–2: public facts attested from a real URL you opened, not an AI summary.",
      "Level 3: structured records from unique qualified buyers.",
      "Level 4: dated pilots, signed intent, supplied workflow/data access, or named implementation steps.",
      "Level 5: a positive payment amount with a verifiable reference.",
    ],
    evidenceThatDoesNotCount: [
      "AI summaries, assumptions, personas, simulations, or unsupported URLs.",
      "Praise, likes, generic waitlists, or hypothetical interest.",
      "Duplicate buyers or voided/corrected evidence.",
    ],
    researchRules: {
      min_verified_sources: 3,
      min_independent_domains: 2,
      require_problem_evidence: true,
      require_current_alternative_evidence: true,
      allowed_statuses: ["QUALIFIED", "INCOMPLETE", "CONTRADICTED", "UNAVAILABLE"],
    },
    humanRules: {
      min_unique_qualified_buyers: thresholds.minBuyers,
      min_strong_pain_records: thresholds.minStrongPain,
      min_price_positive_records: thresholds.minPricePositive,
      min_meaningful_commitments: thresholds.minMeaningfulCommitments,
      commercial_signals_are_combined: thresholds.commercialSignalsAreCombined,
      kill_requires_strict_majority_no_priority_or_no_workaround: true,
      verified_payments_prevent_automatic_kill: true,
      min_hands_on_trials: thresholds.minTrials,
      min_successful_core_outcomes: thresholds.minSuccessfulOutcomes,
      min_purchase_or_pilot_commitments: thresholds.minPurchaseCommitments,
      min_verified_payments_for_scale_signal: thresholds.minVerifiedPaymentsForScale,
    },
    decisionRules: {
      GO_BUILD: [
        `At least ${thresholds.minBuyers} unique qualified buyers.`,
        `At least ${thresholds.minStrongPain} strong-pain records.`,
        commercialRule,
        "No buyer payment is required.",
      ],
      GO_SELL: [
        "A testable MVP and observable core outcome are recorded.",
        `At least ${thresholds.minTrials} unique hands-on trials.`,
        `At least ${thresholds.minSuccessfulOutcomes} successful core outcomes.`,
        `At least ${thresholds.minPurchaseCommitments} explicit purchase or pilot commitments.`,
      ],
      CONTINUE: [
        "Required evidence is incomplete, unavailable, or below the direct-sample boundary.",
      ],
      PIVOT: [
        "Real signal exists, but the buyer, offer, price, positioning, or workflow is contradicted.",
        "A material change creates a fresh profile version and contract.",
      ],
      KILL: [
        "The required direct sample has insufficient strong pain and a strict majority reports no priority or no workaround.",
        "A fatal legal, technical, trust, or economic constraint has verified non-AI evidence and owner confirmation.",
      ],
      OWNER_STOPPED: [
        "The owner chose to stop; this is never represented as an evidence-backed KILL.",
      ],
    },
    notes: [
      "Thresholds are system-owned and cannot be lowered by a client or AI response.",
      "Research failures and unavailable sources can never produce KILL.",
      "Verified payments are a scale-readiness signal and prevent automatic KILL.",
    ],
  };
}

export function confirmIdeaProfile(
  state: SystemState,
  candidate: IdeaProfile,
  confirmedAt?: string,
): { profile: IdeaProfile; changed: boolean } {
  const now = confirmedAt ?? nowIso();
  const current = activeIdeaProfile(state);
  if (current && current.contractFingerprint === candidate.contractFingerprint) {
    return { profile: current, changed: false };
  }

  if (current) current.supersededAt = now;
  candidate.version =
    Math.max(0, ...state.ideaProfiles.map((profile) => profile.version)) + 1;
  candidate.createdAt = now;
  candidate.supersededAt = null;
  state.ideaProfiles.push(candidate);
  state.activeIdeaProfileId = candidate.profileId;
  state.validationContract = buildAdaptiveContract(candidate);
  state.phase = "validation";
  state.researchPass = false;
  state.validationDecision = null;
  state.gateRecommendation = current ? "PIVOT" : "CONTINUE";

  const action: NextAction = {
    actionId: newId(),
    ideaProfileId: candidate.profileId,
    actionType: "RUN_RESEARCH",
    instruction: "Collect verified public-evidence sources for this locked profile.",
    completedAt: null,
    createdAt: now,
  };
  state.nextActions.push(action);
  state.lastUpdated = now;
  return { profile: candidate, changed: true };
}
