/** OFF-04.8: authenticated, same-origin operational HTTP transport.
 *
 * Isolated from the OFF-04.3 synthetic laboratory. Importing this module
 * never starts a sender, changes PWA routes or enables the FastAPI receiver.
 * A technical receipt is NEVER an operational acknowledgement.
 */
import {SyncTransportError, type LookupReply, type SyncReply, type SyncRequest, type SyncTransport}
  from "./offline-sync-types.ts";

export class OperationalHttpUnavailable extends Error {
  constructor() { super("offline_operational_http_unavailable"); }
}

export type OperationalHttpDeps = Readonly<{
  origin: string;
  fetcher: typeof fetch;
}>;

type JsonObject = Record<string, unknown>;
const object = (value: unknown): JsonObject | null =>
  value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : null;
const mismatch = () => new SyncTransportError("network");

export function createOperationalHttpTransport(deps: OperationalHttpDeps): SyncTransport {
  if (!deps.origin || typeof deps.fetcher !== "function") throw new OperationalHttpUnavailable();
  let origin: URL;
  try { origin = new URL(deps.origin); }
  catch { throw new OperationalHttpUnavailable(); }
  if (origin.pathname !== "/" || origin.search || origin.hash ||
      !["http:", "https:"].includes(origin.protocol) ||
      origin.username || origin.password) throw new OperationalHttpUnavailable();

  const request = async (method: "GET" | "POST", path: string, signal: AbortSignal, body?: unknown) => {
    if (!/^\/api\/offline\/captures(?:\/[0-9a-f-]{36})?$/.test(path))
      throw new OperationalHttpUnavailable();
    const url = new URL(path, origin);
    if (url.origin !== origin.origin) throw new OperationalHttpUnavailable();
    try {
      const result = await deps.fetcher(url.toString(), {
        method, signal, mode: "same-origin", credentials: "include",
        redirect: "error", cache: "no-store",
        headers: {Accept: "application/json", ...(method === "POST" ? {"Content-Type": "application/json"} : {})},
        ...(method === "POST" ? {body: JSON.stringify(body)} : {}),
      });
      if (!(result.headers.get("content-type") ?? "").toLowerCase().includes("application/json"))
        throw mismatch();
      const json = object(await result.json());
      if (!json) throw mismatch();
      return {status: result.status, json};
    } catch (error) {
      if (error instanceof SyncTransportError) throw error;
      if ((error as {name?: string})?.name === "AbortError" || signal.aborted)
        throw new SyncTransportError("timeout");
      throw mismatch();
    }
  };

  return {
    async send(capture: SyncRequest, options): Promise<SyncReply> {
      const {status, json} = await request("POST", "/api/offline/captures", options.signal, capture);
      if ([200, 201, 202].includes(status)) {
        if (json.capture_id !== capture.capture_id ||
            json.payload_sha256 !== capture.payload_sha256 ||
            typeof json.server_id !== "string" || !json.server_id ||
            json.technical_acceptance !== true ||
            ((status === 202) !== (json.outcome === "review")) ||
            (json.operational_registered !== undefined &&
             typeof json.operational_registered !== "boolean") ||
            (json.operational_registered === true &&
             json.operational_capture_id !== capture.capture_id))
          return {status:409, body:{outcome:"conflict",reason:"response_unverifiable"}};
        return {status, body:{
          outcome: json.outcome as "created" | "duplicate" | "review",
          server_id: json.server_id,
          warnings: Array.isArray(json.warnings) ? json.warnings as string[] : [],
          reason: typeof json.reason === "string" ? json.reason : undefined,
          ...(typeof json.operational_registered === "boolean" ?
            {operational_registered: json.operational_registered} : {}),
          ...(json.operational_registered === true ?
            {operational_capture_id: capture.capture_id} : {}),
        }};
      }
      return {status, body:{
        outcome: typeof json.outcome === "string" ? json.outcome as "error" : "error",
        reason: typeof json.reason === "string" ? json.reason : undefined,
      }};
    },
    async lookup(captureId: string, options): Promise<LookupReply> {
      const {status, json} = await request("GET", "/api/offline/captures/" + captureId, options.signal);
      if (status === 404 && json.found === false) return {found:false};
      if (status !== 200 || json.found !== true ||
          json.capture_id !== captureId ||
          typeof json.server_id !== "string" || !json.server_id ||
          json.industrial_approval !== false ||
          !["accepted","accepted_warning","review","conflict"].includes(json.outcome as string) ||
          (json.operational_registered !== undefined &&
           typeof json.operational_registered !== "boolean") ||
          (json.operational_registered === true &&
           json.operational_capture_id !== captureId))
        throw mismatch();
      return {found:true,
        outcome:json.outcome as "accepted" | "accepted_warning" | "review" | "conflict",
        server_id:json.server_id,
        warnings:Array.isArray(json.warnings) ? json.warnings as string[] : [],
        reason:typeof json.reason === "string" ? json.reason : undefined,
        ...(typeof json.operational_registered === "boolean" ?
          {operational_registered:json.operational_registered} : {}),
        ...(json.operational_registered === true ? {operational_capture_id:captureId} : {}),
      };
    },
  };
}
