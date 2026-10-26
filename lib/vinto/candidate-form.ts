// Captura CENTRAL CANDIDATA de un formulario de campos de TEXTO / DECIMAL declarados (DEV-B1, ampliado en DEV-Q1 y DEV-Q2): una sola definición declarativa (FieldSpec) produce el parser estricto de las respuestas, el
// borrador, la validación ESTRUCTURAL, el payload, el intento pendiente y el flujo de envío con reconciliación. Reutiliza el núcleo común (capture-core.ts); no duplica el motor ni el servicio de captura.
// Tres contextos de captura:
//   - "assignment" (por defecto, Producción: P1-04, P1-05, P1-31): el contexto es la asignación activa (OT, línea, turno, fecha) y el POST es /api/captures.
//   - "machine" (Calidad por máquina: P1-22, P1-26): SIN bobina, asignación ni OT; el contexto es la máquina y el backend resuelve turno, fecha operativa y usuario al REGISTRAR. El POST es
//     /api/quality/machines/{máquina}/captures y `captured_at` es la hora de registro, no la del ensayo.
//   - "bobbin" (Calidad ligada a UNA bobina física: P1-21): la bobina va en la ruta (POST /api/quality/bobbins/{id}/captures) y el backend deriva máquina, turno, fecha operativa y OT de la F3 de origen; la respuesta
//     lleva la bobina. No usa la asignación activa ni /api/captures y nunca libera ni rechaza la bobina.
//
// NO inventa reglas industriales: solo exige lo que el contrato candidato declara (campo obligatorio, texto o decimal). Un campo de texto no se interpreta; un decimal solo exige el formato que el backend ya
// valida. Sin cálculos, catálogos, rangos, límites ni inventario. Todo es PURO (sin red ni DOM).

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, isStr, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureEnvelope, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

export type FieldKind = "text" | "decimal" | "textarea" | "time" | "integer"; // `time` (DEV-B3): hora MANUAL HH:MM; el backend la guarda como hora real (value_time)
// `integer` (MF-06): entero NO negativo (0, 1, 2…), guardado como `integer` en PostgreSQL; el backend lo devuelve como número JSON y aquí se lee como texto.
// `sinceVersion` (MF-06): el campo existe desde esa versión del formulario; las capturas de versiones anteriores no lo traen y se leen sin exigirlo.
export type FieldSpec = { key: string; label: string; kind: FieldKind; required: boolean; hint?: string; suffix?: string; sinceVersion?: number };
export type CandidateContext = "assignment" | "machine" | "bobbin";
export type CandidateValues = Record<string, string>; // los opcionales ausentes no figuran
// Respuesta de una captura: la de Producción lleva asignación, OT y línea; la de Calidad por máquina no (lleva `recorded_by`); la de Calidad por bobina lleva `bobbin`, OT y línea, sin asignación. Los campos de
// contexto son opcionales para poder tratar todas igual.
export type CandidateCapture = Omit<CaptureEnvelope, "assignment" | "work_order" | "line"> & Partial<Pick<CaptureEnvelope, "assignment" | "work_order" | "line">>
    & { recorded_by?: { id: string; display_name: string } | null; bobbin?: { id: string; code: string }; values: CandidateValues };
export type CandidateSubmission = SubmissionOf<CandidateCapture>;
export type CandidateDraft = Record<string, string>;
// `assignment_id` (contexto "assignment"), `machine_code` ("machine") o `bobbin_id` ("bobbin"): exactamente uno. Los POST de Calidad llevan la máquina o la bobina en la ruta, no en el cuerpo.
export type CandidatePayload = { capture_id: string; form_code: string; device_key: string; values: CandidateValues; assignment_id?: string; machine_code?: string; bobbin_id?: string };
export type CandidateAttempt = PendingAttemptOf<CandidatePayload, CandidateDraft>;
export type CandidateDraftCheck = { ok: true; values: CandidateValues } | { ok: false; errors: string[] };
export type CandidateSubmitDeps = SubmitDepsOf<CandidatePayload, CandidateSubmission, CandidateCapture>;
export type CandidateSubmitOutcome = SubmitOutcomeOf<CandidateCapture>;

// Hora estructural: HH:MM o HH:MM:SS (el backend devuelve HH:MM:SS), 00-23 y 00-59. Sin zona, fracciones ni formatos alternativos; no se interpreta ni se compara con otra hora.
export const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/;
const isTimeText = (value: unknown): value is string => typeof value === "string" && TIME_PATTERN.test(value);
export const NON_NEGATIVE_INTEGER = /^\d{1,9}$/;
const isIntegerText = (value: unknown): value is string => typeof value === "string" && NON_NEGATIVE_INTEGER.test(value);
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

// Respuesta de Calidad por bobina: bobina, máquina, turno, fecha operativa, OT y línea (de la F3 de origen), sin asignación. Se rechaza una captura de OTRO formulario.
function parseBobbinEnvelope(value: unknown, parseValues: (values: unknown, version?: number) => CandidateValues | null, expectedFormCode: string): CandidateCapture | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.status) || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision)) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, bobbin = value.bobbin, machine = pair(value.machine), shift = pair(value.shift), order = value.work_order, line = value.line;
    if (!isRec(form) || form.code !== expectedFormCode || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(bobbin) || !isStr(bobbin.id) || !isStr(bobbin.code) || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parseValues(value.values, form.version_number as number);
    if (values === null) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, machine, shift, operating_date: value.operating_date,
        bobbin: { id: bobbin.id, code: bobbin.code }, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } }, values,
    };
}

// `legacy` (MF-06): campos de versiones ANTERIORES ya retirados del formulario. Nunca se digitan, no entran en el borrador ni en el payload; solo se LEEN (opcionales, con el mismo formato) para que el historial de las
// capturas antiguas siga mostrando lo que se guardó.
export function defineCandidateForm(code: string, fields: readonly FieldSpec[], options: { context?: CandidateContext; legacy?: readonly FieldSpec[] } = {}) {
    const context: CandidateContext = options.context ?? "assignment";
    const legacy = options.legacy ?? [];
    const keys = fields.map((f) => f.key);
    if (new Set([...keys, ...legacy.map((f) => f.key)]).size !== keys.length + legacy.length || keys.includes("_groups")) throw new Error(`Definición candidata inválida: ${code}`);

    // Parser ESTRICTO de las respuestas del backend: obligatorios presentes y no vacíos (decimales con formato decimal), opcionales ausentes o texto; lo demás se ignora.
    function parseValues(value: unknown, version?: number): CandidateValues | null {
        if (!isRec(value)) return null;
        const clean: CandidateValues = {};
        for (const field of fields) {
            const raw = value[field.key] === undefined ? undefined : field.kind === "integer" && typeof value[field.key] === "number" ? String(value[field.key]) : value[field.key];
            const absentOk = !field.required || (field.sinceVersion !== undefined && version !== undefined && version < field.sinceVersion); // un campo posterior a la versión de la captura no se exige
            if (raw === undefined) { if (!absentOk) return null; continue; }
            if (typeof raw !== "string") return null;
            if (field.kind === "integer" && !isIntegerText(raw)) return null;
            if (field.required && raw === "") return null;
            if (field.kind === "decimal" && !isDecimalText(raw)) return null;
            if (field.kind === "time" && !isTimeText(raw)) return null;
            clean[field.key] = raw;
        }
        for (const field of legacy) { // campos retirados: se conservan solo si la captura antigua los trae
            const raw = value[field.key];
            if (raw === undefined) continue;
            if (typeof raw !== "string" || (field.kind === "decimal" && !isDecimalText(raw))) return null;
            clean[field.key] = raw;
        }
        return clean;
    }
    const parseCapture = (value: unknown): CandidateCapture | null => context === "machine" ? parseMachineEnvelope(value, parseValues, code) : context === "bobbin" ? parseBobbinEnvelope(value, parseValues, code) : parseCaptureOf(value, parseValues, code);
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
            if (field.kind === "integer" && text && !isIntegerText(text)) { errors.push(`${field.label}: debe ser un número entero no negativo (por ejemplo 3).`); continue; }
            if (!text) { if (field.required) errors.push(`${field.label}: es obligatorio.`); continue; }
            if (field.kind === "decimal" && !isDecimalText(text)) { errors.push(`${field.label}: debe ser un número decimal (por ejemplo 12.5).`); continue; }
            if (field.kind === "time" && !isTimeText(text)) { errors.push(`${field.label}: debe ser una hora válida HH:MM (por ejemplo 07:30).`); continue; }
            if (text.length > MAX_TEXT_LENGTH) { errors.push(`${field.label}: supera ${MAX_TEXT_LENGTH} caracteres.`); continue; }
            values[field.key] = text;
        }
        return errors.length ? { ok: false, errors } : { ok: true, values };
    }

    // `contextId` es el assignment_id (contexto "assignment"), el código de la máquina ("machine") o el id de la bobina ("bobbin").
    const buildPayload = (captureId: string, contextId: string, deviceKey: string, values: CandidateValues): CandidatePayload => context === "machine"
        ? { capture_id: captureId, form_code: code, machine_code: contextId, device_key: deviceKey, values: { ...values } }
        : context === "bobbin" ? { capture_id: captureId, form_code: code, bobbin_id: contextId, device_key: deviceKey, values: { ...values } }
        : { capture_id: captureId, form_code: code, assignment_id: contextId, device_key: deviceKey, values: { ...values } };

    function createAttempt(draft: CandidateDraft, contextId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: CandidateAttempt } | { ok: false; errors: string[] } {
        const check = normalizeDraft(draft);
        if (!check.ok) return check;
        return { ok: true, attempt: freezeAttempt(buildPayload(makeId(), contextId, deviceKey, check.values), draft) };
    }

    const submitAttempt = (attempt: CandidateAttempt, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => submitAttemptOf(attempt, deps);
    const reconcile = (captureId: string, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => reconcileOf(captureId, deps);

    return { code, context, fields, legacy, parseValues, parseCapture, parseSubmission, parseList, emptyDraft, normalizeDraft, buildPayload, createAttempt, submitAttempt, reconcile };
}

export type CandidateForm = ReturnType<typeof defineCandidateForm>;
