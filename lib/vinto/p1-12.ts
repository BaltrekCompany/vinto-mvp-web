// Captura CENTRAL CANDIDATA de VINTO-P1-12 «Producción diaria de papel higiénico» (Conversión), M6-B: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-12».
//
// CLOUD-DEP G.12-C4-FINAL25: el contrato REAL usado por el backend (seed_data, política, UI) es `P112_FIELDS` + `defineCandidateForm`, más abajo en este archivo -- los 20 campos MANUALES
// exactos de la definición legacy (form_12_produccion_diaria_de_papel_higienico, 37 campos: 9 automáticos, 20 manuales, 8 calculados), igual que P1-01/02/04/05/etc. Todo lo de ARRIBA de esta
// nota (P112Values/parseValues/P112_LABELS/normalizeP112Draft/createP112Attempt/...) es la HIPÓTESIS DE PRUEBA original (3 campos: cantidad de jabas + dos horas, interpretación de
// `PalletProduction`, la pantalla legacy de app/page.tsx) y ya NO se usa desde app/page.tsx: queda como código muerto, sin eliminar, documentando esa hipótesis descartada (igual que
// components/vinto/p1-10-preview.tsx). No la reutilices para nada nuevo: no es el contrato que el backend acepta.
//
// QUÉ NO HACE el contrato real (decisiones pendientes de VINTO, docs/M6-B-conversion-p112.md): no calcula ni envía los 8 saldos finales/mermas (calculados, sin fórmula aprobada), no genera
// firma ni asume el peso nominal/total (maestro no homologado). Solo exige lo estructural que la propia definición declara: texto/decimal, obligatorio según corresponda.
//
// Todo es PURO (sin red, sin DOM).

import {
    freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_12_CODE = "VINTO-P1-12";

// ---- decisiones pendientes de VINTO (NO son reglas confirmadas) --------------------------------------------------------------------------

export const PENDING_NOTES: readonly { key: string; label: string; pending: string }[] = [
    { key: "pallet", label: "Número oficial de pallet", pending: "Pendiente de definición: no se genera ni se asume ningún correlativo. La captura se identifica solo con su identificador técnico." },
    { key: "peso", label: "Peso nominal y peso total", pending: "Pendiente: el maestro de pesos nominales no está homologado. No se calcula ni se guarda ningún peso." },
    { key: "balances", label: "Empaque, saldos y mermas", pending: "La definición legacy los declara (37 campos); esta hipótesis solo registra el pallet." },
    { key: "firma", label: "Firma / grupo", pending: "Sin mecanismo de firma ni concepto de grupo en el modelo central; no se simulan." },
];

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------------

export type P112Values = { cantidad_jabas: number; hora_inicio: string; hora_fin: string };
export type P112Capture = CaptureOf<P112Values>;
export type P112Submission = SubmissionOf<P112Capture>;

const HOUR = /^([01]\d|2[0-3]):[0-5]\d$/; // lo que envía el cliente
const STORED_HOUR = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d(\.\d+)?)?$/; // PostgreSQL devuelve la hora con segundos (HH:MM:SS)
const INTEGER = /^-?\d+$/; // entero con signo opcional: es el mismo formato que acepta el backend; NO hay mínimo industrial (ver docs/M6-B-conversion-p112.md)

// Hora tal como se muestra: HH:MM (los segundos que añade PostgreSQL no se muestran).
export const shortHour = (value: string): string => value.slice(0, 5);

// Parser ESTRICTO: la cantidad es un entero JSON y las horas son texto con formato de hora; lo demás se ignora.
function parseValues(value: unknown): P112Values | null {
    if (!isRec(value)) return null;
    const { cantidad_jabas: jabas, hora_inicio: start, hora_fin: end } = value;
    if (typeof jabas !== "number" || !Number.isSafeInteger(jabas)) return null;
    if (typeof start !== "string" || !STORED_HOUR.test(start) || typeof end !== "string" || !STORED_HOUR.test(end)) return null;
    return { cantidad_jabas: jabas, hora_inicio: start, hora_fin: end };
}

// Reutilizable por P1-13 (M6-C): el parser puro de los tres valores del pallet, sin cambiar su comportamiento.
export const parsePalletValues = parseValues;

export const parseP112Capture = (value: unknown): P112Capture | null => parseCaptureOf(value, parseValues, P1_12_CODE);
export const parseP112Submission = (value: unknown): P112Submission | null => parseSubmissionOf(value, parseP112Capture);
export const parseP112List = (value: unknown): P112Capture[] | null => parseCaptureListOf(value, parseP112Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------------

export type P112Draft = { cantidad_jabas: string; hora_inicio: string; hora_fin: string };
export const EMPTY_P112_DRAFT: P112Draft = { cantidad_jabas: "", hora_inicio: "", hora_fin: "" };
export const P112_LABELS = { cantidad_jabas: "Cantidad de jabas", hora_inicio: "Hora inicio del pallet", hora_fin: "Hora fin del pallet" } as const;

export type P112DraftCheck = { ok: true; values: P112Values } | { ok: false; errors: string[] };

export function normalizeP112Draft(draft: P112Draft): P112DraftCheck {
    const errors: string[] = [];
    const jabas = draft.cantidad_jabas.trim(), start = draft.hora_inicio.trim(), end = draft.hora_fin.trim();
    if (!jabas) errors.push(`${P112_LABELS.cantidad_jabas}: es obligatorio.`);
    else if (!INTEGER.test(jabas) || !Number.isSafeInteger(Number(jabas))) errors.push(`${P112_LABELS.cantidad_jabas}: debe ser un número entero.`);
    for (const [key, text] of [["hora_inicio", start], ["hora_fin", end]] as const) {
        if (!text) errors.push(`${P112_LABELS[key]}: es obligatorio.`);
        else if (!HOUR.test(text)) errors.push(`${P112_LABELS[key]}: debe tener formato HH:MM.`);
    }
    if (errors.length) return { ok: false, errors };
    return { ok: true, values: { cantidad_jabas: Number(jabas), hora_inicio: start, hora_fin: end } };
}

export type P112Payload = { capture_id: string; form_code: typeof P1_12_CODE; assignment_id: string; device_key: string; values: P112Values };

export function buildP112Payload(captureId: string, assignmentId: string, deviceKey: string, values: P112Values): P112Payload {
    return { capture_id: captureId, form_code: P1_12_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

export type P112Attempt = PendingAttemptOf<P112Payload, P112Draft>;

export function createP112Attempt(draft: P112Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P112Attempt } | { ok: false; errors: string[] } {
    const check = normalizeP112Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP112Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------------

export type P112SubmitDeps = SubmitDepsOf<P112Payload, P112Submission, P112Capture>;
export type P112SubmitOutcome = SubmitOutcomeOf<P112Capture>;

export const submitP112Attempt = (attempt: P112Attempt, deps: P112SubmitDeps): Promise<P112SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP112 = (captureId: string, deps: P112SubmitDeps): Promise<P112SubmitOutcome> => reconcileOf(captureId, deps);

// ---- CLOUD-DEP G.12-C4-FINAL25: contrato REAL (20 campos manuales de la definición legacy, en su orden) -----------------------------------
// Fuente única: form-definitions.ts / form_12_produccion_diaria_de_papel_higienico. Automáticos excluidos (fecha, operador, turno, grupo,
// maquina, merma_maquina, merma_maquina_kg, firma_operador, firma_encargada); calculados excluidos (empaque/subempaque/bolsa/segundas/asas
// _saldo_final, merma_logs, merma_cola, total_produccion): sin fórmula aprobada, no se calculan ni se aceptan del cliente.
export const P112_FIELDS: readonly FieldSpec[] = [
    { key: "empaque_saldo_inicial", label: "Empaque saldo inicial", kind: "text", required: true },
    { key: "empaque_solicitado", label: "Empaque solicitado", kind: "text", required: true },
    { key: "empaque_utilizado", label: "Empaque utilizado", kind: "text", required: true },
    { key: "subempaque_saldo_inicial", label: "Subempaque saldo inicial", kind: "text", required: true },
    { key: "subempaque_solicitado", label: "Subempaque solicitado", kind: "text", required: true },
    { key: "subempaque_utilizado", label: "Subempaque utilizado", kind: "text", required: true },
    { key: "bolsa_saldo_inicial", label: "Bolsa saldo inicial", kind: "text", required: true },
    { key: "bolsa_solicitado", label: "Bolsa solicitado", kind: "text", required: true },
    { key: "bolsa_utilizado", label: "Bolsa utilizado", kind: "text", required: true },
    { key: "segundas_saldo_inicial", label: "Segundas saldo inicial", kind: "text", required: true },
    { key: "segundas_solicitado", label: "Segundas solicitado", kind: "text", required: true },
    { key: "segundas_utilizado", label: "Segundas utilizado", kind: "text", required: true },
    { key: "asas_saldo_inicial", label: "Asas saldo inicial", kind: "text", required: true },
    { key: "asas_solicitado", label: "Asas solicitado", kind: "text", required: true },
    { key: "asas_utilizado", label: "Asas utilizado", kind: "text", required: true },
    { key: "codigo_producto", label: "Código producto", kind: "text", required: true },
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "formato", label: "Formato", kind: "text", required: true }, // MF-10 (MD_Ejec 43): texto libre (4*12, 4X12, 4x12, 4.12); se guarda exactamente como se digita. La v1 era decimal.
    { key: "cantidad_producida_jabas", label: "Cantidad producida jabas", kind: "text", required: true },
    { key: "cantidad_producida_segundas", label: "Cantidad producida segundas", kind: "text", required: true },
];
export const P112 = defineCandidateForm(P1_12_CODE, P112_FIELDS);

export const P112_AUTOMATIC = ["Fecha", "Operador", "Turno", "Grupo", "Máquina", "Merma de máquina", "Merma de máquina (kg)", "Firma del operador", "Firma de la encargada"] as const;
export const P112_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Saldos finales y mermas", pending: "8 campos calculados de la definición legacy (saldos finales de empaque/subempaque/bolsa/segundas/asas, merma de logs, merma de cola, producción total): sin fórmula aprobada, no se calculan ni se aceptan del cliente." },
    { label: "Firma", pending: "La definición legacy declara firma del operador y firma de la encargada; sin mecanismo de firma en el modelo central, no se simulan." },
];
