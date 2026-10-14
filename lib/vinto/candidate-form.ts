// Captura CENTRAL CANDIDATA de un formulario de producción de campos de TEXTO / DECIMAL declarados (DEV-B1): una sola definición declarativa (FieldSpec) produce el parser estricto de las respuestas, el
// borrador, la validación ESTRUCTURAL, el payload, el intento pendiente y el flujo de envío con reconciliación. Reutiliza el núcleo común (capture-core.ts); no duplica el motor ni el servicio de captura.
// Pensado para que los siguientes lotes de fichas simples declaren sus campos y obtengan el circuito completo (ver P1-05 y P1-31).
//
// NO inventa reglas industriales: solo exige lo que el contrato candidato declara (campo obligatorio, texto o decimal). Un campo de texto no se interpreta (ni cantidades, ni códigos, ni unidades);
// un campo decimal solo exige el formato que el backend ya valida. Sin cálculos, catálogos, rangos ni inventario. Todo es PURO (sin red ni DOM).

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

export type FieldKind = "text" | "decimal" | "textarea";
export type FieldSpec = { key: string; label: string; kind: FieldKind; required: boolean; hint?: string; suffix?: string };
export type CandidateValues = Record<string, string>; // los opcionales ausentes no figuran
export type CandidateCapture = CaptureOf<CandidateValues>;
export type CandidateSubmission = SubmissionOf<CandidateCapture>;
export type CandidateDraft = Record<string, string>;
export type CandidatePayload = { capture_id: string; form_code: string; assignment_id: string; device_key: string; values: CandidateValues };
export type CandidateAttempt = PendingAttemptOf<CandidatePayload, CandidateDraft>;
export type CandidateDraftCheck = { ok: true; values: CandidateValues } | { ok: false; errors: string[] };
export type CandidateSubmitDeps = SubmitDepsOf<CandidatePayload, CandidateSubmission, CandidateCapture>;
export type CandidateSubmitOutcome = SubmitOutcomeOf<CandidateCapture>;

const isDecimalText = (value: unknown): value is string => typeof value === "string" && value.length <= MAX_DECIMAL_CHARS && DECIMAL.test(value);

export function defineCandidateForm(code: string, fields: readonly FieldSpec[]) {
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
    const parseCapture = (value: unknown): CandidateCapture | null => parseCaptureOf(value, parseValues, code);
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

    const buildPayload = (captureId: string, assignmentId: string, deviceKey: string, values: CandidateValues): CandidatePayload =>
        ({ capture_id: captureId, form_code: code, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } });

    function createAttempt(draft: CandidateDraft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: CandidateAttempt } | { ok: false; errors: string[] } {
        const check = normalizeDraft(draft);
        if (!check.ok) return check;
        return { ok: true, attempt: freezeAttempt(buildPayload(makeId(), assignmentId, deviceKey, check.values), draft) };
    }

    const submitAttempt = (attempt: CandidateAttempt, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => submitAttemptOf(attempt, deps);
    const reconcile = (captureId: string, deps: CandidateSubmitDeps): Promise<CandidateSubmitOutcome> => reconcileOf(captureId, deps);

    return { code, fields, parseValues, parseCapture, parseSubmission, parseList, emptyDraft, normalizeDraft, buildPayload, createAttempt, submitAttempt, reconcile };
}

export type CandidateForm = ReturnType<typeof defineCandidateForm>;
