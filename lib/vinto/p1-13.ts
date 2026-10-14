// Captura CENTRAL CANDIDATA de VINTO-P1-13 «Producción diaria de servilletas y especiales» (Conversión), M6-C: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y los validadores del pallet de P1-12 (p1-12.ts), y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-13».
//
// HIPÓTESIS DE PRUEBA, NO una definición aprobada: los ocho campos son una interpretación de `NapkinSheet` (la pantalla legacy de app/page.tsx): una bobina DECLARADA con sus tres saldos, más UN pallet
// (jabas, hora de inicio y fin) y observaciones. La definición legacy de P1-13 es otra (31 campos) y NO se implementa aquí.
//
// QUÉ NO HACE (decisiones pendientes de VINTO, docs/M6-C-conversion-p113.md): los saldos y el número de bobina son DECLARACIONES de prueba: no se calcula ni se guarda consumo, balance, merma ni saldo
// disponible, no hay movimiento de inventario, ajuste de existencias ni relación con bobinas reales (F3, Rebobinado, P1-11, genealogía), y el número de bobina es texto libre que no se consulta. Tampoco se exige
// que el saldo final sea menor que el inicial, ni hay mínimos, máximos, precisión o redondeos; las unidades «kg» son etiquetas de la hipótesis legacy. Sin receta, insumos, número de pallet ni pesos.
//
// Todo es PURO (sin red, sin DOM). P1-13 NO está habilitado en la política de captura central del backend ni Conversión es un sector operativo: este cliente solo funciona contra un backend de prueba
// que lo habilite explícitamente.

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { EMPTY_P112_DRAFT, normalizeP112Draft, parsePalletValues, type P112Values } from "./p1-12.ts";

export const P1_13_CODE = "VINTO-P1-13";
export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

export const ADVISORY = "Ficha candidata no homologada. Los saldos y el número de bobina son declaraciones de prueba: no generan consumo ni modifican inventario.";

// ---- decisiones pendientes de VINTO (NO son reglas confirmadas) --------------------------------------------------------------------------

export const PENDING_NOTES: readonly { key: string; label: string; pending: string }[] = [
    { key: "bobina", label: "Identificación de la bobina", pending: "El número es texto libre declarado: no se consulta ni se vincula con bobinas de Bobinas, Rebobinado ni P1-11." },
    { key: "saldos", label: "Saldos y consumo", pending: "Declarados por el operador; no se calcula consumo ni balance, no hay movimiento de inventario y la unidad oficial está pendiente." },
    { key: "receta", label: "Receta e insumos", pending: "El tipo de bobina, los insumos y sus cantidades dependen de recetas sin homologar: quedan fuera de esta hipótesis." },
    { key: "pallet", label: "Número de pallet y pesos", pending: "Pendiente de definición: no se genera número oficial ni se calcula peso nominal o total." },
    { key: "firma", label: "Firma / grupo", pending: "Sin mecanismo de firma ni concepto de grupo en el modelo central; no se simulan." },
];

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------------

export type P113Values = P112Values & { numero_bobina: string; saldo_inicial_kg: string; ingreso_kg: string; saldo_final_kg: string; observaciones?: string };
export type P113Capture = CaptureOf<P113Values>;
export type P113Submission = SubmissionOf<P113Capture>;

const isDecimalText = (value: unknown): value is string => typeof value === "string" && value.length <= MAX_DECIMAL_CHARS && DECIMAL.test(value);

// Parser ESTRICTO: texto no vacío, tres decimales en texto (el backend devuelve los decimales como texto), el pallet con el parser de P1-12 y observaciones opcionales en texto; lo demás se ignora.
function parseValues(value: unknown): P113Values | null {
    if (!isRec(value)) return null;
    const pallet = parsePalletValues(value);
    const { numero_bobina: coil, saldo_inicial_kg: opening, ingreso_kg: inflow, saldo_final_kg: closing, observaciones: notes } = value;
    if (!pallet || typeof coil !== "string" || coil === "" || !isDecimalText(opening) || !isDecimalText(inflow) || !isDecimalText(closing)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: P113Values = { numero_bobina: coil, saldo_inicial_kg: opening, ingreso_kg: inflow, saldo_final_kg: closing, ...pallet };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

export const parseP113Capture = (value: unknown): P113Capture | null => parseCaptureOf(value, parseValues, P1_13_CODE);
export const parseP113Submission = (value: unknown): P113Submission | null => parseSubmissionOf(value, parseP113Capture);
export const parseP113List = (value: unknown): P113Capture[] | null => parseCaptureListOf(value, parseP113Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------------

export type P113Draft = typeof EMPTY_P112_DRAFT & { numero_bobina: string; saldo_inicial_kg: string; ingreso_kg: string; saldo_final_kg: string; observaciones: string };
export const EMPTY_P113_DRAFT: P113Draft = { ...EMPTY_P112_DRAFT, numero_bobina: "", saldo_inicial_kg: "", ingreso_kg: "", saldo_final_kg: "", observaciones: "" };
export const P113_LABELS = {
    numero_bobina: "N.º de bobina (declarado)", saldo_inicial_kg: "Saldo inicial declarado", ingreso_kg: "Ingreso declarado", saldo_final_kg: "Saldo final declarado", observaciones: "Observaciones",
} as const;

export type P113DraftCheck = { ok: true; values: P113Values } | { ok: false; errors: string[] };

export function normalizeP113Draft(draft: P113Draft): P113DraftCheck {
    const errors: string[] = [];
    const coil = draft.numero_bobina.trim(), notes = draft.observaciones.trim();
    if (!coil) errors.push(`${P113_LABELS.numero_bobina}: es obligatorio.`);
    else if (coil.length > MAX_TEXT_LENGTH) errors.push(`${P113_LABELS.numero_bobina}: supera ${MAX_TEXT_LENGTH} caracteres.`);
    if (notes.length > MAX_TEXT_LENGTH) errors.push(`${P113_LABELS.observaciones}: supera ${MAX_TEXT_LENGTH} caracteres.`);
    // Los saldos se escriben con coma o punto; el backend solo acepta el punto. Es la ÚNICA normalización (sin redondeo, sin rango, sin comparar un saldo con otro).
    const decimals: Record<"saldo_inicial_kg" | "ingreso_kg" | "saldo_final_kg", string> = { saldo_inicial_kg: "", ingreso_kg: "", saldo_final_kg: "" };
    for (const key of ["saldo_inicial_kg", "ingreso_kg", "saldo_final_kg"] as const) {
        const text = draft[key].trim().replace(",", ".");
        if (!text) errors.push(`${P113_LABELS[key]}: es obligatorio.`);
        else if (!isDecimalText(text)) errors.push(`${P113_LABELS[key]}: debe ser un número decimal (por ejemplo 12.5).`);
        else decimals[key] = text;
    }
    // El pallet usa exactamente los validadores de P1-12 (cantidad de jabas entera con signo opcional y dos horas HH:MM).
    const pallet = normalizeP112Draft({ cantidad_jabas: draft.cantidad_jabas, hora_inicio: draft.hora_inicio, hora_fin: draft.hora_fin });
    if (!pallet.ok) errors.push(...pallet.errors);
    if (errors.length || !pallet.ok) return { ok: false, errors };
    const values: P113Values = { numero_bobina: coil, ...decimals, ...pallet.values };
    if (notes) values.observaciones = notes;
    return { ok: true, values };
}

export type P113Payload = { capture_id: string; form_code: typeof P1_13_CODE; assignment_id: string; device_key: string; values: P113Values };

export function buildP113Payload(captureId: string, assignmentId: string, deviceKey: string, values: P113Values): P113Payload {
    return { capture_id: captureId, form_code: P1_13_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

export type P113Attempt = PendingAttemptOf<P113Payload, P113Draft>;

export function createP113Attempt(draft: P113Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P113Attempt } | { ok: false; errors: string[] } {
    const check = normalizeP113Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP113Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------------

export type P113SubmitDeps = SubmitDepsOf<P113Payload, P113Submission, P113Capture>;
export type P113SubmitOutcome = SubmitOutcomeOf<P113Capture>;

export const submitP113Attempt = (attempt: P113Attempt, deps: P113SubmitDeps): Promise<P113SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP113 = (captureId: string, deps: P113SubmitDeps): Promise<P113SubmitOutcome> => reconcileOf(captureId, deps);
