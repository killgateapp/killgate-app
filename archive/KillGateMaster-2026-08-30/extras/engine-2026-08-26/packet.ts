import { activeIdeaProfile, profileLabel } from "./evaluator.ts";
import { evaluateAdaptiveGate } from "./evaluator.ts";
import { nowIso } from "./ids.ts";
import type { SystemState } from "./types.ts";

export function slugForPacket(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return slug || "workspace";
}

export function buildEvidencePacket(state: SystemState) {
  const evaluation = evaluateAdaptiveGate(state);
  const profile = activeIdeaProfile(state);
  const buyers = state.buyerValidationRecords.filter(
    (row) => !profile || row.ideaProfileId === profile.profileId,
  );
  const trials = state.productTrialRecords.filter(
    (row) => !profile || row.ideaProfileId === profile.profileId,
  );
  const sources = state.sourceEvidence.filter((source) => {
    if (source.verificationStatus !== "VERIFIED") return false;
    if (!profile) return true;
    const run = state.researchRuns.find((item) => item.runId === source.researchRunId);
    return !run || run.ideaProfileId === profile.profileId;
  });

  return {
    packetVersion: "1.0",
    product: "Killgate",
    exportedAt: nowIso(),
    evaluatorVersion: evaluation.evaluatorVersion,
    workspace: {
      id: state.id,
      name: state.name,
      hypothesis: state.hypothesis,
      phase: state.phase,
      archivedAt: state.archivedAt,
    },
    gate: {
      recommendation: evaluation.recommendation,
      nextAction: evaluation.nextAction.actionType,
      instruction: evaluation.nextAction.instruction,
      blockers: evaluation.blockers,
      passedGates: evaluation.passedGates,
      completeness: evaluation.evidenceCompleteness,
      scaleReady: evaluation.scaleReady,
    },
    profile: profile
      ? {
          profileId: profile.profileId,
          version: profile.version,
          buyerType: profile.buyerType,
          salesMotion: profile.salesMotion,
          salesCallRequired: profile.salesCallRequired,
          targetPrice: profile.targetPrice,
          billingCadence: profile.billingCadence,
          problem: profile.problem,
          proposedOffer: profile.proposedOffer,
          systemProfile: profile.systemProfile,
          systemProfileLabel: profileLabel(profile.systemProfile),
          contractFingerprint: profile.contractFingerprint,
        }
      : null,
    evidence: {
      sources: sources.map((source) => ({
        title: source.title,
        url: source.sourceUrl,
        domain: source.domain,
        theme: source.queryTheme,
        evidenceLevel: source.evidenceLevel,
      })),
      buyers: buyers.map((buyer) => ({
        identifier: buyer.buyerIdentifier,
        role: buyer.buyerRole,
        qualificationBasis: buyer.qualificationBasis,
        recentRealExample: buyer.recentRealExample,
        painStrength: buyer.painStrength,
        priorityStatus: buyer.priorityStatus,
        pricePositive: buyer.pricePositive,
        pilotPriceTested: buyer.pilotPriceTested,
        commitmentType: buyer.commitmentType,
        paymentAmount: buyer.paymentAmount,
        voided: Boolean(buyer.voidedAt),
      })),
      trials: trials.map((trial) => ({
        participant: trial.participantIdentifier,
        handsOn: trial.handsOn,
        coreOutcomeSucceeded: trial.coreOutcomeSucceeded,
        outcomeDetail: trial.outcomeDetail,
        commitmentType: trial.commitmentType,
        voided: Boolean(trial.voidedAt),
      })),
    },
    notes: [
      "This packet is an attested snapshot of owner-entered evidence.",
      "Killgate does not independently verify interviews, payments, or URLs.",
      "A GO is a contract against this ledger, not a prediction of success.",
    ],
  };
}

export type EvidencePacket = ReturnType<typeof buildEvidencePacket>;

export function packetFilename(state: SystemState, packet: EvidencePacket): string {
  const gate = (packet.gate.recommendation || "continue").toLowerCase().replaceAll("_", "-");
  const day = packet.exportedAt.slice(0, 10);
  return `killgate-${gate}-${slugForPacket(state.name)}-${day}.json`;
}

export function downloadEvidencePacket(state: SystemState) {
  const packet = buildEvidencePacket(state);
  const blob = new Blob([JSON.stringify(packet, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = packetFilename(state, packet);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return packet;
}
