import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseAvailability, type Availability } from "@/lib/vinto/availability";
import type { CandidateCapture, CandidateForm, CandidatePayload, CandidateSubmission } from "@/lib/vinto/candidate-form";

// Cliente HTTP de un formulario candidato: las mismas operaciones genéricas que F6 y P1-10 (captures-api.ts), con el parser ESTRICTO del formulario (código esperado). Solo funciona contra un backend
// que publique el formulario para la máquina (hoy únicamente entornos de prueba).
export const candidateApi = (form: CandidateForm) => ({
    submit: (payload: CandidatePayload): Promise<ApiResult<CandidateSubmission>> => postCaptureOf(payload, form.parseSubmission),
    get: (captureId: string, signal?: AbortSignal): Promise<ApiResult<CandidateCapture>> => getCaptureOf(captureId, form.parseCapture, signal),
    list: (signal?: AbortSignal, limit = 50): Promise<ApiResult<CandidateCapture[]>> => listCapturesOf(form.parseList, signal, limit, form.code),
});

const POST_TIMEOUT_MS = 20000, GET_TIMEOUT_MS = 10000;

// Calidad POR MÁQUINA (DEV-Q1): sin bobina ni asignación. La máquina va en la ruta (no en el cuerpo); el listado se filtra por máquina y formulario. Cookie HttpOnly vía requestJson.
export const machineCandidateApi = (form: CandidateForm) => ({
    submit: (payload: CandidatePayload): Promise<ApiResult<CandidateSubmission>> => {
        const { machine_code: machine, ...body } = payload;
        return requestJson(`/api/quality/machines/${encodeURIComponent(machine ?? "")}/captures`, { method: "POST", body, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, form.parseSubmission);
    },
    get: (captureId: string, signal?: AbortSignal): Promise<ApiResult<CandidateCapture>> =>
        requestJson(`/api/quality/machine-captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, form.parseCapture),
    list: (machineCode: string, signal?: AbortSignal, limit = 50): Promise<ApiResult<CandidateCapture[]>> =>
        requestJson(`/api/quality/machines/${encodeURIComponent(machineCode)}/captures?form_code=${encodeURIComponent(form.code)}&limit=${limit}`, { signal }, form.parseList),
});

// Calidad ligada a UNA BOBINA física (DEV-Q2, P1-21): reutiliza las rutas de capturas de Calidad por bobina. La bobina va en la ruta (no en el cuerpo); el historial se filtra por formulario en el backend
// (un historial con otros formularios no pasaría el parser estricto de éste). Cookie HttpOnly vía requestJson.
export const bobbinCandidateApi = (form: CandidateForm) => ({
    submit: (payload: CandidatePayload): Promise<ApiResult<CandidateSubmission>> => {
        const { bobbin_id: bobbin, ...body } = payload;
        return requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbin ?? "")}/captures`, { method: "POST", body, signal: AbortSignal.timeout(POST_TIMEOUT_MS) }, form.parseSubmission);
    },
    get: (captureId: string, signal?: AbortSignal): Promise<ApiResult<CandidateCapture>> =>
        requestJson(`/api/quality/captures/${encodeURIComponent(captureId)}`, { signal: signal ?? AbortSignal.timeout(GET_TIMEOUT_MS) }, form.parseCapture),
    list: (bobbinId: string, signal?: AbortSignal): Promise<ApiResult<CandidateCapture[]>> =>
        requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbinId)}/captures?form_code=${encodeURIComponent(form.code)}`, { signal }, form.parseList),
});

// Candidatos de Calidad por bobina que el backend publica por máquina (vacío con la política real).
export function getQualityBobbinForms(signal?: AbortSignal): Promise<ApiResult<Availability>> {
    return requestJson("/api/quality/bobbin-forms", { signal }, parseAvailability);
}

// Máquinas del alcance y formularios de Calidad por máquina que el backend publica (vacío con la política real).
export function getQualityMachineForms(signal?: AbortSignal): Promise<ApiResult<Availability>> {
    return requestJson("/api/quality/machine-forms", { signal }, parseAvailability);
}
