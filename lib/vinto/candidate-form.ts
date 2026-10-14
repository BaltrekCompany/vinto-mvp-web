// Captura CENTRAL CANDIDATA de un formulario de campos de TEXTO / DECIMAL declarados (DEV-B1, ampliado en DEV-Q1): una sola definición declarativa (FieldSpec) produce el parser estricto de las respuestas, el
// borrador, la validación ESTRUCTURAL, el payload, el intento pendiente y el flujo de envío con reconciliación. Reutiliza el núcleo común (capture-core.ts); no duplica el motor ni el servicio de captura.
// Dos contextos de captura:
//   - "assignment" (por defecto, Producción: P1-04, P1-05, P1-31): el contexto es la asignación activa (OT, línea, turno, fecha) y el POST es /api/captures.
//   - "machine" (Calidad por máquina: P1-22, P1-26): SIN bobina, asignación ni OT; el contexto es la máquina y el backend resuelve turno, fecha operativa y usuario al REGISTRAR. El POST es
//     /api/quality/machines/{máquina}/captures y `captured_at` es la hora de registro, no la del ensayo.
//
// NO inventa reglas industriales: solo exige lo que el contrato candidato declara (campo obligatorio, texto o decimal). Un campo de texto no se interpreta; un decimal solo exige el formato que el backend ya
// valida. Sin cálculos, catálogos, rangos, límites ni inventario. Todo es PURO (sin red ni DOM).

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, isStr, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureEnvelope, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

export type FieldKind = "text" | "decimal" | "textarea";
export type FieldSpec = { key: string; label: string; kind: FieldKind; required: boolean; hint?: string; suffix?: string };
export type CandidateContext = "assignment" | "machine";
export type CandidateValues = Record<string, string>; // los opcionales ausentes no figuran
// Respuesta de una captura: la de Producción lleva asignación, OT y línea; la de Calidad por máquina no (lleva `recorded_by`). Los campos de contexto son opcionales para poder tratar ambas igual.
export type CandidateCapture = Omit<CaptureEnvelope, "assignment" | "work_order" | "line"> & Partial<Pick<CaptureEnvelope, "assignment" | "work_order" | "line">>
    & { recorded_by?: { id: string; display_name: string } | null; values: CandidateValues };
export type CandidateSubmission = SubmissionOf<CandidateCapture>;
export type CandidateDraft = Record<string, string>;
// `assignment_id` (contexto "assignment") o `machine_code` (contexto "machine"): exactamente uno de los dos. El POST de Calidad por máquina lleva `machine_code` en la ruta, no en el cuerpo.
export type CandidatePayload = { capture_id: string; form_code: string; device_key: string; values: CandidateValues; assignment_id?: string; machine_code?: string };
export type CandidateAttempt = PendingAttemptOf<CandidatePayload, CandidateDraft>;
export type CandidateDraftCheck = { ok: true; values: CandidateValues } | { ok: false; errors: string[] };
export type CandidateSubmitDeps = SubmitDepsOf<CandidatePayload, CandidateSubmission, CandidateCapture>;
export type CandidateSubmitOutcome = SubmitOutcomeOf<CandidateCapture>;

const isDecimalText = (value: unknown): value is string => typeof value === "string" && value.length <= MAX_DECIMAL_CHARS && DECIMAL.test(value);
const pair = (value: unknown): { code: string; name: string } | null => isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;

// Respuesta de Calidad por máquina: sin asignación, OT ni línea. Se rechaza una captura de OTRO formulario.
function parseMachineEnvelope(value: unknown, parseValues: (values: unknown) => CandidateValues | null, expectedFormCode: string): CandidateCapture | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.status) || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision)) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, machine = pair(value.machine), shift = pair(value.shift), by = value.recorded_by;
    if (!isRec(form) || form.code !== expectedFormCode || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (!(by === null || by === undefined || (isRec(by) && isStr(by.id) && typeof by.display_name === "string"))) return null;
    const values = parseValues(value.values);
    if (values === null) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, machine, shift, operating_date: value.operating_date,
        recorded_by: isRec(by) ? { id: by.id as string, display_name: by.display_name as string } : null, values,
    };
}

export function defineCandidateForm(code: string, fields: readonly FieldSpec[], options: { context?: CandidateContext } = {}) {
    const context: CandidateContext = options.context ?? "assignment";
    const keys = fields.map((f) => f.key);
    if (new Set(keys).size !== keys.length || keys.includes("_groups")) throw new Error(`Definición candidata inválida: ${code}`);

    // Parser ESTRICTO de las respuestas del backend: obligatorios presentes y no vacíos (decimales con formato decimal), opcionales ausentes o texto; lo demás se ignora.
    function parseValues(value: unknown): CandidateValues | null {
        if (!isRec(value)) return null;
        const clean: CandidateValues = {};
        for (const field of fields) {
            const raw = value[field.key];
            if (raw === undefined) { if (field.required) return null; continue; }
            if (typeof raw !== "string") return null;
            if (field.required && raw === "") return null;
            if (field.kind === "decimal" && !isDecimalText(raw)) return null;
            clean[field.key] = raw;
        }
        return clean;
    }
    const parseCapture = (value: unknown): CandidateCapture | null => context === "machine" ? parseMachineEnvelope(value, parseValues, code) : parseCaptureOf(value, parseValues, code);
    const parseSubmission = (value: unknown): CandidateSubmission | null => parseSubmissionOf(value, parseCapture);
    const parseList = (value: unknown): CandidateCapture[] | null => parseCaptureListOf(value, parseCapture);

    const emptyDraft = (): CandidateDraft => Object.fromEntries(keys.map((k) => [k, ""]));

    // Validación ESTRUCTURAL del borrador. Texto: recortado, obligatorio y con el tope técnico. Decimal: coma o punto (el backend solo acepta el punto); es la ÚNICA normalización.
    function normalizeDraft(draft: CandidateDraft): CandidateDraftCheck {
        const errors: string[] = [];
        const values: CandidateValues = {};
        for (const field of fields) {
            let text = (draft[field.key] ?? "").trim();
            if (field.kind === "decimal") text = text.replace(",", ".");
            if (!text) { if (field.required) errors.push(`${field.label}: es obligatorio.`); continue; }
            if (field.kind === "decimal" && !isDecimalText(text)) { errors.push(`${field.label}: debe ser un número decimal (por ejemplo 12.5).`); continue; }
            if (text.length > MAX_TEXT_LENGTH) { errors.push(`${field.label}: supera ${MAX_TEXT_LENGTH} caracteres.`); continue; }
            values[field.key] = text;
        }
        return errors.length ? { ok: false, errors } : { ok: true, values };
    }

    // `contextId` es el assignment_id (contexto "assignment") o el código de la máquina (contexto "machine").
    const buildPayload = (captureId: string, contextId: string, deviceKey: string, values: CandidateValues): CandidatePayload => context === "machine"
        ? { capture_id: captureId, form_code: code, machine_code: contextId, device_key: deviceKey, values: { ...values } }
        : { capture_id: captureId, form_code: code, assignment_id: contextId, device_key: deviceKey, values: { ...values } };

    function createAttempt(draft: CandidateDraft, contextId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: CandidateAttempt } | { ok: false; errors: string[] } {
        const check = normalizeDraft(draft);
        if (!check.ok) return check;
        return { ok: true, attempt: freezeAttempt(buildPayload(makeId(), contextId, deviceKey, check.values), draft) };
    }

    const submitAttempt = (attempt: CandidateAttempt, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => submitAttemptOf(attempt, deps);
    const reconcile = (captureId: string, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => reconcileOf(captureId, deps);

    return { code, context, fields, parseValues, parseCapture, parseSubmission, parseList, emptyDraft, normalizeDraft, buildPayload, createAttempt, submitAttempt, reconcile };
}

export type CandidateForm = ReturnType<typeof defineCandidateForm>;
