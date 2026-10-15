import type { CaptureCountFailure, CaptureFront } from "./api";

// Presentación del conteo de capturas de Seguimiento. El valor es SIEMPRE central: sin conteo central (cargando, sin permiso o no disponible) no se muestra un número (ni un cero ficticio) como si fuera la
// producción. INT-02A: los registros locales del navegador (vinto-p1-records) ya no se leen ni se mencionan como indicador: no se suman ni se presentan junto al conteo central.
export type CaptureCountViewState = { status: "loading" } | { status: "failed"; kind: CaptureCountFailure } | { status: "ready"; count: number };
export type CaptureCountView = { label: string; value: string; note: string; canRetry: boolean };

export const CENTRAL_LABEL = "Registros centrales";
export const VALUE_UNKNOWN = "—";

export function captureCountView(state: CaptureCountViewState, front: CaptureFront): CaptureCountView {
    if (state.status === "ready") return { label: CENTRAL_LABEL, value: String(state.count), note: `Capturas centrales de ${front} (PostgreSQL). Sin sincronización automática.`, canRetry: true };
    if (state.status === "loading") return { label: CENTRAL_LABEL, value: VALUE_UNKNOWN, note: "Consultando registros centrales…", canRetry: false };
    const reason = state.kind === "forbidden" ? "Tu perfil no tiene acceso al conteo central." : "Consulta central no disponible.";
    return { label: CENTRAL_LABEL, value: VALUE_UNKNOWN, note: reason, canRetry: true };
}
