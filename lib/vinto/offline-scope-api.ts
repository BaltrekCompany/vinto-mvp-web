/** OFF-03B.3: online-only read-only scope issuance, never a capture API. */
import { apiBaseUrl } from "./api";
import type { SignedOfflineScope } from "./offline-scope-verify";

export class ScopeFetchError extends Error {
    constructor() { super("No se pudo obtener un alcance firmado en una sesión online segura."); }
}
/** Dev loopback is allowed for CI; deployed browsers require real HTTPS. */
function secureEndpoint(url: URL): boolean {
    if (url.protocol === "https:") return true;
    if (process.env.NODE_ENV !== "development") return false;
    return url.protocol === "http:" && ["localhost","127.0.0.1","[::1]"].includes(url.hostname);
}
export async function issueOnlineReadinessScope(deviceKey: string, machineCodes: string[]): Promise<SignedOfflineScope> {
    const url = new URL(apiBaseUrl() + "/api/offline/scope");
    if (!window.isSecureContext || !secureEndpoint(url)) throw new ScopeFetchError();
    let response: Response;
    try {
        response = await fetch(url, {
            method: "POST", cache: "no-store", credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_key: deviceKey, machine_codes: machineCodes })
        });
    } catch { throw new ScopeFetchError(); }
    if (!response.ok || response.headers.get("Cache-Control")?.toLowerCase().includes("no-store") !== true)
        throw new ScopeFetchError();
    let payload: unknown;
    try { payload = await response.json(); } catch { throw new ScopeFetchError(); }
    if (typeof payload !== "object" || payload === null || Array.isArray(payload) ||
        !("public_key_b64url" in payload) || typeof payload.public_key_b64url !== "string") throw new ScopeFetchError();
    // Structural and signature validation occurs BEFORE storage by storeOfflineScope.
    return payload as SignedOfflineScope;
}
