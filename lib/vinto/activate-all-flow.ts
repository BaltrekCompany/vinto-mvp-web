// MF-13-03B PR7: máquina de estados PURA del diálogo de activación masiva (vista previa -> confirmación). Sin red ni DOM.
//
// Garantías que fija este módulo (y que prueban scripts/pr7-activate-all.test.mjs):
//  - NO se confirma sin una vista previa vigente, coherente con la OT, con `can_confirm` verdadero y con algo que hacer.
//  - El `plan_hash` vive únicamente dentro del estado de la interfaz (memoria): ni almacenamiento local ni cookies. Cerrar, cambiar de OT o de sesión lo descarta.
//  - Una respuesta que llega para OTRA OT, o fuera de fase (tardía), se ignora.
//  - Tras un fallo de la confirmación NUNCA se reenvía sola: 409 -> hay que consultar de nuevo; red / respuesta desconocida -> «incierto» (el servidor pudo haberla aplicado):
//    solo se ofrece una vista previa de solo lectura.
//  - Los mensajes no añaden información que el backend no haya autorizado en la respuesta.

import type { ActivateAllResponse, PlanConflict, PlanLine } from "./activate-all.ts";

export type Problem = "plan_changed" | "blocked" | "uncertain" | "unavailable" | "invalid" | "not_available" | "disabled";

export type FlowState =
    | { phase: "closed" }
    | { phase: "previewing"; orderId: string }
    | { phase: "preview"; orderId: string; plan: ActivateAllResponse }
    | { phase: "confirming"; orderId: string; plan: ActivateAllResponse }
    | { phase: "done"; orderId: string; result: ActivateAllResponse }
    | { phase: "problem"; orderId: string; problem: Problem };

export type Failure = { kind: string; code?: string };
export type FlowAction =
    | { type: "preview_start"; orderId: string }
    | { type: "preview_ok"; orderId: string; plan: ActivateAllResponse }
    | { type: "preview_failed"; orderId: string; failure: Failure }
    | { type: "confirm_start"; orderId: string }
    | { type: "confirm_ok"; orderId: string; result: ActivateAllResponse }
    | { type: "confirm_failed"; orderId: string; failure: Failure }
    | { type: "close" };

export const CLOSED: FlowState = { phase: "closed" };
export const startPreviewing = (orderId: string): FlowState => ({ phase: "previewing", orderId });

// ¿Hay algo que aplicar? Con todo ya activo y sin vencidas la confirmación no hace nada: no se ofrece.
export const isActionable = (plan: ActivateAllResponse): boolean => plan.summary.activate > 0 || plan.summary.expired_to_finish > 0;
export const canConfirmPlan = (plan: ActivateAllResponse): boolean => plan.outcome === "preview" && plan.can_confirm && isActionable(plan);

// 401 -> sesión perdida (lo atiende el mecanismo existente). 403/404 -> sin detalles. 422 MULTI_MACHINE_DISABLED -> deshabilitar. 409 -> consultar de nuevo. Red/5xx/respuesta
// desconocida: tras CONFIRMAR es «incierto» (no se reintenta); en la vista previa es «no disponible».
export function classifyFailure(phase: "preview" | "confirm", failure: Failure): Problem | "session" {
    if (failure.kind === "session") return "session";
    if (failure.kind === "invalid" && failure.code === "MULTI_MACHINE_DISABLED") return "disabled";
    if (failure.kind === "forbidden" || failure.kind === "not_found") return "not_available";
    if (failure.kind === "conflict") return failure.code === "ACTIVATION_BLOCKED" ? "blocked" : "plan_changed";
    if (failure.kind === "invalid") return "invalid";
    return phase === "confirm" ? "uncertain" : "unavailable";
}

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
    switch (action.type) {
        case "preview_start":
            return state.phase === "confirming" ? state : { phase: "previewing", orderId: action.orderId }; // nunca se actualiza a mitad de una confirmación
        case "preview_ok":
            if (state.phase !== "previewing" || state.orderId !== action.orderId) return state; // respuesta tardía o de otra OT
            if (action.plan.work_order.id !== action.orderId || action.plan.outcome !== "preview") return { phase: "problem", orderId: action.orderId, problem: "unavailable" };
            return { phase: "preview", orderId: action.orderId, plan: action.plan };
        case "preview_failed": {
            if (state.phase !== "previewing" || state.orderId !== action.orderId) return state;
            const problem = classifyFailure("preview", action.failure);
            return problem === "session" ? CLOSED : { phase: "problem", orderId: action.orderId, problem };
        }
        case "confirm_start":
            if (state.phase !== "preview" || state.orderId !== action.orderId || !canConfirmPlan(state.plan)) return state; // sin vista previa vigente o confirmable no hay confirmación
            return { phase: "confirming", orderId: action.orderId, plan: state.plan };
        case "confirm_ok":
            if (state.phase !== "confirming" || state.orderId !== action.orderId) return state;
            if (action.result.work_order.id !== action.orderId || action.result.outcome === "preview" || action.result.plan_hash !== state.plan.plan_hash) return { phase: "problem", orderId: action.orderId, problem: "uncertain" };
            return { phase: "done", orderId: action.orderId, result: action.result };
        case "confirm_failed": {
            if (state.phase !== "confirming" || state.orderId !== action.orderId) return state;
            const problem = classifyFailure("confirm", action.failure);
            return problem === "session" ? CLOSED : { phase: "problem", orderId: action.orderId, problem }; // el plan (y su hash) se descarta: no se reutiliza
        }
        case "close":
            return state.phase === "confirming" ? state : CLOSED; // mientras la confirmación está en vuelo no se puede cerrar: se perdería el resultado
    }
}

// ---- textos ------------------------------------------------------------------------------------------------------------------------------------------------------------

export const PROBLEM_MESSAGES: Record<Problem, string> = {
    plan_changed: "La programación o el turno cambió; vuelve a consultar la vista previa.",
    blocked: "La activación está bloqueada. Actualiza la vista previa para ver el motivo; no se realizó ningún cambio.",
    uncertain: "No se recibió una respuesta válida del servidor. La confirmación no se repite sola: consulta de nuevo la situación (vista previa de solo lectura) para saber si se aplicó.",
    unavailable: "No se pudo consultar la vista previa. No se realizó ningún cambio.",
    invalid: "Los datos enviados no son válidos. No se realizó ningún cambio.",
    not_available: "No se puede consultar esta orden de trabajo.",
    disabled: "La activación masiva no está habilitada por el servidor.",
};

// Se puede volver a consultar (solo lectura) salvo cuando el servidor no la habilita o no hay acceso.
export const canRetryPreview = (problem: Problem): boolean => problem !== "disabled" && problem !== "not_available";

export const REASON_LABELS: Record<string, string> = {
    MACHINE_INACTIVE: "Máquina inactiva",
    MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER: "Ocupada por otra OT",
    SHIFT_NOT_CONFIGURED: "Sin turno configurado",
    SHIFT_AMBIGUOUS: "Turno ambiguo",
};
export const reasonLabel = (reason: string | null): string => (reason ? REASON_LABELS[reason] ?? "Bloqueada" : "Bloqueada");

export const conflictMessage = (conflict: PlanConflict): string =>
    `La máquina ${conflict.machine.code} tiene líneas activas de otra OT (${conflict.work_order.number}). Finaliza esas asignaciones desde Supervisión antes de continuar.`;

export function groupLines(plan: ActivateAllResponse): { toActivate: PlanLine[]; alreadyActive: PlanLine[]; blocked: PlanLine[] } {
    return {
        toActivate: plan.lines.filter((line) => line.action === "activate"),
        alreadyActive: plan.lines.filter((line) => line.action === "already_active"),
        blocked: plan.lines.filter((line) => line.action === "blocked"),
    };
}

export function previewHeadline(plan: ActivateAllResponse): string {
    const s = plan.summary;
    return `${plan.work_order.number}: ${plan.lines.length} línea(s) · ${s.activate} por activar · ${s.already_active} ya activas · ${s.blocked} bloqueadas · ${s.expired_to_finish} vencida(s) por finalizar · ${s.conflicts} conflicto(s)`;
}

// Solo se afirma lo que el servidor confirmó (resultado real).
export function resultMessage(result: ActivateAllResponse): string {
    if (result.outcome === "already_in_effect") return `El plan ya estaba aplicado: las ${result.already_active.length} línea(s) ya están activas en el turno vigente. No se realizó ninguna activación nueva.`;
    return `Se activaron ${result.activated.length} línea(s); ${result.already_active.length} ya estaban activas; se finalizaron ${result.finished.length} asignación(es) vencida(s).`;
}

// Mensaje cuando la consulta es confirmable pero no hay nada que hacer (p. ej. tras una respuesta perdida que sí se aplicó).
export const NOTHING_TO_DO = "Todas las líneas ya están activas en el turno vigente; no hay nada que confirmar.";
