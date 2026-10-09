import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parsePhysicalCapture, parsePhysicalCaptureSubmission, type PhysicalCapture, type PhysicalCaptureSubmission, type PhysicalPayload } from "@/lib/vinto/quality-physical";

// VINTO-P1-20 por los endpoints centrales EXISTENTES de Calidad (los mismos de P1-19), con los parsers estrictos de P1-20. Cookie HttpOnly vía
// requestJson (credentials "include"); sin tokens manuales. Si el POST vence por tiempo, el resultado es INCIERTO: se reconcilia con GET.

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

export function submitPhysicalCapture(bobbinId: string, payload: PhysicalPayload): Promise<ApiResult<PhysicalCaptureSubmission>> {
    return requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbinId)}/captures`, { method: "POST", body: payload, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, parsePhysicalCaptureSubmission);
}

export function getPhysicalCapture(captureId: string, signal?: AbortSignal): Promise<ApiResult<PhysicalCapture>> {
    return requestJson(`/api/quality/captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, parsePhysicalCapture);
}
