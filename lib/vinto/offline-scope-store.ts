/**
 * OFF-03B.3: encrypted signed-scope snapshots, bound to the SAME single-user
 * browser vault. Scope metadata is never persisted as plaintext in IndexedDB.
 * Only an authenticated HTTPS enrolment may first pin the public key. A signed
 * historical scope is NOT permission to record or upload a capture.
 */
import { openProfileDb, readLocalProfile, SCOPE_STORE_NAME } from "./offline-profile-store.ts";
import { openLocalDraft, sealLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { SealedValues } from "./offline-store";
import { verifyOfflineScope, type SignedOfflineScope, type OfflineScopeIdentity, ScopeError } from "./offline-scope-verify.ts";

const FORM_CODE = "VINTO-OFFLINE-SCOPE";
const FORM_VERSION = 1;
type Stored = { profileId: string; ownerId: string; deviceKey: string; snapshotId: string; sealed: SealedValues };
export type VerifiedLocalScope = Readonly<{ envelope: SignedOfflineScope; trustedPublicKey: string }>;

function id(identity: OfflineVaultIdentity): string {
    return identity.ownerId.toLowerCase() + ":" + identity.deviceKey.toLowerCase();
}
function binding(identity: OfflineVaultIdentity, snapshotId: string) {
    return { ...identity, id: snapshotId, contextId: snapshotId, formCode: FORM_CODE, formVersion: FORM_VERSION };
}
function validStored(value: unknown, identity: OfflineScopeIdentity): value is Stored {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const obj = value as Record<string, unknown>;
    return obj.profileId === id(identity) && obj.ownerId === identity.ownerId.toLowerCase() &&
        obj.deviceKey === identity.deviceKey.toLowerCase() && typeof obj.snapshotId === "string" &&
        typeof obj.sealed === "object" && obj.sealed !== null;
}
async function getRecord(identity: OfflineScopeIdentity): Promise<Stored | null> {
    const db = await openProfileDb();
    try {
        return await new Promise((resolve, reject) => {
            const tx = db.transaction(SCOPE_STORE_NAME, "readonly");
            const request = tx.objectStore(SCOPE_STORE_NAME).get(id(identity));
            request.onsuccess = () => {
                if (request.result == null) { resolve(null); return; }
                if (!validStored(request.result, identity)) { reject(new ScopeError("invalid")); return; }
                resolve(request.result);
            };
            request.onerror = () => reject(new ScopeError("unavailable"));
            tx.onerror = () => reject(new ScopeError("unavailable"));
            tx.onabort = () => reject(new ScopeError("unavailable"));
        });
    } finally { db.close(); }
}

/** Read, decrypt, validate exact owner+browser and independently stored trust pin. */
export async function readOfflineScope(key: CryptoKey, identity: OfflineScopeIdentity): Promise<VerifiedLocalScope | null> {
    const stored = await getRecord(identity);
    if (!stored) return null;
    const decrypted = await openLocalDraft(key, binding(identity, stored.snapshotId), stored.sealed);
    const trustedPublicKey = decrypted.trustedPublicKey;
    if (typeof trustedPublicKey !== "string") throw new ScopeError("invalid");
    const envelope = await verifyOfflineScope(decrypted.envelope, trustedPublicKey, identity);
    if (envelope.payload.snapshot_id !== stored.snapshotId) throw new ScopeError("invalid");
    return { envelope, trustedPublicKey };
}

/**
 * The first pin MUST originate from an authenticated online HTTPS response,
 * never an arbitrary IndexedDB envelope. Subsequent refreshes refuse rotation.
 */
export async function storeOfflineScope(
    key: CryptoKey, identity: OfflineScopeIdentity, envelope: unknown, onlineTrustedKey: string
): Promise<void> {
    const profile = await readLocalProfile();
    if (!profile || profile.ownerId !== identity.ownerId.toLowerCase() ||
        profile.deviceKey !== identity.deviceKey.toLowerCase()) throw new ScopeError("identity_mismatch");
    const verified = await verifyOfflineScope(envelope, onlineTrustedKey, identity);
    const earlier = await readOfflineScope(key, identity);
    if (earlier && earlier.trustedPublicKey !== onlineTrustedKey) throw new ScopeError("pin_mismatch");
    const snapshotId = verified.payload.snapshot_id;
    const sealed = await sealLocalDraft(key, binding(identity, snapshotId),
        { trustedPublicKey: onlineTrustedKey, envelope: verified });
    const db = await openProfileDb();
    try {
        await new Promise<void>((resolve, reject) => {
            const tx = db.transaction(["profiles", SCOPE_STORE_NAME], "readwrite");
            const scopes = tx.objectStore(SCOPE_STORE_NAME);
            let rejected: Error | undefined;
            const profileReq = tx.objectStore("profiles").get(id(identity));
            profileReq.onsuccess = () => {
                if (!profileReq.result || profileReq.result.ownerId !== identity.ownerId.toLowerCase() ||
                    profileReq.result.deviceKey !== identity.deviceKey.toLowerCase()) {
                    rejected = new ScopeError("identity_mismatch"); tx.abort(); return;
                }
                const request = scopes.get(id(identity));
                request.onsuccess = () => {
                    const previous = request.result as Stored | undefined;
                    if (previous && (!validStored(previous, identity) ||
                        previous.snapshotId !== earlier?.envelope.payload.snapshot_id)) {
                        rejected = new ScopeError("invalid"); tx.abort(); return;
                    }
                    scopes.put({
                        profileId: id(identity), ownerId: identity.ownerId.toLowerCase(),
                        deviceKey: identity.deviceKey.toLowerCase(), snapshotId, sealed
                    } satisfies Stored);
                };
            };
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(rejected ?? new ScopeError("unavailable"));
            tx.onabort = () => reject(rejected ?? new ScopeError("unavailable"));
        });
    } finally { db.close(); }
}
