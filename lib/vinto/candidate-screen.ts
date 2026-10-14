// Configuración de una pantalla central candidata (Bobinas o Calidad): lo mínimo que necesitan la pantalla de captura y el historial genéricos. Solo tipos.
import type { CandidateCapture, CandidateForm, CandidatePayload, CandidateSubmission } from "./candidate-form.ts";

export type CandidateApiResult<T> = { ok: true; data: T; status: number } | { ok: false; kind: string; status: number; code?: string };

export type CandidateScreen = {
    code: string;
    form: CandidateForm;
    api: { submit: (payload: CandidatePayload) => Promise<CandidateApiResult<CandidateSubmission>>; get: (captureId: string, signal?: AbortSignal) => Promise<CandidateApiResult<CandidateCapture>> };
    kicker: string;
    title: string; // título de la captura y del historial
    automatic: readonly string[]; // campos automáticos de la definición legacy (no se digitan)
    pending: readonly { label: string; pending: string }[]; // decisiones pendientes de VINTO
    unresolved?: readonly string[]; // campos automáticos de la definición SIN fuente confirmada (no se generan)
    calculated?: readonly string[]; // campos calculados de la definición sin fórmula aprobada (no se calculan ni se muestran)
    historyNote: string;
};
