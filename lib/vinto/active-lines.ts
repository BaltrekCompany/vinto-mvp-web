// MF-13-03B PR8: selección de línea activa en Operación (puro: sin red ni DOM).
//
// Historial: con UNA asignación activa, `GET /api/assignments/active` sigue siendo el contrato (y no se añade ningún paso). Solo cuando el servidor responde 409 MULTIPLE_ACTIVE_ASSIGNMENTS
// (varias líneas activas de la misma OT con la compuerta multimáquina) se lee `GET /api/assignments/active-lines`. El cliente NUNCA elige una línea por el operario ni por el servidor:
// la selección es explícita, vive solo en memoria, y es DERIVADA (si la línea ya no está o no está vigente, deja de valer sin necesidad de efectos).
// La selección no es una autorización: la captura envía el `assignment_id` y el backend vuelve a validar sesión, alcance, máquina, permiso, vigencia y turno.

import { captureContextOf, parseActive, parseAssignment, type ActiveAssignment, type Assignment, type ContextCheck } from "./orders.ts";

export type ActiveLineItem = { assignment: Assignment; stale: boolean | null };
export type ActiveLines = { current_shift: ActiveAssignment["current_shift"]; items: ActiveLineItem[] };

// Lo que ve la pantalla de Ejecución: el contrato histórico (0 o 1 asignación) o varias líneas.
export type OperationSelection = { kind: "single"; active: ActiveAssignment } | { kind: "multiple"; lines: ActiveLines };

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);

export function parseActiveLines(value: unknown): ActiveLines | null {
    if (!isRec(value) || !("current_shift" in value) || !Array.isArray(value.assignments)) return null;
    // Reutiliza el parser de `/active` para el turno (misma forma): una asignación nula + el turno recibido.
    const shell = parseActive({ assignment: null, current_shift: value.current_shift, stale: null });
    if (!shell) return null;
    const items: ActiveLineItem[] = [];
    for (const raw of value.assignments) {
        if (!isRec(raw) || (raw.stale !== null && typeof raw.stale !== "boolean")) return null;
        const assignment = parseAssignment(raw.assignment);
        if (!assignment) return null;
        items.push({ assignment, stale: raw.stale as boolean | null });
    }
    if (new Set(items.map((item) => item.assignment.id)).size !== items.length) return null; // una asignación repetida sería ambigua
    return { current_shift: shell.current_shift, items };
}

// 0 o 1 línea activa es el contrato histórico (una carrera entre dos lecturas no obliga a elegir); 2+ exige selección explícita.
export function selectionFromLines(lines: ActiveLines): OperationSelection {
    if (lines.items.length > 1) return { kind: "multiple", lines };
    const only = lines.items[0];
    return { kind: "single", active: { assignment: only ? only.assignment : null, current_shift: lines.current_shift, stale: only ? only.stale : null } };
}

export const isSelectable = (item: ActiveLineItem): boolean => item.stale === false;

// Por qué una línea no se puede elegir (null si se puede).
export function unselectableReason(item: ActiveLineItem): string | null {
    if (item.stale === true) return "Otro turno o fecha operativa. Supervisión debe reactivarla.";
    if (item.stale === null) return "No se pudo resolver el turno vigente.";
    return null;
}

// Una selección pertenece a UN contexto (sesión + máquina + lectura del servidor). Se guarda con su clave y solo vale mientras la clave coincida.
export type Selection = { key: string; assignmentId: string };
export const selectionKey = (scope: string, machine: string): string => `${scope}:${machine}`;

// Selección vigente: misma clave, la línea sigue activa en la lectura actual y sigue vigente para el turno. Cualquier otro caso => null (hay que elegir de nuevo).
export function validSelection(selection: Selection | null, key: string, lines: ActiveLines): string | null {
    if (!selection || selection.key !== key) return null;
    const item = lines.items.find((candidate) => candidate.assignment.id === selection.assignmentId);
    return item && isSelectable(item) ? item.assignment.id : null;
}

// Contexto de captura de la línea elegida. Sin selección válida no hay contexto: nunca se escoge una por el operario.
export function contextFromSelection(lines: ActiveLines, assignmentId: string | null): ContextCheck {
    const item = assignmentId === null ? undefined : lines.items.find((candidate) => candidate.assignment.id === assignmentId);
    if (!item) return { ok: false, reason: "unselected", assignment: null };
    if (item.stale === true) return { ok: false, reason: "stale", assignment: item.assignment };
    if (item.stale === null) return { ok: false, reason: "unresolvable", assignment: item.assignment };
    return { ok: true, context: captureContextOf(item.assignment) };
}
