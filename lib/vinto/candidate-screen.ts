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
    bobbinCodeField?: string; // contexto "bobbin": campo manual que declara el número de bobina; se precarga con el código de la bobina seleccionada y el backend rechaza cualquier otro valor
    unresolved?: readonly string[]; // campos automáticos de la definición SIN fuente confirmada (no se generan)
    calculated?: readonly string[]; // campos calculados de la definición sin fórmula aprobada (no se calculan ni se muestran)
    sections?: readonly { title: string; hint?: string; keys: readonly string[] }[]; // agrupación SOLO visual de los campos (cada campo en exactamente una sección); no cambia la estructura guardada
    actionLabel?: string; // texto inequívoco de la acción en el inbox (por defecto «<título> (candidato)»)
    officialStatusNote?: string; // contexto "bobbin": aviso de que el estado oficial de Calidad de la bobina se muestra aparte (solo lectura) y esta captura no lo cambia
    hints?: Readonly<Record<string, string>>; // pistas por campo (clave -> texto); no cambian el contrato
    table?: { columns: readonly { prefix: string; label: string; suffix?: string }[]; positions: readonly number[]; keyFor: (prefix: string, position: number) => string }; // MF-07 (P1-21): los campos «columna_NN» se dibujan como UNA tabla editable de filas numeradas; la estructura guardada no cambia
    preview?: (draft: Readonly<Record<string, string>>) => Record<string, string | null>; // MF-07: valor mostrado de cada campo calculado por el backend (solo visualización mientras se digita)
    historyNote: string;
};
