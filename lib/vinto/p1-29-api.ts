import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_29_CODE, parseP129Capture, parseP129List, parseP129Submission, type P129Capture, type P129Payload, type P129Submission } from "@/lib/vinto/p1-29";

// Cliente de VINTO-P1-29: las mismas operaciones HTTP genéricas que F6 y P1-10 (captures-api.ts) con el parser ESTRICTO de P1-29 (código esperado «VINTO-P1-29»).
// Una respuesta de otro formulario no puede confundirse con una de P1-29 ni al revés. Solo funciona contra un backend que habilite P1-29 (hoy solo entornos de prueba).

export const submitP129 = (payload: P129Payload): Promise<ApiResult<P129Submission>> => postCaptureOf(payload, parseP129Submission);
export const getP129 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P129Capture>> => getCaptureOf(captureId, parseP129Capture, signal);
export const listP129 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P129Capture[]>> => listCapturesOf(parseP129List, signal, limit, P1_29_CODE);
