// Captura CENTRAL CANDIDATA de VINTO-P1-13 «Producción diaria de servilletas y especiales» (Conversión), M6-C: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y los validadores del pallet de P1-12 (p1-12.ts), y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-13».
//
// CLOUD-DEP G.12-C4-FINAL25: el contrato REAL usado por el backend (seed_data, política, UI) es `P113_FIELDS` + `defineCandidateForm`, más abajo en este archivo -- los 18 campos MANUALES
// exactos de la definición legacy (form_13_produccion_diaria_de_servilletas_y_especiales, 31 campos: 8 automáticos, 18 manuales, 5 calculados). Todo lo de ARRIBA de esta nota (P113 hipótesis:
// bobina declarada + saldos + pallet, interpretación de `NapkinSheet`) es la HIPÓTESIS DE PRUEBA original y ya NO se usa desde app/page.tsx: queda como código muerto, sin eliminar.
//
// QUÉ NO HACE el contrato real (decisiones pendientes de VINTO, docs/M6-C-conversion-p113.md): no calcula merma_bobina/saldo_final/merma_empaque/insumo_saldo_final (calculados, sin fórmula
// aprobada). Solo exige lo estructural que la propia definición declara.
//
// Todo es PURO (sin red, sin DOM).

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { EMPTY_P112_DRAFT, normalizeP112Draft, parsePalletValues, type P112Values } from "./p1-12.ts";
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

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

// ---- CLOUD-DEP G.12-C4-FINAL25: contrato REAL (18 campos manuales de la definición legacy, en su orden) -----------------------------------
// Fuente única: form-definitions.ts / form_13_produccion_diaria_de_servilletas_y_especiales. Automáticos excluidos (operador, firma, fecha,
// hora, turno, grupo, maquina, encargado_de_turno); calculados excluidos (merma_bobina, saldo_final, merma_empaque, insumo_saldo_final): sin
// fórmula aprobada. `observacion` (singular) y `observaciones` (plural) son DOS claves distintas de la definición legacy, ambas opcionales --
// no se fusionan ni se corrige la aparente duplicación: así está declarada la fuente.
export const P113_FIELDS: readonly FieldSpec[] = [
    { key: "hora_inicio", label: "Hora inicio", kind: "time", required: true, sinceVersion: 2 }, // MF-11 (MD_Ejec 46 y 48, un solo par): horas GENERALES de producción, no las del pallet de la hipótesis anterior
    { key: "hora_fin", label: "Hora fin", kind: "time", required: true, sinceVersion: 2 },
    { key: "saldo_inicial", label: "Saldo inicial", kind: "text", required: true },
    { key: "numero_bobina_consumida", label: "Número bobina consumida", kind: "text", required: true },
    { key: "peso_bobina_consumida", label: "Peso bobina consumida", kind: "text", required: true, suffix: "kg" },
    { key: "formato_bobina_consumida", label: "Formato bobina consumida", kind: "text", required: true },
    { key: "observacion", label: "Observación", kind: "textarea", required: false },
    { key: "codigo_producto", label: "Código producto", kind: "text", required: true },
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "formato_producto", label: "Formato producto", kind: "text", required: true },
    { key: "cantidad_producida", label: "Cantidad producida", kind: "text", required: true },
    { key: "empaque_saldo_inicial", label: "Empaque saldo inicial", kind: "text", required: true },
    { key: "empaque_solicitado", label: "Empaque solicitado", kind: "text", required: true },
    { key: "empaque_utilizado", label: "Empaque utilizado", kind: "text", required: true },
    { key: "insumo_codigo", label: "Insumo código", kind: "text", required: true },
    { key: "insumo_nombre", label: "Insumo nombre", kind: "text", required: true },
    { key: "insumo_saldo_inicial", label: "Insumo saldo inicial", kind: "text", required: true },
    { key: "insumo_solicitado", label: "Insumo solicitado", kind: "text", required: true },
    { key: "insumo_utilizado", label: "Insumo utilizado", kind: "text", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P113 = defineCandidateForm(P1_13_CODE, P113_FIELDS);

export const P113_AUTOMATIC = ["Operador", "Firma", "Fecha", "Hora", "Turno", "Grupo", "Máquina", "Encargado de turno"] as const;
export const P113_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Horas de inicio y fin", pending: "Se digitan (HH:MM, hora local de planta) y son obligatorias desde la versión 2; no son la hora de registro del sistema ni las de un pallet, no se calcula la duración ni se valida el orden, y no se asume otra fecha si cruzan la medianoche." },
    { label: "Mermas y saldos finales", pending: "4 campos calculados de la definición legacy (merma de bobina, saldo final, merma de empaque, saldo final de insumo): sin fórmula aprobada, no se calculan ni se aceptan del cliente." },
    { label: "observacion / observaciones", pending: "La definición legacy declara DOS campos de observación distintos (singular y plural), ambos opcionales: no se fusionan ni se corrige la aparente duplicación." },
];
