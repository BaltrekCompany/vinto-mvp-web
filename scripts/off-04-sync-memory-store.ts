// Test-only in-memory SyncQueueStore with the SAME transition rules as the IndexedDB store (offline-sync-rules.ts).
import { applyClaim, applyFinalize } from "../lib/vinto/offline-sync-rules.ts";
import type { SyncQueueStore, SyncRecord } from "../lib/vinto/offline-sync-types.ts";

export function createMemorySyncStore(): SyncQueueStore & { rows: Map<string, SyncRecord> } {
    const rows = new Map<string, SyncRecord>();
    return {
        rows,
        async enqueue(record) {
            const cur = rows.get(record.capture_id);
            if (cur) {
                if (cur.payloadSha256 !== record.payloadSha256 || cur.ownerId !== record.ownerId) throw new Error("duplicate_conflict");
                return { created: false, record: cur };
            }
            rows.set(record.capture_id, record);
            return { created: true, record };
        },
        async get(id) { return rows.get(id) ?? null; },
        async list(ownerId, deviceKey) { return [...rows.values()].filter(r => r.ownerId === ownerId && r.deviceKey === deviceKey); },
        async claim(id, tabId, now, leaseMs) {
            const cur = rows.get(id);
            const next = cur ? applyClaim(cur, tabId, now, leaseMs) : null;
            if (next) rows.set(id, next.record);
            return next;
        },
        async finalize(id, tabId, patch, now) {
            const cur = rows.get(id);
            const next = cur ? applyFinalize(cur, tabId, patch, now) : null;
            if (!next) return false;
            rows.set(id, next);
            return true;
        },
    };
}
