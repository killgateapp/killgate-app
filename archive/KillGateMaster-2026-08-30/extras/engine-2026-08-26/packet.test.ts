import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmIdeaProfile, createIdeaProfile } from "./profile.ts";
import { buildEvidencePacket, packetFilename, slugForPacket } from "./packet.ts";
import type { SystemState } from "./types.ts";

const NOW = "2026-08-26T05:00:00.000Z";

function sample(): SystemState {
  const state: SystemState = {
    id: "v-packet",
    name: "Call capture for shops",
    hypothesis: "Shops miss calls.",
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
  const profile = createIdeaProfile({
    buyerType: "Shop owner",
    salesMotion: "SALES_ASSISTED",
    salesCallRequired: true,
    targetPrice: 149,
    billingCadence: "MONTHLY",
    problem: "Missed calls during jobs.",
    proposedOffer: "Call capture assistant.",
  });
  confirmIdeaProfile(state, profile);
  return state;
}

test("packet includes the locked profile and gate, not a prediction", () => {
  const packet = buildEvidencePacket(sample());
  assert.equal(packet.product, "Killgate");
  assert.equal(packet.profile?.buyerType, "Shop owner");
  assert.ok(packet.profile?.contractFingerprint);
  assert.equal(packet.gate.recommendation, "CONTINUE");
  assert.ok(packet.notes.some((note) => note.includes("not a prediction")));
});

test("filename is stable and filesystem-safe", () => {
  const state = sample();
  const packet = buildEvidencePacket(state);
  packet.exportedAt = "2026-08-26T05:00:00.000Z";
  assert.equal(slugForPacket("Call capture for shops"), "call-capture-for-shops");
  assert.match(packetFilename(state, packet), /^killgate-continue-call-capture-for-shops-2026-08-26\.json$/);
});
