import { getCaptureOf, listCapturesOf, postCaptureOf } from "@/lib/vinto/captures-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { P1_16_CODE, parseP116Capture, parseP116List, parseP116Submission, type P116Capture, type P116Payload, type P116Submission } from "@/lib/vinto/p1-16";

// Cliente de VINTO-P1-16 (candidato): las mismas operaciones HTTP genéricas que F6 y P1-10 (captures-api.ts), con el parser ESTRICTO de P1-16 (código esperado «VINTO-P1-16»).
// Solo funciona contra un backend que habilite P1-16 (hoy solo entornos de prueba).

export const submitP116 = (payload: P116Payload): Promise<ApiResult<P116Submission>> => postCaptureOf(payload, parseP116Submission);
export const getP116 = (captureId: string, signal?: AbortSignal): Promise<ApiResult<P116Capture>> => getCaptureOf(captureId, parseP116Capture, signal);
export const listP116 = (signal?: AbortSignal, limit = 50): Promise<ApiResult<P116Capture[]>> => listCapturesOf(parseP116List, signal, limit, P1_16_CODE);
