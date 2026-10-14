import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import type { CandidateCapture, CandidateForm, CandidatePayload, CandidateSubmission } from "@/lib/vinto/candidate-form";

// Cliente HTTP de un formulario candidato: las mismas operaciones genéricas que F6 y P1-10 (captures-api.ts), con el parser ESTRICTO del formulario (código esperado). Solo funciona contra un backend
// que publique el formulario para la máquina (hoy únicamente entornos de prueba).
export const candidateApi = (form: CandidateForm) => ({
    submit: (payload: CandidatePayload): Promise<ApiResult<CandidateSubmission>> => postCaptureOf(payload, form.parseSubmission),
    get: (captureId: string, signal?: AbortSignal): Promise<ApiResult<CandidateCapture>> => getCaptureOf(captureId, form.parseCapture, signal),
    list: (signal?: AbortSignal, limit = 50): Promise<ApiResult<CandidateCapture[]>> => listCapturesOf(form.parseList, signal, limit, form.code),
});
