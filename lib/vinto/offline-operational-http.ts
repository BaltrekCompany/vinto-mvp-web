/** OFF-04.8: same-origin HTTP adapter for the operational Quality sync runtime.
 *
 * No implicit mounting, endpoint activation, service worker or background
 * writes. The caller supplies the authenticated origin and starts the runtime
 * explicitly. Browser credentials are session cookies, never a cached user ID.
 * All responses still pass createHttpSyncTransport integrity/operational-ACK
 * verification and syncNow's original-owner check.
 */
import {createHttpSyncTransport, type HttpCall} from "./offline-sync-http-transport.ts";
import type {SyncTransport} from "./offline-sync-types.ts";

export class OperationalHttpUnavailable extends Error {
  constructor() { super("offline_operational_http_unavailable"); }
}

export type OperationalHttpDeps = Readonly<{
  /** Same-origin URL prefix only. Cross-origin endpoints are never accepted. */
  origin: string;
  fetcher: typeof fetch;
}>;

export function createOperationalHttpTransport(deps: OperationalHttpDeps): SyncTransport {
  if (!deps.origin || !deps.fetcher) throw new OperationalHttpUnavailable();
  const origin = new URL(deps.origin);
  if (origin.pathname !== "/" || origin.search || origin.hash ||
      !["http:", "https:"].includes(origin.protocol))
    throw new OperationalHttpUnavailable();
  const http: HttpCall = async ({method, path, body, signal}) => {
    if (!/^\/api\/offline\/captures(?:\/[0-9a-f-]{36})?$/.test(path))
      throw new OperationalHttpUnavailable();
    const endpoint = new URL(path, origin);
    if (endpoint.origin !== origin.origin) throw new OperationalHttpUnavailable();
    const response = await deps.fetcher(endpoint.toString(), {
      method, signal, mode: "same-origin", credentials: "include",
      redirect: "error", cache: "no-store",
      headers: {Accept: "application/json", ...(method === "POST" ? {"Content-Type": "application/json"} : {})},
      ...(method === "POST" ? {body: JSON.stringify(body)} : {}),
    });
    const type = response.headers.get("content-type") ?? "";
    if (!type.toLowerCase().includes("application/json")) throw new OperationalHttpUnavailable();
    return {status: response.status, json: await response.json()};
  };
  return createHttpSyncTransport(http);
}
