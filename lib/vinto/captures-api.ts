import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { capturesListPath } from "@/lib/vinto/capture-core";
import { parseCapture, parseCaptureList, parseSubmission, type CapturePayload, type CaptureSubmission, type CentralCapture } from "@/lib/vinto/captures";

// Capturas centrales. Cookie HttpOnly vía requestJson (credentials "include", cache "no-store"); sin tokens manuales.
// El POST y la reconciliación llevan un tiempo límite: si vence, el resultado se trata como INCIERTO (no como no guardado).
// Las operaciones HTTP son GENÉRICAS (postCaptureOf / getCaptureOf / listCapturesOf): cada formulario aporta SU parser estricto, de modo que una respuesta de
// otro formulario nunca se acepta por error. Las funciones F6 de abajo conservan su API pública.

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

export function postCaptureOf<P, S>(payload: P, parse: (payload: unknown) => S | null): Promise<ApiResult<S>> {
    return requestJson("/api/captures", { method: "POST", body: payload, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, parse);
}

export function getCaptureOf<C>(captureId: string, parse: (payload: unknown) => C | null, signal?: AbortSignal): Promise<ApiResult<C>> {
    return requestJson(`/api/captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, parse);
}

// `formCode` solo se envía si se indica; el backend exige que el formulario esté habilitado (422 si no). El parser decide qué formulario se acepta.
export function listCapturesOf<C>(parse: (payload: unknown) => C[] | null, signal?: AbortSignal, limit = 50, formCode?: string): Promise<ApiResult<C[]>> {
    return requestJson(capturesListPath(limit, formCode), { signal }, parse);
}

// ---- F6 (VINTO-P1-06) ------------------------------------------------------------------------------------------------------------

export const submitCapture = (payload: CapturePayload): Promise<ApiResult<CaptureSubmission>> => postCaptureOf(payload, parseSubmission);
export const getCapture = (captureId: string, signal?: AbortSignal): Promise<ApiResult<CentralCapture>> => getCaptureOf(captureId, parseCapture, signal);
// Listado histórico F6: sin `form_code` (la URL no cambia) y con el parser F6. Otros formularios usan listCapturesOf con su propio parser.
export const listCaptures = (signal?: AbortSignal, limit = 50): Promise<ApiResult<CentralCapture[]>> => listCapturesOf(parseCaptureList, signal, limit);
