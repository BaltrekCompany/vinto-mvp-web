/**
 * OFF-04.4 (LABORATORY / CI ONLY): adapter from the OFF-04.3 sync engine to the isolated FastAPI offline receiver.
 *
 * It does NOT call the network itself: the caller injects `http`, and the only callers are the disposable CI server and
 * ASGI-style test clients. It is never wired to the application, never points at a deployed API and is not enabled by default.
 *
 * Safety rules implemented here:
 *  - the capture_id (idempotency key) and the author id travel exactly as stored; nothing is regenerated or rewritten;
 *  - a reply counts as a confirmed central receipt ONLY if it echoes the same capture_id and checksum and carries a
 *    server reference with technical acceptance; anything else is treated as a conflict (never `synced`);
 *  - reconciliation (`lookup`) uses the same verification; any non-definitive answer is a transport error, so the engine keeps
 *    the record and retries later instead of resending blindly or marking it done.
 */
import { SyncTransportError, type LookupReply, type SyncReply, type SyncRequest, type SyncTransport } from "./offline-sync-types.ts";

export type HttpCall = (request: { method: "GET" | "POST"; path: string; body?: unknown; signal: AbortSignal }) => Promise<{ status: number; json: unknown }>;
const asObject = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {});
const UNVERIFIABLE: SyncReply = { status: 409, body: { outcome: "conflict", reason: "response_unverifiable" } };

async function call(http: HttpCall, request: Parameters<HttpCall>[0]): Promise<{ status: number; json: Record<string, unknown> }> {
    try {
        const r = await http(request);
        return { status: r.status, json: asObject(r.json) };
    } catch (error) {
        if ((error as { name?: string })?.name === "AbortError" || request.signal.aborted) throw new SyncTransportError("timeout");
        throw new SyncTransportError("network");
    }
}

const verified = (j: Record<string, unknown>, captureId: string, sha: string): boolean =>
    j.capture_id === captureId && j.payload_sha256 === sha && typeof j.server_id === "string" && j.server_id.length > 0 && j.technical_acceptance === true;

export function createHttpSyncTransport(http: HttpCall, basePath = "/api/offline/captures"): SyncTransport {
    return {
        async send(request: SyncRequest, options): Promise<SyncReply> {
            const r = await call(http, { method: "POST", path: basePath, body: request, signal: options.signal });
            const j = r.json;
            if (r.status === 200 || r.status === 201 || r.status === 202) {
                if (!verified(j, request.capture_id, request.payload_sha256)) return UNVERIFIABLE;
                if ((r.status === 202) !== (j.outcome === "review")) return UNVERIFIABLE;
                if (j.operational_registered !== undefined && typeof j.operational_registered !== "boolean") return UNVERIFIABLE;
                if (j.operational_registered === true && j.operational_capture_id !== request.capture_id) return UNVERIFIABLE;
                return { status: r.status, body: { outcome: j.outcome as never, server_id: j.server_id as string, warnings: (j.warnings as string[]) ?? [], reason: (j.reason as string) ?? undefined,
                    ...(typeof j.operational_registered === "boolean" ? { operational_registered: j.operational_registered } : {}),
                    ...(j.operational_registered === true ? { operational_capture_id: request.capture_id } : {}) } };
            }
            return { status: r.status, body: { outcome: (j.outcome as never) ?? "error", reason: (j.reason as string) ?? undefined } };
        },
        async lookup(captureId: string, options): Promise<LookupReply> {
            const r = await call(http, { method: "GET", path: basePath + "/" + captureId, signal: options.signal });
            if (r.status === 404 && r.json.found === false) return { found: false };
            if (r.status === 200 && r.json.found === true && r.json.capture_id === captureId && typeof r.json.server_id === "string" && r.json.industrial_approval === false &&
                ["accepted", "accepted_warning", "review", "conflict"].includes(r.json.outcome as string)) {
                if (r.json.operational_registered !== undefined && typeof r.json.operational_registered !== "boolean") throw new SyncTransportError("network");
                if (r.json.operational_registered === true && r.json.operational_capture_id !== captureId) throw new SyncTransportError("network");
                return { found: true, outcome: r.json.outcome as never, server_id: r.json.server_id, warnings: (r.json.warnings as string[]) ?? [], reason: (r.json.reason as string) ?? undefined,
                    ...(typeof r.json.operational_registered === "boolean" ? { operational_registered: r.json.operational_registered } : {}),
                    ...(r.json.operational_registered === true ? { operational_capture_id: captureId } : {}) };
            }
            throw new SyncTransportError("network");          // not a definitive answer (401, 5xx, malformed): never assume found or not found
        },
    };
}
