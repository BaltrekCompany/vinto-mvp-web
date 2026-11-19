/**
 * OFF-04.3 (LABORATORY ONLY): the pure state-transition rules shared by EVERY queue store (IndexedDB and the
 * in-memory one used by Node tests), so the same compare-and-swap semantics are exercised everywhere.
 */
import type { FinalizePatch, SyncRecord } from "./offline-sync-types.ts";

/** Eligibility + new value for a claim, or null when the record cannot be taken at `now`. */
export function applyClaim(rec: SyncRecord, tabId: string, now: number, leaseMs: number): { record: SyncRecord; recovered: boolean } | null {
    let recovered = false;
    if (rec.state === "queued") { /* eligible */ }
    else if (rec.state === "retry_wait") { if ((rec.nextAttemptAt ?? 0) > now) return null; }
    else if (rec.state === "syncing") {
        if (!rec.lease || rec.lease.until > now) return null;       // another tab is still working on it
        recovered = true;                                           // lease expired: the previous attempt was interrupted
    } else return null;                                             // terminal states are never sent again
    return {
        recovered,
        record: { ...rec, state: "syncing", attempts: rec.attempts + 1, uncertain: rec.uncertain || recovered,
            lease: { owner: tabId, until: now + leaseMs }, version: rec.version + 1, updatedAt: new Date(now).toISOString() },
    };
}

/** Apply a result only while `tabId` still holds the lease of a `syncing` record. */
export function applyFinalize(rec: SyncRecord, tabId: string, patch: FinalizePatch, now: number): SyncRecord | null {
    if (rec.state !== "syncing" || !rec.lease || rec.lease.owner !== tabId) return null;
    return { ...rec, ...patch, lease: null, version: rec.version + 1, updatedAt: new Date(now).toISOString() };
}
