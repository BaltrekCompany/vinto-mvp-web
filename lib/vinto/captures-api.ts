import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseCapture, parseCaptureList, parseSubmission, type CapturePayload, type CaptureSubmission, type CentralCapture } from "@/lib/vinto/captures";

// Capturas centrales F6. Cookie HttpOnly vía requestJson (credentials "include", cache "no-store"); sin tokens manuales.
// El POST y la reconciliación llevan un tiempo límite: si vence, el resultado se trata como INCIERTO (no como no guardado).

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

export function submitCapture(payload: CapturePayload): Promise<ApiResult<CaptureSubmission>> {
    return requestJson("/api/captures", { method: "POST", body: payload, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, parseSubmission);
}

export function getCapture(captureId: string, signal?: AbortSignal): Promise<ApiResult<CentralCapture>> {
    return requestJson(`/api/captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, parseCapture);
}

export function listCaptures(signal?: AbortSignal, limit = 50): Promise<ApiResult<CentralCapture[]>> {
    return requestJson(`/api/captures?limit=${limit}`, { signal }, parseCaptureList);
}

