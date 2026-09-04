import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmIdeaProfile, createIdeaProfile } from "./profile.ts";
import {
  MAX_LIVE_LOCKS,
  canOpenLiveLock,
  canUnarchive,
  isLiveLocked,
  slotStatus,
} from "./slots.ts";
import type { SystemState } from "./types.ts";

const NOW = "2026-08-26T05:00:00.000Z";

function draft(id: string): SystemState {
  return {
    id,
    name: id,
    hypothesis: "draft",
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

function locked(id: string, archived = false): SystemState {
  const state = draft(id);
  const profile = createIdeaProfile({
    buyerType: "Owner",
    salesMotion: "SALES_ASSISTED",
    salesCallRequired: true,
    targetPrice: 149,
    billingCadence: "MONTHLY",
    problem: "Waste",
    proposedOffer: "Gate",
  });
  confirmIdeaProfile(state, profile);
  if (archived) state.archivedAt = NOW;
  return state;
}

test("drafts do not occupy live slots", () => {
  const status = slotStatus([draft("a"), draft("b")]);
  assert.equal(status.used, 0);
  assert.equal(status.full, false);
  assert.equal(isLiveLocked(draft("a")), false);
});

test("a locked unarchived profile occupies one slot", () => {
  assert.equal(isLiveLocked(locked("a")), true);
  assert.equal(slotStatus([locked("a"), draft("b")]).used, 1);
});

test("archive frees a live slot", () => {
  const status = slotStatus([locked("a", true), locked("b")]);
  assert.equal(status.used, 1);
  assert.equal(isLiveLocked(locked("a", true)), false);
});

test("fourth new lock is refused, pivot on an existing live lock is allowed", () => {
  const ventures = [locked("a"), locked("b"), locked("c"), draft("d")];
  assert.equal(slotStatus(ventures).used, MAX_LIVE_LOCKS);
  assert.equal(canOpenLiveLock(ventures, "d"), false);
  assert.equal(canOpenLiveLock(ventures, "a"), true);
  assert.equal(canOpenLiveLock(ventures), false);
});

test("unarchiving needs a free slot", () => {
  const full = [locked("a"), locked("b"), locked("c"), locked("d", true)];
  assert.equal(canOpenLiveLock(full, "d"), false);
  assert.equal(canUnarchive(full, "d"), false);
  const withRoom = [locked("a"), locked("d", true)];
  assert.equal(canUnarchive(withRoom, "d"), true);
  const archivedDraft = { ...draft("e"), archivedAt: NOW };
  assert.equal(
    canUnarchive([locked("a"), locked("b"), locked("c"), archivedDraft], "e"),
    true,
  );
});
