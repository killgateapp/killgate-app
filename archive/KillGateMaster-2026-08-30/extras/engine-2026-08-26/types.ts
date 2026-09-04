export const EVALUATOR_VERSION = "2.0.0";
export const ADAPTIVE_CONTRACT_VERSION = "2.0";

export type GateRecommendation =
  | "GO_BUILD"
  | "GO_SELL"
  | "CONTINUE"
  | "PIVOT"
  | "KILL"
  | "OWNER_STOPPED";

export type ValidationProfile =
  | "SALES_ASSISTED_HIGH_PRICE"
  | "SELF_SERVE_LOW_PRICE";

export type SalesMotion = "SELF_SERVE" | "SALES_ASSISTED" | "HYBRID";
export type BillingCadence = "WEEKLY" | "MONTHLY" | "ANNUAL" | "ONE_TIME";
export type ResearchStatus =
  | "QUALIFIED"
  | "INCOMPLETE"
  | "CONTRADICTED"
  | "UNAVAILABLE";
export type ResearchRunState = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
export type SourceVerificationStatus = "VERIFIED" | "REJECTED";
export type PainStrength = "NONE" | "WEAK" | "MODERATE" | "STRONG";
export type PriorityStatus = "PRIORITY" | "NOT_NOW" | "NO_PRIORITY" | "UNKNOWN";
export type CommitmentType =
  | "NONE"
  | "DATED_PILOT"
  | "SIGNED_INTENT"
  | "WORKFLOW_OR_DATA_ACCESS"
  | "NAMED_IMPLEMENTATION_STEP"
  | "PURCHASE";
export type FatalConstraintType = "LEGAL" | "TECHNICAL" | "TRUST" | "ECONOMIC";
export type Phase = "validation" | "build" | "distribute" | "scale" | "kill";
export type LegacyDecision =
  | "go"
  | "continue_validation"
  | "kill"
  | "pivot"
  | null;

export type IdeaProfile = {
  profileId: string;
  version: number;
  buyerType: string;
  salesMotion: SalesMotion;
  salesCallRequired: boolean;
  targetPrice: number;
  billingCadence: BillingCadence;
  problem: string;
  proposedOffer: string;
  systemProfile: ValidationProfile;
  contractFingerprint: string;
  createdAt: string;
  supersededAt: string | null;
};

export type ResearchRun = {
  runId: string;
  ideaProfileId: string | null;
  state: ResearchRunState;
  status: ResearchStatus | null;
  queryThemes: string[];
  provider: string;
  failureCode: string;
  failureMessage: string;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
};

export type SourceEvidence = {
  sourceId: string;
  researchRunId: string;
  sourceUrl: string;
  title: string;
  domain: string;
  queryTheme: string;
  verificationStatus: SourceVerificationStatus;
  evidenceLevel: 0 | 1 | 2;
  claimMappings: string[];
  accessedAt: string;
};

export type BuyerValidationRecord = {
  recordId: string;
  ideaProfileId: string;
  buyerIdentifier: string;
  buyerRole: string;
  qualificationBasis: string;
  recentRealExample: string;
  hasCurrentWorkaround: boolean;
  currentWorkaround: string;
  painStrength: PainStrength;
  priorityStatus: PriorityStatus;
  pilotPriceTested: number;
  priceResponse: string;
  pricePositive: boolean;
  commitmentType: CommitmentType;
  commitmentDetail: string;
  commitmentDate: string | null;
  commitmentReference: string;
  paymentAmount: number;
  paymentReference: string;
  objectionOrNoReason: string;
  createdAt: string;
  voidedAt: string | null;
  voidReason: string;
};

export type MvpReadiness = {
  ideaProfileId: string;
  testable: boolean;
  artifactReference: string;
  coreOutcome: string;
  confirmedAt: string | null;
};

export type ProductTrialRecord = {
  trialId: string;
  ideaProfileId: string;
  participantIdentifier: string;
  qualificationBasis: string;
  handsOn: boolean;
  coreOutcomeAttempted: boolean;
  coreOutcomeSucceeded: boolean;
  outcomeDetail: string;
  commitmentType: CommitmentType;
  commitmentDetail: string;
  commitmentDate: string | null;
  commitmentReference: string;
  paymentAmount: number;
  paymentReference: string;
  createdAt: string;
  voidedAt: string | null;
  voidReason: string;
};

export type FatalConstraint = {
  constraintId: string;
  ideaProfileId: string;
  constraintType: FatalConstraintType;
  description: string;
  sourceEvidenceIds: string[];
  independentlyVerified: boolean;
  ownerConfirmedAt: string | null;
  createdAt: string;
  voidedAt: string | null;
  voidReason: string;
};

export type NextAction = {
  actionId: string;
  ideaProfileId: string | null;
  actionType: string;
  instruction: string;
  completedAt: string | null;
  createdAt: string;
};

export type ValidationContract = {
  contractVersion: string;
  status: "locked" | "draft";
  source: "system";
  hypothesisFingerprint: string;
  ideaProfileId: string | null;
  validationProfile: ValidationProfile | null;
  createdAt: string;
  lockedAt: string;
  criticalAssumptions: string[];
  evidenceThatCounts: string[];
  evidenceThatDoesNotCount: string[];
  researchRules: Record<string, unknown>;
  humanRules: Record<string, unknown>;
  decisionRules: Record<string, string[]>;
  notes: string[];
};

export type RecommendationRecord = {
  recommendationId: string;
  ideaProfileId: string | null;
  recommendation: GateRecommendation;
  evaluatorVersion: string;
  passedGates: string[];
  blockers: string[];
  evidenceCompleteness: Record<string, unknown>;
  nextAction: NextAction;
  createdAt: string;
};

export type SystemState = {
  id: string;
  name: string;
  hypothesis: string;
  phase: Phase;
  validationDecision: LegacyDecision;
  researchPass: boolean;
  ideaProfiles: IdeaProfile[];
  activeIdeaProfileId: string | null;
  researchRuns: ResearchRun[];
  sourceEvidence: SourceEvidence[];
  buyerValidationRecords: BuyerValidationRecord[];
  mvpReadiness: MvpReadiness | null;
  productTrialRecords: ProductTrialRecord[];
  fatalConstraints: FatalConstraint[];
  gateRecommendation: GateRecommendation | null;
  recommendationLog: RecommendationRecord[];
  nextActions: NextAction[];
  ownerStoppedAt: string | null;
  archivedAt: string | null;
  validationContract: ValidationContract | null;
  createdAt: string;
  lastUpdated: string;
};

export type GateThresholds = {
  minBuyers: number;
  minStrongPain: number;
  minPricePositive: number;
  minMeaningfulCommitments: number;
  commercialSignalsAreCombined: boolean;
  minTrials: number;
  minSuccessfulOutcomes: number;
  minPurchaseCommitments: number;
  minVerifiedPaymentsForScale: number;
};

export type AdaptiveGateEvaluation = {
  recommendation: GateRecommendation;
  evaluatorVersion: string;
  passedGates: string[];
  blockers: string[];
  evidenceCompleteness: Record<string, unknown>;
  nextAction: NextAction;
  scaleReady: boolean;
};

export const THRESHOLDS: Record<ValidationProfile, GateThresholds> = {
  SALES_ASSISTED_HIGH_PRICE: {
    minBuyers: 6,
    minStrongPain: 3,
    minPricePositive: 3,
    minMeaningfulCommitments: 2,
    commercialSignalsAreCombined: false,
    minTrials: 3,
    minSuccessfulOutcomes: 2,
    minPurchaseCommitments: 2,
    minVerifiedPaymentsForScale: 2,
  },
  SELF_SERVE_LOW_PRICE: {
    minBuyers: 12,
    minStrongPain: 5,
    minPricePositive: 5,
    minMeaningfulCommitments: 5,
    commercialSignalsAreCombined: true,
    minTrials: 8,
    minSuccessfulOutcomes: 5,
    minPurchaseCommitments: 3,
    minVerifiedPaymentsForScale: 5,
  },
};

export const GATE_COPY: Record<
  GateRecommendation,
  { label: string; tone: "go" | "wait" | "pivot" | "kill" | "stop" }
> = {
  GO_BUILD: { label: "GO BUILD", tone: "go" },
  GO_SELL: { label: "GO SELL", tone: "go" },
  CONTINUE: { label: "CONTINUE", tone: "wait" },
  PIVOT: { label: "PIVOT", tone: "pivot" },
  KILL: { label: "KILL", tone: "kill" },
  OWNER_STOPPED: { label: "OWNER STOPPED", tone: "stop" },
};
