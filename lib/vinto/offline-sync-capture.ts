/**
 * OFF-04.3 (LABORATORY ONLY): builds sealed, frozen SYNTHETIC test captures for the synchronisation engine and opens
 * them again. The payload is encrypted with the local vault (AAD bound to owner, browser, capture, context, form and
 * version). These are test records of the simulated server only: they are NOT industrial captures.
 */
import { openLocalDraft, sealLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import { contextIdFor } from "./offline-draft-schema.ts";
import { payloadHash } from "./offline-sync-engine.ts";
import type { SyncQueueStore, SyncRecord } from "./offline-sync-types.ts";

export type NewSyncCapture = Readonly<{
    captureId?: string;
    payload: Record<string, unknown>;
    formCode?: string;
    formVersion?: number;
    contextVersion: string;
    dependsOn?: string | null;
    seq: number;
}>;

const binding = async (identity: OfflineVaultIdentity, r: Pick<SyncRecord, "capture_id" | "formCode" | "formVersion" | "contextVersion">) => ({
    ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: r.capture_id,
    contextId: await contextIdFor(r.contextVersion, "SYNCLAB", r.formCode), formCode: r.formCode, formVersion: r.formVersion,
});

export async function createSyncCapture(
    key: CryptoKey, identity: OfflineVaultIdentity, store: SyncQueueStore, input: NewSyncCapture, now: () => number = () => Date.now()
): Promise<SyncRecord> {
    const captureId = (input.captureId ?? crypto.randomUUID()).toLowerCase();
    const partial = { capture_id: captureId, formCode: input.formCode ?? "VINTO-P1-26", formVersion: input.formVersion ?? 1, contextVersion: input.contextVersion };
    const sealed = await sealLocalDraft(key, await binding(identity, partial), { synthetic: true, payload: input.payload });
    const iso = new Date(now()).toISOString();
    const record: SyncRecord = {
        ...partial, ownerId: identity.ownerId.toLowerCase(), deviceKey: identity.deviceKey.toLowerCase(), seq: input.seq,
        dependsOn: input.dependsOn ? input.dependsOn.toLowerCase() : null, payloadSha256: await payloadHash({ synthetic: true, payload: input.payload }),
        state: "queued", attempts: 0, nextAttemptAt: null, uncertain: false, lease: null, version: 1, lastError: null, serverRef: null, warnings: [],
        createdAt: iso, updatedAt: iso, sealed,
    };
    return (await store.enqueue(record)).record;
}

export function openSyncPayload(key: CryptoKey, identity: OfflineVaultIdentity): (record: SyncRecord) => Promise<unknown> {
    return async (record) => openLocalDraft(key, await binding(identity, record), record.sealed);
}
