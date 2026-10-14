import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_11_CODE, parseP111Capture, parseP111List, parseP111Submission, type P111Capture, type P111Payload, type P111Submission } from "@/lib/vinto/p1-11";

// Cliente de VINTO-P1-11 (candidato): las mismas operaciones HTTP genéricas que F6, P1-10, P1-12, P1-13 y P1-16 (captures-api.ts), con el parser ESTRICTO de P1-11 (código esperado «VINTO-P1-11»).
// Solo funciona contra un backend que habilite P1-11 (hoy solo entornos de prueba).

export const submitP111 = (payload: P111Payload): Promise<ApiResult<P111Submission>> => postCaptureOf(payload, parseP111Submission);
export const getP111 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P111Capture>> => getCaptureOf(captureId, parseP111Capture, signal);
export const listP111 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P111Capture[]>> => listCapturesOf(parseP111List, signal, limit, P1_11_CODE);
