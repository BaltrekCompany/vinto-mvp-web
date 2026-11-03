// MF-13-03B PR7: contrato de la activación masiva (POST /api/work-orders/{id}/activate-all, PR4) para la interfaz de Supervisión. PURO: sin red, sin DOM.
//
// Principios: el navegador NUNCA genera el `plan_hash` ni envía máquina, turno, fecha o identificadores operativos; solo `{"dry_run": true}` (vista previa, de solo lectura) o
// `{"dry_run": false, "plan_hash": <el hash que devolvió el servidor, sin tocar>}`. La respuesta se valida de forma ESTRICTA, incluida su coherencia interna: una respuesta
// parcialmente malformada o contradictoria no puede presentarse como una confirmación válida (se trata como fallo).

import { parseAssignment, type Assignment, type WorkOrderStatus } from "./orders.ts";

export type PlanAction = "activate" | "already_active" | "blocked";
export type Outcome = "preview" | "applied" | "already_in_effect";
type NameCode = { code: string; name: string };

export type PlanLine = {
    baseline_line_id: string;
    line_code: string;
    pv_reference: string;
    article: { code: string; description: string };
    machine: NameCode;
    shift: NameCode | null;
    operating_date: string | null;
    action: PlanAction;
    reason: string | null;
    assignment_id: string | null;
};
export type PlanExpired = { assignment_id: string; machine: NameCode; line_code: string };
export type PlanConflict = { assignment_id: string; machine: NameCode; work_order: { id: string; number: string }; line_code: string; expired: boolean | null };
export type PlanSummary = { activate: number; already_active: number; blocked: number; expired_to_finish: number; conflicts: number };

export type ActivateAllResponse = {
    dry_run: boolean;
    outcome: Outcome;
    work_order: { id: string; number: string };
    status: WorkOrderStatus;
    plan_hash: string;
    can_confirm: boolean;
    summary: PlanSummary;
    lines: PlanLine[];
    expired: PlanExpired[];
    conflicts: PlanConflict[];
    activated: Assignment[];
    already_active: Assignment[];
    finished: Assignment[];
};

// ---- cuerpos exactos de la solicitud -------------------------------------------------------------------------------------------------------------------------------

export const PLAN_HASH = /^[a-f0-9]{64}$/;

export const previewPayload = () => ({ dry_run: true }) as const;

// El hash se envía tal cual lo devolvió el servidor. Un valor que no tenga la forma de un hash NO se envía (null): el cliente no lo corrige ni lo fabrica.
export function confirmPayload(planHash: string): { dry_run: false; plan_hash: string } | null {
    return typeof planHash === "string" && PLAN_HASH.test(planHash) ? { dry_run: false, plan_hash: planHash } : null;
}

// ---- parser estricto ----------------------------------------------------------------------------------------------------------------------------------------------------

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const STATUSES: readonly string[] = ["draft", "published", "in_progress", "closed"];
const OUTCOMES: readonly string[] = ["preview", "applied", "already_in_effect"];
const ACTIONS: readonly string[] = ["activate", "already_active", "blocked"];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function pair(value: unknown): NameCode | null {
    return isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
}
function all<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
    if (!Array.isArray(value)) return null;
    const items = value.map(parse);
    return items.some((item) => item === null) ? null : (items as T[]);
}

function parseLine(value: unknown): PlanLine | null {
    if (!isRec(value) || !isStr(value.baseline_line_id) || !isStr(value.line_code) || typeof value.pv_reference !== "string") return null;
    const article = value.article, machine = pair(value.machine);
    if (!isRec(article) || !isStr(article.code) || typeof article.description !== "string" || !machine) return null;
    if (typeof value.action !== "string" || !ACTIONS.includes(value.action)) return null;
    const shift = value.shift === null ? null : pair(value.shift);
    if (value.shift !== null && !shift) return null;
    if (value.operating_date !== null && !(typeof value.operating_date === "string" && DATE.test(value.operating_date))) return null;
    if (value.reason !== null && !isStr(value.reason)) return null;
    if (value.assignment_id !== null && !isStr(value.assignment_id)) return null;
    if ((value.action === "blocked") !== (value.reason !== null)) return null; // el motivo existe si y solo si la línea está bloqueada
    if ((value.action === "already_active") !== (value.assignment_id !== null)) return null; // la asignación vigente existe si y solo si ya estaba activa
    return { baseline_line_id: value.baseline_line_id, line_code: value.line_code, pv_reference: value.pv_reference, article: { code: article.code, description: article.description }, machine, shift,
        operating_date: value.operating_date as string | null, action: value.action as PlanAction, reason: value.reason as string | null, assignment_id: value.assignment_id as string | null };
}
function parseExpired(value: unknown): PlanExpired | null {
    const machine = isRec(value) ? pair(value.machine) : null;
    return isRec(value) && isStr(value.assignment_id) && isStr(value.line_code) && machine ? { assignment_id: value.assignment_id, machine, line_code: value.line_code } : null;
}
function parseConflict(value: unknown): PlanConflict | null {
    if (!isRec(value) || !isStr(value.assignment_id) || !isStr(value.line_code)) return null;
    const machine = pair(value.machine), order = value.work_order;
    if (!machine || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (value.expired !== null && typeof value.expired !== "boolean") return null;
    return { assignment_id: value.assignment_id, machine, work_order: { id: order.id, number: order.number }, line_code: value.line_code, expired: value.expired as boolean | null };
}

export function parseActivateAll(value: unknown): ActivateAllResponse | null {
    if (!isRec(value) || typeof value.dry_run !== "boolean" || typeof value.outcome !== "string" || !OUTCOMES.includes(value.outcome)) return null;
    if (value.dry_run !== (value.outcome === "preview")) return null;
    const order = value.work_order;
    if (!isRec(order) || !isStr(order.id) || !isStr(order.number) || !isStr(value.status) || !STATUSES.includes(value.status)) return null;
    if (typeof value.plan_hash !== "string" || !PLAN_HASH.test(value.plan_hash) || typeof value.can_confirm !== "boolean") return null;
    const s = value.summary;
    if (!isRec(s) || !isCount(s.activate) || !isCount(s.already_active) || !isCount(s.blocked) || !isCount(s.expired_to_finish) || !isCount(s.conflicts)) return null;
    const lines = all(value.lines, parseLine), expired = all(value.expired, parseExpired), conflicts = all(value.conflicts, parseConflict);
    const activated = all(value.activated, parseAssignment), alreadyActive = all(value.already_active, parseAssignment), finished = all(value.finished, parseAssignment);
    if (!lines || !expired || !conflicts || !activated || !alreadyActive || !finished || lines.length === 0) return null;
    const count = (action: PlanAction) => lines.filter((line) => line.action === action).length;
    // coherencia interna: el resumen describe exactamente las listas y `can_confirm` solo es verdadero sin bloqueos ni conflictos
    if (s.activate !== count("activate") || s.already_active !== count("already_active") || s.blocked !== count("blocked") || s.expired_to_finish !== expired.length || s.conflicts !== conflicts.length) return null;
    if (value.can_confirm !== (s.blocked === 0 && s.conflicts === 0)) return null;
    if (value.outcome === "preview") { // la vista previa es de solo lectura: nada activado ni finalizado
        if (activated.length + alreadyActive.length + finished.length !== 0) return null;
    } else if (value.outcome === "applied") {
        if (!value.can_confirm || activated.length !== s.activate || alreadyActive.length !== s.already_active || finished.length !== s.expired_to_finish) return null;
    } else { // already_in_effect: no se activó ni finalizó nada; todas las líneas ya estaban activas
        if (!value.can_confirm || s.activate !== 0 || s.expired_to_finish !== 0 || activated.length !== 0 || finished.length !== 0 || alreadyActive.length !== lines.length) return null;
    }
    return { dry_run: value.dry_run, outcome: value.outcome as Outcome, work_order: { id: order.id, number: order.number }, status: value.status as WorkOrderStatus, plan_hash: value.plan_hash,
        can_confirm: value.can_confirm, summary: { activate: s.activate, already_active: s.already_active, blocked: s.blocked, expired_to_finish: s.expired_to_finish, conflicts: s.conflicts },
        lines, expired, conflicts, activated, already_active: alreadyActive, finished };
}

// Qué esperamos de cada fase: la respuesta a una vista previa SOLO es válida como vista previa y la de una confirmación SOLO como confirmación (con el mismo hash enviado).
export const parsePreview = (value: unknown): ActivateAllResponse | null => {
    const parsed = parseActivateAll(value);
    return parsed && parsed.outcome === "preview" ? parsed : null;
};
export const parseConfirmation = (planHash: string) => (value: unknown): ActivateAllResponse | null => {
    const parsed = parseActivateAll(value);
    return parsed && parsed.outcome !== "preview" && parsed.plan_hash === planHash ? parsed : null;
};

// 201 <-> applied y 200 <-> already_in_effect: cualquier otra combinación es una respuesta contradictoria.
export function statusMatchesOutcome(status: number, outcome: Outcome): boolean {
    return (status === 201 && outcome === "applied") || (status === 200 && outcome === "already_in_effect") || (status === 200 && outcome === "preview");
}
