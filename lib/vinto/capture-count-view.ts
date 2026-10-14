import type { CaptureCountFailure, CaptureFront } from "./api";

// Presentación del conteo de capturas de Seguimiento. El valor principal es SIEMPRE central: sin conteo central (cargando, sin permiso o no disponible)
// no se muestra un número (ni cero ni el local) como si fuera la producción; el conteo local del navegador solo aparece como dato secundario rotulado.
export type CaptureCountViewState = { status: "loading" } | { status: "failed"; kind: CaptureCountFailure } | { status: "ready"; count: number };
export type CaptureCountView = { label: string; value: string; note: string; canRetry: boolean };

export const LOCAL_LABEL = "Registros locales (este navegador)";
export const CENTRAL_LABEL = "Registros centrales";
export const VALUE_UNKNOWN = "—";

export function captureCountView(state: CaptureCountViewState, front: CaptureFront, localCount: number): CaptureCountView {
    const local = `${LOCAL_LABEL}: ${localCount}. No representan la producción central de ${front} ni se suman al conteo central.`;
    if (state.status === "ready") return { label: CENTRAL_LABEL, value: String(state.count), note: `${local} Sin sincronización automática.`, canRetry: true };
    if (state.status === "loading") return { label: CENTRAL_LABEL, value: VALUE_UNKNOWN, note: "Consultando registros centrales…", canRetry: false };
    const reason = state.kind === "forbidden" ? "Tu perfil no tiene acceso al conteo central." : "Consulta central no disponible.";
    return { label: CENTRAL_LABEL, value: VALUE_UNKNOWN, note: `${reason} ${local}`, canRetry: true };
}
