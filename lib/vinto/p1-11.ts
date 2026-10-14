// Captura CENTRAL CANDIDATA de VINTO-P1-11 «Consumo de bobinas» (Conversión), M6-D: especificación del grupo repetible, borrador, validación ESTRUCTURAL, payload, intento pendiente y parsers.
// Reutiliza el núcleo común (capture-core.ts) y los grupos repetibles (capture-groups.ts, M3-A); aporta su parser con el código esperado «VINTO-P1-11». PURO: sin red ni DOM.
//
// HIPÓTESIS DE PRUEBA, NO una definición aprobada: UN grupo repetible `bobinas` (número de bobina declarado, posición superior/inferior y tres saldos declarados) y las observaciones opcionales. La definición
// legacy de P1-11 es otra (61 campos: bobinas inferior/superior, merma, cinco insumos, producción, rodelas y cuchilla, con 22 calculados) y la pantalla legacy son 3 filas fijas; NINGUNA de las dos se implementa.
//
// QUÉ NO HACE (decisiones pendientes de VINTO, docs/M6-D-conversion-p111.md): los números de bobina y los saldos son DECLARACIONES de prueba: no se calcula ni se guarda consumo, balance, merma, saldo
// disponible, diferencia ni movimiento de inventario, y no hay relación con bobinas reales (F3, Rebobinado, P1-13, Calidad, genealogía). No se exige que el saldo final sea menor que el inicial, ni que el número de
// bobina sea único entre filas, ni hay mínimos, máximos, precisión o redondeos de negocio; las unidades «kg» son etiquetas de la hipótesis legacy. Sin receta, tipo de bobina, rodelas ni insumos.
//
// CARDINALIDAD: `min_rows = 1` y las dos posiciones son decisiones SOLO del contrato candidato (no reglas industriales); no hay máximo funcional definido. El único tope es el TÉCNICO del sistema
// (1000 filas por grupo, capture-groups.ts), que no es una regla industrial.
//
// P1-11 NO está habilitado en la política de captura central del backend ni Conversión es un sector operativo: este cliente solo funciona contra un backend de prueba que lo habilite explícitamente.

import {
    freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { buildGroupedValues, buildGroups, groupedValuesParser, initialDrafts, type GroupDrafts, type GroupSpec, type RowError } from "./capture-groups.ts";

export const P1_11_CODE = "VINTO-P1-11";
export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

export const ADVISORY = "Ficha candidata no homologada. Los números de bobina y los saldos son declaraciones de prueba: no generan consumo, movimientos de inventario ni vínculos de genealogía.";

export const POSICION_OPTIONS = [{ value: "superior", label: "Superior" }, { value: "inferior", label: "Inferior" }] as const;
export const positionLabel = (value: string): string => POSICION_OPTIONS.find((o) => o.value === value)?.label ?? value;

// ---- especificación del contrato candidato -----------------------------------------------------------------------------------------------------

export const P111_GROUPS: readonly GroupSpec[] = [
    { code: "bobinas", label: "Bobinas declaradas", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "numero_bobina", label: "N.º de bobina (declarado)", kind: "text", required: true },
        { key: "posicion", label: "Posición (declarada)", kind: "choice", required: true, options: POSICION_OPTIONS },
        { key: "saldo_inicial_kg", label: "Saldo inicial declarado", kind: "decimal", required: true, unit: "kg" },
        { key: "ingreso_kg", label: "Ingreso declarado", kind: "decimal", required: true, unit: "kg" },
        { key: "saldo_final_kg", label: "Saldo final declarado", kind: "decimal", required: true, unit: "kg" },
    ] },
];

// ---- decisiones pendientes de VINTO (NO son reglas confirmadas) --------------------------------------------------------------------------

export const PENDING_NOTES: readonly { key: string; label: string; pending: string }[] = [
    { key: "estructura", label: "Estructura de la ficha", pending: "La definición legacy (61 campos) y la pantalla de tres filas fijas difieren; el número de filas y las posiciones de esta hipótesis no son reglas industriales." },
    { key: "bobina", label: "Identificación de la bobina", pending: "El número es texto libre declarado: no se consulta, no se exige que sea único y no se vincula con bobinas de Bobinas, Rebobinado ni P1-13." },
    { key: "saldos", label: "Saldos y consumo", pending: "Declarados por el operador; no se calcula consumo ni balance, no hay movimiento de inventario y la unidad oficial está pendiente." },
    { key: "diferidos", label: "Rodelas, insumos, producción y cuchilla", pending: "Quedan fuera de esta hipótesis: dependen de decisiones de VINTO sobre su estructura y sus fórmulas." },
    { key: "firma", label: "Firma / grupo", pending: "Sin mecanismo de firma ni concepto de grupo en el modelo central; no se simulan." },
];

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------------

export type P111Row = { numero_bobina: string; posicion: string; saldo_inicial_kg: string; ingreso_kg: string; saldo_final_kg: string };
export type P111Simple = { observaciones?: string };
export type P111Values = P111Simple & { _groups: { bobinas: P111Row[] } };
export type P111Capture = CaptureOf<P111Values>;
export type P111Submission = SubmissionOf<P111Capture>;

// Solo las observaciones opcionales; lo demás (incluidos campos desconocidos como un consumo) se ignora, nunca se conserva.
function parseSimple(value: unknown): P111Simple | null {
    if (!isRec(value)) return null;
    const { observaciones: notes } = value;
    if (notes !== undefined && typeof notes !== "string") return null;
    return notes === undefined ? {} : { observaciones: notes };
}

const parseValues = groupedValuesParser(parseSimple, P111_GROUPS);
export const parseP111Capture = (value: unknown): P111Capture | null => parseCaptureOf(value, parseValues as (v: unknown) => P111Values | null, P1_11_CODE);
export const parseP111Submission = (value: unknown): P111Submission | null => parseSubmissionOf(value, parseP111Capture);
export const parseP111List = (value: unknown): P111Capture[] | null => parseCaptureListOf(value, parseP111Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------------

export type P111Draft = { observaciones: string; groups: GroupDrafts };
export const emptyP111Draft = (makeKey?: () => string): P111Draft => ({ observaciones: "", groups: initialDrafts(P111_GROUPS, makeKey) });

export type P111Check = { ok: true; values: Record<string, unknown> } | { ok: false; errors: RowError[] };

// Solo lo estructural: texto no vacío, posición del catálogo, tres decimales (coma o punto; se envían como TEXTO con punto, sin float ni redondeo) y al menos una fila. No compara saldos, no exige unicidad
// del número de bobina, no impone rango ni precisión y no calcula nada.
export function normalizeP111Draft(draft: P111Draft): P111Check {
    const errors: RowError[] = [];
    const simple: Record<string, unknown> = {};
    const notes = draft.observaciones.trim();
    if (notes.length > MAX_TEXT_LENGTH) errors.push({ group: "", row: null, field: "observaciones", message: `Observaciones: supera ${MAX_TEXT_LENGTH} caracteres.` });
    else if (notes) simple.observaciones = notes;
    const built = buildGroups(P111_GROUPS, draft.groups);
    if (!built.ok) errors.push(...built.errors);
    return errors.length || !built.ok ? { ok: false, errors } : { ok: true, values: buildGroupedValues(simple, built.groups) };
}

export type P111Payload = { capture_id: string; form_code: typeof P1_11_CODE; assignment_id: string; device_key: string; values: Record<string, unknown> };

export const buildP111Payload = (captureId: string, assignmentId: string, deviceKey: string, values: Record<string, unknown>): P111Payload =>
    ({ capture_id: captureId, form_code: P1_11_CODE, assignment_id: assignmentId, device_key: deviceKey, values });

export type P111Attempt = PendingAttemptOf<P111Payload, P111Draft>;

export function createP111Attempt(draft: P111Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P111Attempt } | { ok: false; errors: RowError[] } {
    const check = normalizeP111Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP111Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------------

export type P111SubmitDeps = SubmitDepsOf<P111Payload, P111Submission, P111Capture>;
export type P111SubmitOutcome = SubmitOutcomeOf<P111Capture>;

export const submitP111Attempt = (attempt: P111Attempt, deps: P111SubmitDeps): Promise<P111SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP111 = (captureId: string, deps: P111SubmitDeps): Promise<P111SubmitOutcome> => reconcileOf(captureId, deps);
