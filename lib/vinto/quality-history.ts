// Historial de controles de Calidad de UNA Bobina física (GET /api/quality/bobbins/{id}/captures). SOLO lectura. PURO (sin red, sin DOM,
// sin imports en tiempo de ejecución) para probarlo con Node: el parser estricto de P1-19 (parseQualityCapture) entra inyectado y NO se
// relaja ni se reemplaza. El backend es la autoridad del orden (captured_at DESC, id DESC): aquí no se reordena, no se filtra ni se calcula
// nada que se guarde. Si un registro no se puede identificar o pertenece a otra Bobina, se rechaza la respuesta COMPLETA (nunca se oculta
// en silencio un control). Un formulario sin visor específico se muestra solo con sus metadatos; sus valores no se interpretan.

import type { QualityApiLike, QualityCapture } from "./quality-captures.ts"; // solo tipos: se borran al compilar
import type { Resource } from "./use-central.ts";

export const PLANT_TIME_ZONE = "America/La_Paz";

export type QualityHistoryMeta = Omit<QualityCapture, "values">;
export type QualityHistoryEntry =
    | { kind: "humidity"; meta: QualityHistoryMeta; capture: QualityCapture } // P1-19 que pasó su validación estricta
    | { kind: "invalid"; meta: QualityHistoryMeta } // formulario con visor cuyos datos NO pasan su validación: error seguro, sin mediciones
    | { kind: "unsupported"; meta: QualityHistoryMeta }; // formulario todavía sin visor: solo metadatos
export type QualityBobbinHistory = { bobbinId: string; entries: QualityHistoryEntry[] };
export type ExpectedBobbin = { id: string; code: string };
// Formularios con visor específico: código -> parser ESTRICTO de ese formulario. Hoy solo P1-19 ({ [Q19_FORM_CODE]: parseQualityCapture }).
export type HistoryViewers = Readonly<Record<string, (raw: unknown) => QualityCapture | null>>;

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isPositiveInt = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const pair = (value: unknown): { code: string; name: string } | null =>
    isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
// Instante ISO con zona EXPLÍCITA (timestamptz del backend). Sin zona no se puede convertir a hora de planta con seguridad.
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const isInstant = (value: unknown): value is string => typeof value === "string" && INSTANT.test(value) && !Number.isNaN(Date.parse(value));
const isDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);

// Estructura COMÚN a cualquier formulario. Los valores deben ser un objeto, pero no se copian: solo el visor específico los interpreta.
export function parseHistoryMeta(value: unknown): QualityHistoryMeta | null {
    if (!isRec(value) || !isStr(value.id) || !(value.status === "submitted" || value.status === "closed") || !isPositiveInt(value.revision)) return null;
    if (!isInstant(value.captured_at) || !(value.submitted_at === null || isInstant(value.submitted_at)) || !isDate(value.operating_date)) return null;
    const form = value.form, bobbin = value.bobbin, machine = pair(value.machine), shift = pair(value.shift), order = value.work_order, line = value.line;
    if (!isRec(form) || !isStr(form.code) || !isPositiveInt(form.version_number) || typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(bobbin) || !isStr(bobbin.id) || !isStr(bobbin.code)) return null;
    if (!isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    if (!isRec(value.values)) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, bobbin: { id: bobbin.id, code: bobbin.code }, machine, shift,
        operating_date: value.operating_date, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
    };
}

// null = respuesta inválida o inconsistente (no es lista, un registro ilegible, otra Bobina o un id repetido). Se conserva el orden recibido.
export function parseQualityBobbinHistory(value: unknown, expected: ExpectedBobbin, viewers: HistoryViewers): QualityBobbinHistory | null {
    if (!Array.isArray(value)) return null;
    const seen = new Set<string>();
    const entries: QualityHistoryEntry[] = [];
    for (const raw of value) {
        const meta = parseHistoryMeta(raw);
        if (!meta || meta.bobbin.id !== expected.id || meta.bobbin.code !== expected.code || seen.has(meta.id)) return null;
        seen.add(meta.id);
        const viewer = Object.prototype.hasOwnProperty.call(viewers, meta.form.code) ? viewers[meta.form.code] : null;
        if (!viewer) { entries.push({ kind: "unsupported", meta }); continue; }
        const capture = viewer(raw); // validación ESTRICTA existente (P1-19: la de Q2); un registro inválido nunca pasa como otro formulario
        entries.push(capture && capture.id === meta.id && capture.bobbin.id === expected.id ? { kind: "humidity", meta, capture } : { kind: "invalid", meta });
    }
    return { bobbinId: expected.id, entries };
}

// ---- resultado de la consulta -------------------------------------------------------------------------------------------------

export type HistoryFailure = "session" | "forbidden" | "not_found" | "network" | "unavailable" | "invalid_response";
export type QualityHistoryLoad = { bobbinId: string; ok: true; history: QualityBobbinHistory } | { bobbinId: string; ok: false; failure: HistoryFailure };

// Clasifica la respuesta HTTP. status 0 = sin respuesta (red o tiempo agotado); 2xx sin datos = el parser rechazó el cuerpo.
export function qualityHistoryLoad(bobbinId: string, result: QualityApiLike<QualityBobbinHistory>): QualityHistoryLoad {
    if (result.ok) return result.data.bobbinId === bobbinId ? { bobbinId, ok: true, history: result.data } : { bobbinId, ok: false, failure: "invalid_response" };
    const { status } = result;
    const failure: HistoryFailure = status === 401 ? "session" : status === 403 ? "forbidden" : status === 404 ? "not_found" : status === 0 ? "network"
        : status >= 200 && status < 300 ? "invalid_response" : "unavailable";
    return { bobbinId, ok: false, failure };
}

// Lo que se muestra para la Bobina SELECCIONADA: un resultado de otra Bobina (respuesta tardía) nunca se presenta; se ve como "cargando".
export function historyForBobbin(view: Resource<QualityHistoryLoad>, bobbinId: string): Resource<QualityHistoryLoad> {
    return view.status === "ready" && view.data.bobbinId !== bobbinId ? { status: "loading" } : view;
}

// ---- presentación -------------------------------------------------------------------------------------------------------------

export const HISTORY_MESSAGES = {
    empty: "Esta bobina no tiene controles de Calidad registrados.",
    unsupported: "Detalle de este formulario todavía no disponible",
    invalidEntry: "Los datos de este control no superan la validación del formulario. No se muestran sus mediciones.",
    noSubmitted: "No disponible",
} as const;

export const HISTORY_FAILURE_MESSAGES: Record<HistoryFailure, string> = {
    session: "La sesión ya no es válida.",
    forbidden: "No tienes permisos para consultar los controles de Calidad.",
    not_found: "La bobina no existe o ya no está disponible.",
    network: "No se pudo conectar con el servidor. Revisa la conexión y reintenta.",
    unavailable: "El servidor de Calidad no está disponible en este momento.",
    invalid_response: "La respuesta del servidor no es válida. No se muestra el historial para evitar datos incompletos.",
};

export const captureStatusLabel = (status: string): string => (status === "submitted" ? "Captura enviada" : status === "closed" ? "Captura cerrada" : status);

const PLANT_FORMAT = new Intl.DateTimeFormat("en-CA", { timeZone: PLANT_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });

// Instante -> "dd/mm/aaaa hh:mm:ss" en hora de planta. La fecha operativa NO pasa por aquí: es un dato histórico independiente.
export function formatPlantInstant(iso: string): string {
    const parts: Record<string, string> = {};
    for (const part of PLANT_FORMAT.formatToParts(new Date(Date.parse(iso)))) parts[part.type] = part.value;
    return `${parts.day}/${parts.month}/${parts.year} ${parts.hour}:${parts.minute}:${parts.second}`;
}
