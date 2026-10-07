import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseBobbin, parseBobbinSubmission, type BobbinPayload, type BobbinSubmission, type CentralBobbin } from "@/lib/vinto/bobbins";

// Producción de bobinas F3. Cookie HttpOnly vía requestJson (credentials "include", cache "no-store"); sin tokens manuales.
// Si el POST vence por tiempo, el resultado es INCIERTO (no "no guardado"): se reintenta el mismo POST con el mismo capture_id.

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

export function submitBobbin(payload: BobbinPayload): Promise<ApiResult<BobbinSubmission>> {
    return requestJson("/api/bobbins", { method: "POST", body: payload, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, parseBobbinSubmission);
}

// Lectura de una Bobbin ya conocida. NO se usa para reconciliar un POST incierto (antes de la primera respuesta no hay bobbin_id).
export function getBobbin(bobbinId: string, signal?: AbortSignal): Promise<ApiResult<CentralBobbin>> {
    return requestJson(`/api/bobbins/${encodeURIComponent(bobbinId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, parseBobbin);
}
