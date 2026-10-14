import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_12_CODE, parseP112Capture, parseP112List, parseP112Submission, type P112Capture, type P112Payload, type P112Submission } from "@/lib/vinto/p1-12";

// Cliente de VINTO-P1-12 (candidato): las mismas operaciones HTTP genéricas que F6, P1-10 y P1-16 (captures-api.ts), con el parser ESTRICTO de P1-12 (código esperado «VINTO-P1-12»).
// Solo funciona contra un backend que habilite P1-12 (hoy solo entornos de prueba).

export const submitP112 = (payload: P112Payload): Promise<ApiResult<P112Submission>> => postCaptureOf(payload, parseP112Submission);
export const getP112 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P112Capture>> => getCaptureOf(captureId, parseP112Capture, signal);
export const listP112 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P112Capture[]>> => listCapturesOf(parseP112List, signal, limit, P1_12_CODE);
