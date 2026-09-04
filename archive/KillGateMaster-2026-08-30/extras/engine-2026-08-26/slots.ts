import { activeIdeaProfile } from "./evaluator.ts";
import type { SystemState } from "./types.ts";

export const MAX_LIVE_LOCKS = 3;

export const SLOT_FULL_MESSAGE =
  "Three live locks are already open. Archive one before locking another idea.";

export type SlotFailureCode = "SLOT_FULL" | "ARCHIVED" | "NOT_FOUND";

export type SlotOk<T extends object = object> = { ok: true } & T;
export type SlotErr = { ok: false; code: SlotFailureCode; message: string };
export type SlotResult<T extends object = object> = SlotOk<T> | SlotErr;

export function isLiveLocked(state: SystemState): boolean {
  if (state.archivedAt) return false;
  return activeIdeaProfile(state) !== null;
}

export function liveLockedVentures(ventures: SystemState[]): SystemState[] {
  return ventures.filter(isLiveLocked);
}

export function slotStatus(ventures: SystemState[]) {
  const live = liveLockedVentures(ventures);
  return {
    used: live.length,
    max: MAX_LIVE_LOCKS,
    remaining: Math.max(0, MAX_LIVE_LOCKS - live.length),
    full: live.length >= MAX_LIVE_LOCKS,
    live,
  };
}

export function canOpenLiveLock(ventures: SystemState[], ventureId?: string): boolean {
  if (ventureId) {
    const current = ventures.find((venture) => venture.id === ventureId);
    if (current && isLiveLocked(current)) return true;
  }
  return !slotStatus(ventures).full;
}

export function canUnarchive(ventures: SystemState[], ventureId: string): boolean {
  const current = ventures.find((venture) => venture.id === ventureId);
  if (!current) return false;
  if (!current.archivedAt) return true;
  if (activeIdeaProfile(current) === null) return true;
  return slotStatus(ventures.filter((venture) => venture.id !== ventureId)).used < MAX_LIVE_LOCKS;
}

export function slotFullError(): SlotErr {
  return { ok: false, code: "SLOT_FULL", message: SLOT_FULL_MESSAGE };
}
