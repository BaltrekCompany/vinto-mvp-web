import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_13_CODE, parseP113Capture, parseP113List, parseP113Submission, type P113Capture, type P113Payload, type P113Submission } from "@/lib/vinto/p1-13";

// Cliente de VINTO-P1-13 (candidato): las mismas operaciones HTTP genéricas que F6, P1-10, P1-12 y P1-16 (captures-api.ts), con el parser ESTRICTO de P1-13 (código esperado «VINTO-P1-13»).
// Solo funciona contra un backend que habilite P1-13 (hoy solo entornos de prueba).

export const submitP113 = (payload: P113Payload): Promise<ApiResult<P113Submission>> => postCaptureOf(payload, parseP113Submission);
export const getP113 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P113Capture>> => getCaptureOf(captureId, parseP113Capture, signal);
export const listP113 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P113Capture[]>> => listCapturesOf(parseP113List, signal, limit, P1_13_CODE);
