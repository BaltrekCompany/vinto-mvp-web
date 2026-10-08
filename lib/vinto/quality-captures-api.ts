import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseQualityCapture, parseQualityCaptureSubmission, type HumidityPayload, type QualityCapture, type QualityCaptureSubmission } from "@/lib/vinto/quality-captures";

// Capturas centrales de Calidad ligadas a una Bobina. Cookie HttpOnly vía requestJson (credentials "include"); sin tokens manuales.
// Si el POST vence por tiempo, el resultado es INCIERTO (no "no guardado"): se reconcilia con GET por capture_id o se reintenta el mismo POST.

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

export function submitQualityCapture(bobbinId: string, payload: HumidityPayload): Promise<ApiResult<QualityCaptureSubmission>> {
    return requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbinId)}/captures`, { method: "POST", body: payload, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, parseQualityCaptureSubmission);
}

export function getQualityCapture(captureId: string, signal?: AbortSignal): Promise<ApiResult<QualityCapture>> {
    return requestJson(`/api/quality/captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, parseQualityCapture);
}
