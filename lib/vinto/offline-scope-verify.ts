/**
 * VINTO OFF-03B.3: verify a signed, read-only scope under an EXISTING trust pin.
 *
 * First trust pin is received over a successful authenticated online HTTPS
 * session and sealed with the local vault. NEVER trust a key solely because it
 * comes inside an offline/IndexedDB envelope. Signature != current permission.
 */
const FORMAT = "vinto.offline.scope.v1";
const ENVELOPE_KEYS = ["algorithm","key_id","public_key_b64url","payload","signature_b64url"];
const PAYLOAD_KEYS = ["audience","captures_enabled","device_key","form_scopes","issued_at","issuer","kind","schema","snapshot_id","subject_user_id"];
const FORM_KEYS = ["form_code","form_version","grant_id","machine_code","operation"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FORM = /^VINTO-[A-Z0-9-]{2,40}$/;
const MACHINE = /^[A-Za-z0-9_.-]{1,48}$/;
const KEY_ID = /^ed25519-[0-9a-f]{20}$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const OPS = new Set(["production_capture", "bobbin_production", "quality_bobbin_capture", "quality_machine_capture"]);
const DOMAIN = "VINTO-OFFLINE-SCOPE-V1\0";
const encoder = new TextEncoder();

export type OfflineScopeIdentity = Readonly<{ ownerId: string; deviceKey: string }>;
export type FormScope = Readonly<{
    machine_code: string;
    form_code: string;
    form_version: number;
    grant_id: string;
    operation: string;
}>;
export type SignedOfflineScope = Readonly<{
    algorithm: "Ed25519";
    key_id: string;
    public_key_b64url: string;
    signature_b64url: string;
    payload: {
        schema: typeof FORMAT;
        issuer: "vinto-backend";
        audience: "vinto-offline-readiness";
        snapshot_id: string;
        subject_user_id: string;
        device_key: string;
        issued_at: string;
        kind: "scope_readiness_only";
        captures_enabled: false;
        form_scopes: FormScope[];
    };
}>;
export class ScopeError extends Error {
    readonly reason: "invalid" | "identity_mismatch" | "pin_mismatch" | "signature" | "unavailable";
    constructor(reason: ScopeError["reason"]) {
        super("OFFLINE_SCOPE_" + reason.toUpperCase());
        this.name = "ScopeError";
        this.reason = reason;
    }
}
type R = Record<string, unknown>;
function record(v: unknown): v is R {
    return v !== null && typeof v === "object" && !Array.isArray(v);
}
function exact(v: unknown, keys: readonly string[]): v is R {
    return record(v) && Object.keys(v).sort().join("|") === [...keys].sort().join("|");
}
function b64decode(value: string, expected: number): Uint8Array {
    if (!B64URL.test(value)) throw new ScopeError("invalid");
    let bytes: Uint8Array;
    try {
        const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "="));
        bytes = Uint8Array.from(raw, x => x.charCodeAt(0));
    } catch { throw new ScopeError("invalid"); }
    if (bytes.length !== expected || b64encode(bytes) !== value) throw new ScopeError("invalid");
    return bytes;
}
function b64encode(raw: Uint8Array): string {
    let binary = "";
    for (const x of raw) binary += String.fromCharCode(x);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export function canonicalOfflineJson(value: unknown): string {
    if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
    if (typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map(canonicalOfflineJson).join(",") + "]";
    if (!record(value)) throw new ScopeError("invalid");
    return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonicalOfflineJson(value[k])).join(",") + "}";
}
function validate(value: unknown, identity: OfflineScopeIdentity): asserts value is SignedOfflineScope {
    if (!exact(value, ENVELOPE_KEYS) || value.algorithm !== "Ed25519" ||
        typeof value.key_id !== "string" || !KEY_ID.test(value.key_id) ||
        typeof value.public_key_b64url !== "string" ||
        typeof value.signature_b64url !== "string" || !exact(value.payload, PAYLOAD_KEYS)) throw new ScopeError("invalid");
    const p = value.payload;
    if (p.schema !== FORMAT || p.issuer !== "vinto-backend" || p.audience !== "vinto-offline-readiness" ||
        p.kind !== "scope_readiness_only" || p.captures_enabled !== false ||
        typeof p.snapshot_id !== "string" || !UUID.test(p.snapshot_id) ||
        typeof p.subject_user_id !== "string" || !UUID.test(p.subject_user_id) ||
        typeof p.device_key !== "string" || !UUID.test(p.device_key) ||
        typeof p.issued_at !== "string" || !UTC.test(p.issued_at) || !Number.isFinite(Date.parse(p.issued_at))) throw new ScopeError("invalid");
    if (p.subject_user_id.toLowerCase() !== identity.ownerId.toLowerCase() ||
        p.device_key.toLowerCase() !== identity.deviceKey.toLowerCase()) throw new ScopeError("identity_mismatch");
    if (!Array.isArray(p.form_scopes) || p.form_scopes.length < 1 || p.form_scopes.length > 200) throw new ScopeError("invalid");
    const unique = new Set<string>();
    for (const entry of p.form_scopes) {
        if (!exact(entry, FORM_KEYS) || typeof entry.machine_code !== "string" || !MACHINE.test(entry.machine_code) ||
            typeof entry.form_code !== "string" || !FORM.test(entry.form_code) ||
            !Number.isSafeInteger(entry.form_version) || (entry.form_version as number) < 1 ||
            typeof entry.grant_id !== "string" || !UUID.test(entry.grant_id) ||
            typeof entry.operation !== "string" || !OPS.has(entry.operation)) throw new ScopeError("invalid");
        const id = [entry.machine_code, entry.form_code, entry.operation].join(":");
        if (unique.has(id)) throw new ScopeError("invalid");
        unique.add(id);
    }
}
/** Explicit pin is required; the embedded public_key alone is NEVER trusted. */
export async function verifyOfflineScope(input: unknown, trustedPublicKey: string, identity: OfflineScopeIdentity): Promise<SignedOfflineScope> {
    if (!globalThis.crypto?.subtle || !globalThis.crypto.getRandomValues) throw new ScopeError("unavailable");
    if (!identity || typeof identity.ownerId !== "string" || !UUID.test(identity.ownerId) ||
        typeof identity.deviceKey !== "string" || !UUID.test(identity.deviceKey)) throw new ScopeError("invalid");
    validate(input, identity);
    if (typeof trustedPublicKey !== "string" || input.public_key_b64url !== trustedPublicKey) throw new ScopeError("pin_mismatch");
    const pub = b64decode(trustedPublicKey, 32);
    const sig = b64decode(input.signature_b64url, 64);
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", pub as BufferSource));
    const computedKeyId = "ed25519-" + Array.from(hash.slice(0, 10), b => b.toString(16).padStart(2, "0")).join("");
    if (input.key_id !== computedKeyId) throw new ScopeError("pin_mismatch");
    try {
        const key = await crypto.subtle.importKey("raw", pub as BufferSource, { name: "Ed25519" }, false, ["verify"]);
        const bytes = encoder.encode(DOMAIN + canonicalOfflineJson(input.payload));
        const ok = await crypto.subtle.verify({ name: "Ed25519" }, key, sig as BufferSource, bytes as BufferSource);
        if (!ok) throw new ScopeError("signature");
    } catch (err) {
        if (err instanceof ScopeError) throw err;
        throw new ScopeError("unavailable");
    }
    return input;
}
