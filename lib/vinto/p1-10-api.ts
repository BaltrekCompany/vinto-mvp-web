import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_10_CODE, parseP110Capture, parseP110List, parseP110Submission, type P110Capture, type P110Payload, type P110Submission } from "@/lib/vinto/p1-10";

// Cliente de VINTO-P1-10: las mismas operaciones HTTP genéricas que F6 (captures-api.ts), con el parser ESTRICTO de P1-10 (código esperado «VINTO-P1-10»).
// Una respuesta de F6 no puede confundirse con una de P1-10 ni al revés. Solo funciona contra un backend que habilite P1-10 (hoy solo entornos de prueba).

export const submitP110 = (payload: P110Payload): Promise<ApiResult<P110Submission>> => postCaptureOf(payload, parseP110Submission);
export const getP110 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P110Capture>> => getCaptureOf(captureId, parseP110Capture, signal);
export const listP110 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P110Capture[]>> => listCapturesOf(parseP110List, signal, limit, P1_10_CODE);
