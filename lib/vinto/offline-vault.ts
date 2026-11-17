/**
 * VINTO OFF-03A -- EXPERIMENTAL offline vault primitive.
 *
 * This cryptography DOES NOT authorize industrial actions or replace the server
 * session. No production UI should call it before signed grants, device QA,
 * human review of passphrase resistance and explicit operational approval.
 *
 * Each browser is a distinct compartment. A high-entropy LOCAL passphrase
 * wraps a random AES-256 content key. The unwrap key is derived with PBKDF2.
 * Offline guesses against a stolen browser database cannot be rate limited by
 * JS: this is a bounded prototype, not a substitute for hardware-backed keys.
 */
import type { SealedValues } from "./offline-store";

export const VAULT_ALGORITHM = "pbkdf2-sha256-aes256gcm-v1" as const;
export const VAULT_ITERATIONS = 650_000;
export const LOCAL_PASSPHRASE_MIN = 16;
export const LOCAL_PASSPHRASE_MAX = 256;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ALLOWED_B64 = /^[A-Za-z0-9_-]+$/;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const MAX_PAYLOAD_BYTES = 1024 * 1024;

export type OfflineVaultIdentity = Readonly<{ ownerId: string; deviceKey: string }>;
export type OfflineVaultRecord = OfflineVaultIdentity & Readonly<{
    format: typeof VAULT_ALGORITHM;
    iterations: typeof VAULT_ITERATIONS;
    salt: string;
    wrapIv: string;
    wrappedKey: string;
}>;
export type DraftBinding = OfflineVaultIdentity & Readonly<{
    id: string;
    contextId: string;
    formCode: string;
    formVersion: number;
}>;

export class VaultError extends Error {
    readonly reason: "unavailable" | "invalid" | "weak_passphrase" | "unlock_failed" | "corrupt";
    constructor(reason: VaultError["reason"]) {
        super(`OFFLINE_VAULT_${reason.toUpperCase()}`);
        this.name = "VaultError";
        this.reason = reason;
    }
}

function requireCrypto(): SubtleCrypto {
    if (typeof crypto === "undefined" || !crypto.subtle || !crypto.getRandomValues) {
        throw new VaultError("unavailable");
    }
    return crypto.subtle;
}

function bytesToBase64Url(raw: Uint8Array): string {
    let text = "";
    for (const b of raw) text += String.fromCharCode(b);
    return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string, expected?: number): Uint8Array {
    if (!ALLOWED_B64.test(value)) throw new VaultError("corrupt");
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    let result: Uint8Array;
    try {
        result = Uint8Array.from(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
    } catch {
        throw new VaultError("corrupt");
    }
    if (expected !== undefined && result.length !== expected) throw new VaultError("corrupt");
    if (bytesToBase64Url(result) !== value) throw new VaultError("corrupt");
    return result;
}

function requireIdentity(value: OfflineVaultIdentity): void {
    if (!value || typeof value.ownerId !== "string" || !UUID.test(value.ownerId)
        || typeof value.deviceKey !== "string" || !UUID.test(value.deviceKey)) throw new VaultError("invalid");
}

function requirePassphrase(passphrase: string): void {
    if (typeof passphrase !== "string" || passphrase.length < LOCAL_PASSPHRASE_MIN
        || passphrase.length > LOCAL_PASSPHRASE_MAX || /[\u0000-\u001f\u007f]/u.test(passphrase)) {
        throw new VaultError("weak_passphrase");
    }
    // This is a MINIMUM strength gate. No short PIN, no repeated single character.
    if (new Set(Array.from(passphrase)).size < 8) throw new VaultError("weak_passphrase");
}

function aad(identity: OfflineVaultIdentity): Uint8Array {
    return encoder.encode(`VINTO:OFF03A:v1:${identity.ownerId.toLowerCase()}:${identity.deviceKey.toLowerCase()}`);
}

function captureAad(binding: DraftBinding): Uint8Array {
    requireIdentity(binding);
    if (!UUID.test(binding.id) || !UUID.test(binding.contextId)
        || !/^VINTO-[A-Z0-9-]{2,40}$/.test(binding.formCode)
        || !Number.isSafeInteger(binding.formVersion) || binding.formVersion < 1) {
        throw new VaultError("invalid");
    }
    return encoder.encode([
        "VINTO:OFF03A:CAPTURE:v1",binding.ownerId.toLowerCase(),
        binding.deviceKey.toLowerCase(),binding.id.toLowerCase(),
        binding.contextId.toLowerCase(),binding.formCode,binding.formVersion
    ].join(":"));
}

async function deriveWrapKey(passphrase: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
    const subtle = requireCrypto();
    const material = await subtle.importKey("raw", encoder.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
    return subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: salt as BufferSource, iterations },
        material, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isOfflineVaultRecord(value: unknown): value is OfflineVaultRecord {
    if (!isRecord(value)) return false;
    const { ownerId, deviceKey, format, iterations, salt, wrapIv, wrappedKey } = value;
    return typeof ownerId === "string" && UUID.test(ownerId) && typeof deviceKey === "string" && UUID.test(deviceKey)
        && format === VAULT_ALGORITHM && iterations === VAULT_ITERATIONS
        && typeof salt === "string" && salt.length === 22 && ALLOWED_B64.test(salt)
        && typeof wrapIv === "string" && wrapIv.length === 16 && ALLOWED_B64.test(wrapIv)
        && typeof wrappedKey === "string" && wrappedKey.length === 64 && ALLOWED_B64.test(wrappedKey);
}

/** Only call after authenticated online enrollment and an explicit consent/gate. */
export async function createLocalVault(identity: OfflineVaultIdentity, localPassphrase: string): Promise<{
    record: OfflineVaultRecord; key: CryptoKey;
}> {
    requireIdentity(identity);
    requirePassphrase(localPassphrase);
    const subtle = requireCrypto();
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const rawKey = crypto.getRandomValues(new Uint8Array(32));
    try {
        const wrapKey = await deriveWrapKey(localPassphrase, salt, VAULT_ITERATIONS);
        const encrypted = await subtle.encrypt(
            { name: "AES-GCM", iv, additionalData: aad(identity) as BufferSource },
            wrapKey, rawKey);
        const key = await subtle.importKey("raw", rawKey, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
        return {
            record: {
                ownerId: identity.ownerId.toLowerCase(), deviceKey: identity.deviceKey.toLowerCase(),
                format: VAULT_ALGORITHM, iterations: VAULT_ITERATIONS,
                salt: bytesToBase64Url(salt), wrapIv: bytesToBase64Url(iv),
                wrappedKey: bytesToBase64Url(new Uint8Array(encrypted)),
            },
            key,
        };
    } finally {
        rawKey.fill(0); // best-effort memory hygiene, cannot guarantee GC copies are erased
    }
}

/** Offline unlocking intentionally makes NO network call and produces NO session cookie. */
export async function unlockLocalVault(record: OfflineVaultRecord, localPassphrase: string): Promise<CryptoKey> {
    if (!isOfflineVaultRecord(record)) throw new VaultError("corrupt");
    if (typeof localPassphrase !== "string") throw new VaultError("unlock_failed");
    const subtle = requireCrypto();
    const salt = base64UrlToBytes(record.salt, 16);
    const iv = base64UrlToBytes(record.wrapIv, 12);
    const wrapped = base64UrlToBytes(record.wrappedKey, 48);
    try {
        const wrapKey = await deriveWrapKey(localPassphrase, salt, record.iterations);
        const decrypted = new Uint8Array(await subtle.decrypt({
            name: "AES-GCM", iv: iv as BufferSource, additionalData: aad(record) as BufferSource
        }, wrapKey, wrapped as BufferSource));
        try {
            if (decrypted.length !== 32) throw new VaultError("corrupt");
            return await subtle.importKey("raw", decrypted, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
        } finally {
            decrypted.fill(0);
        }
    } catch {
        // Same message for incorrect passphrase and authenticated wrap corruption.
        throw new VaultError("unlock_failed");
    }
}

export async function sealLocalDraft(key: CryptoKey, binding: DraftBinding, payload: unknown): Promise<SealedValues> {
    const subtle = requireCrypto();
    const extra = captureAad(binding);
    let json: string;
    try { json = JSON.stringify(payload); }
    catch { throw new VaultError("invalid"); }
    if (typeof json !== "string" || json === "null" || !isRecord(payload)) throw new VaultError("invalid");
    const clear = encoder.encode(json);
    if (clear.length > MAX_PAYLOAD_BYTES) throw new VaultError("invalid");
    const iv = crypto.getRandomValues(new Uint8Array(12));
    try {
        const ciphertext = await subtle.encrypt({ name: "AES-GCM", iv, additionalData: extra as BufferSource }, key, clear);
        return { format: "aes-gcm-v1", iv: bytesToBase64Url(iv), ciphertext: bytesToBase64Url(new Uint8Array(ciphertext)) };
    } catch { throw new VaultError("invalid"); }
    finally { clear.fill(0); }
}

export async function openLocalDraft(key: CryptoKey, binding: DraftBinding, sealed: SealedValues): Promise<Record<string, unknown>> {
    const subtle = requireCrypto();
    const extra = captureAad(binding);
    if (sealed?.format !== "aes-gcm-v1" || typeof sealed.iv !== "string" || typeof sealed.ciphertext !== "string") {
        throw new VaultError("corrupt");
    }
    const iv = base64UrlToBytes(sealed.iv, 12);
    const raw = base64UrlToBytes(sealed.ciphertext);
    if (raw.length <= 16 || raw.length > MAX_PAYLOAD_BYTES + 16) throw new VaultError("corrupt");
    let clear: Uint8Array;
    try {
        clear = new Uint8Array(await subtle.decrypt(
            { name: "AES-GCM", iv: iv as BufferSource, additionalData: extra as BufferSource }, key, raw as BufferSource));
    } catch { throw new VaultError("unlock_failed"); }
    try {
        const obj: unknown = JSON.parse(decoder.decode(clear));
        if (!isRecord(obj)) throw new VaultError("corrupt");
        return obj;
    } catch { throw new VaultError("corrupt"); }
    finally { clear.fill(0); }
}
