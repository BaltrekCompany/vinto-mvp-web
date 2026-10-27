// MF-10 · versión 2 (MD_Ejec 30 y 47): se retiran «Peso fardo» (lote) y «Peso» por formato; «Tipo de tubete» pasa a «Formato de tubete» (misma clave); el espesor muestra mm; los diámetros interno y externo son TEXTO
// (un solo campo cada uno, por ejemplo «77-78»; no se interpretan, convierten ni normalizan) y se añaden «Hora inicio» y «Hora fin» (HH:MM, hora local de planta, obligatorias desde la v2; sin cálculo de duración ni validación
// de orden). La unidad en METROS pedida para el formato NO está confirmada: no se añade «m» a ningún campo. Las filas repetibles no cambian. La versión 1 y sus capturas se conservan: el parser lee cada captura con la
// definición de SU versión (P129_GROUPS_V1 y `peso_fardo` solo para v1).
// Captura CENTRAL CANDIDATA de VINTO-P1-29 «Producción Tubetera» (M3-B): especificación de campos y grupos, borrador, validación ESTRUCTURAL, payload, intento pendiente y parsers.
// Reutiliza el núcleo común (capture-core.ts) y los grupos repetibles (capture-groups.ts); aporta su parser con el código esperado «VINTO-P1-29» (una respuesta de F6, P1-10 o de
// otro formulario nunca pasa por P1-29). PURO: sin red ni DOM.
//
// ESTA FICHA ES CANDIDATA Y NO ESTÁ HOMOLOGADA. La agrupación (campos simples + grupos «rodelas» y «formatos») es una PROPUESTA técnica basada en la clasificación legacy
// («Detalle repetible», «Detalle repetible por formato», «dato global»), no una decisión industrial. Claves y tipos son los de la definición legacy (las cantidades siguen siendo
// TEXTO, los decimales siguen siendo decimales conservados como texto hasta la API). No hay catálogo de tipos de tubete, ni reglas de rango, ni responsable/visto bueno: ver
// docs/M3-B-p1-29-tubetera.md. P1-29 NO está en la política de captura central del backend ni Rebobinado es un sector operativo.

import {
    freezeAttempt, isRec, newCaptureId, parseCaptureOf, parseSubmissionOf, parseCaptureListOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { buildGroupedValues, buildGroups, groupedValuesParser, initialDrafts, type GroupDrafts, type GroupSpec, type RowError } from "./capture-groups.ts";

export const P1_29_CODE = "VINTO-P1-29";
export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

// ---- especificación (claves y tipos de la definición legacy) ------------------------------------------------------------------------------------

export type SimpleKind = "text" | "textarea" | "date" | "time";
export type SimpleFieldSpec = { key: P129SimpleKey; label: string; kind: SimpleKind; required: boolean; unit?: string; hint?: string };
export type P129SimpleKey = "fecha_de_produccion" | "lote_de_produccion" | "hora_inicio" | "hora_fin" | "pegamento_total_kg" | "numero_mrp_del_sistema" | "observaciones";
export const P129_V2 = 2; // primera versión sin «peso_fardo» / «peso_kg_por_formato», con horas y diámetros de texto

export const P129_SIMPLE_FIELDS: readonly SimpleFieldSpec[] = [
    { key: "fecha_de_produccion", label: "Fecha de producción", kind: "date", required: true, hint: "Campo manual de la ficha: no se reemplaza por la fecha operativa de la asignación." },
    { key: "lote_de_produccion", label: "Lote de producción", kind: "text", required: true },
    { key: "hora_inicio", label: "Hora inicio", kind: "time", required: true, hint: "Hora local de planta (HH:MM). No es la hora de registro del sistema." },
    { key: "hora_fin", label: "Hora fin", kind: "time", required: true, hint: "Hora local de planta (HH:MM). No es la hora de registro del sistema." },
    { key: "pegamento_total_kg", label: "Pegamento total", kind: "text", required: true, unit: "kg", hint: "Una sola cantidad global por lote/turno. Tipo declarado: texto; formato por confirmar." },
    { key: "numero_mrp_del_sistema", label: "Número MRP del sistema", kind: "text", required: true, hint: "Se digita; este sistema no genera ni valida el número MRP." },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];

// Grupos de la versión 1 (sin cambios, solo para LEER capturas antiguas): incluyen «Peso» por formato y los diámetros decimales.
export const P129_GROUPS_V1: readonly GroupSpec[] = [
    { code: "rodelas", label: "Rodelas de papel kraft", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "rodela_papel_kraft_identificacion", label: "Identificación de la rodela / lote", kind: "text", required: true },
        { key: "rodela_papel_kraft_peso_kg", label: "Peso de la rodela", kind: "decimal", required: true, unit: "kg" },
    ] },
    { code: "formatos", label: "Formatos de tubete", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "formato_tipo_de_tubete", label: "Tipo de tubete", kind: "text", required: true },
        { key: "cantidad_tubetes_producidos_por_formato", label: "Cantidad de tubetes producidos", kind: "text", required: true },
        { key: "cantidad_tubetes_observados_por_formato", label: "Cantidad de tubetes observados", kind: "textarea", required: false },
        { key: "merma_kg_por_formato", label: "Merma", kind: "decimal", required: true, unit: "kg" },
        { key: "diametro_interno_mm_por_formato", label: "Diámetro interno", kind: "decimal", required: true, unit: "mm" },
        { key: "diametro_externo_mm_por_formato", label: "Diámetro externo", kind: "decimal", required: true, unit: "mm" },
        { key: "cantidad_de_hojas_por_formato", label: "Cantidad de hojas", kind: "text", required: true },
        { key: "espesor_mm_por_formato", label: "Espesor", kind: "decimal", required: true },
        { key: "peso_kg_por_formato", label: "Peso", kind: "decimal", required: true, unit: "kg" },
    ] },
];

// Grupos CANDIDATOS (versión 2). `minRows`/`maxRows`/`repeatable` son HIPÓTESIS de prueba (idénticas a las del fixture de backend), no reglas industriales: la definición legacy no declara límites.
export const P129_GROUPS: readonly GroupSpec[] = [
    { code: "rodelas", label: "Rodelas de papel kraft", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "rodela_papel_kraft_identificacion", label: "Identificación de la rodela / lote", kind: "text", required: true },
        { key: "rodela_papel_kraft_peso_kg", label: "Peso de la rodela", kind: "decimal", required: true, unit: "kg" },
    ] },
    { code: "formatos", label: "Formatos de tubete", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "formato_tipo_de_tubete", label: "Formato de tubete", kind: "text", required: true }, // MF-10: antes «Tipo de tubete»; la clave no cambia. Texto libre (sin catálogo)
        { key: "cantidad_tubetes_producidos_por_formato", label: "Cantidad de tubetes producidos", kind: "text", required: true },
        { key: "cantidad_tubetes_observados_por_formato", label: "Cantidad de tubetes observados", kind: "textarea", required: false },
        { key: "merma_kg_por_formato", label: "Merma", kind: "decimal", required: true, unit: "kg" },
        { key: "diametro_interno_mm_por_formato", label: "Diámetro interno", kind: "text", required: true, unit: "mm" }, // MF-10: texto, por ejemplo «77-78»; no se interpreta ni normaliza
        { key: "diametro_externo_mm_por_formato", label: "Diámetro externo", kind: "text", required: true, unit: "mm" },
        { key: "cantidad_de_hojas_por_formato", label: "Cantidad de hojas", kind: "text", required: true },
        { key: "espesor_mm_por_formato", label: "Espesor", kind: "decimal", required: true, unit: "mm" }, // MF-10: unidad mm
    ] },
];

// Campos contextuales de la fuente (automáticos): NO se capturan ni se almacenan como manuales simulados.
export const CONTEXT_NOTES: Readonly<Record<"operador" | "turno" | "visto_bueno_responsable", { origin: string; pending: string }>> = {
    operador: { origin: "Sin regla definida.", pending: "Por confirmar: no se asume que sea el usuario autenticado (la fuente propone usuario, turno activo o catálogo)." },
    turno: { origin: "Se toma del turno de la asignación (el servidor lo deriva; no se digita).", pending: "Por confirmar: los turnos reales de Rebobinado (los de prueba son ficticios)." },
    visto_bueno_responsable: { origin: "Sin mecanismo definido.", pending: "Por definir: responsable, mecanismo y efecto sobre la aprobación; no se simula ningún visto bueno." },
};

// Discrepancias y decisiones abiertas (se muestran tal cual; NO se corrigen por suposición).
export const P129_PENDING: readonly { id: string; title: string; detail: string }[] = [
    { id: "maquina", title: "Nombre de la máquina", detail: "La definición del frontend dice «tubertera»; el catálogo candidato identifica TUBETERA. No se corrige por suposición." },
    { id: "espesor", title: "Unidad del espesor", detail: "El espesor se muestra en mm (MF-10). La unidad en METROS pedida para el formato de tubete no está confirmada: no se añade «m» a ningún campo." },
    { id: "diametros", title: "Diámetros", detail: "Interno y externo son texto (por ejemplo «77-78»): se guardan tal como se digitan, sin interpretar ni convertir." },
    { id: "horas", title: "Horas de inicio y fin", detail: "Se digitan (HH:MM, hora local de planta) y son obligatorias desde la versión 2; no se calcula la duración ni se valida el orden, y no se asume otra fecha si cruzan la medianoche." },
    { id: "catalogo", title: "Tipos de tubete", detail: "La fuente propone un catálogo controlado que aún no existe; hoy es texto libre." },
    { id: "visto-bueno", title: "Visto bueno y responsable", detail: "Hay que confirmar responsable, mecanismo y efectos sobre la aprobación; no se crea ninguna firma ni aprobación ficticia." },
    { id: "alcance", title: "Alcance de los grupos", detail: "La cantidad de filas de rodelas y formatos por lote/turno, y si cada grupo es obligatorio, requieren validación (los límites de prueba son hipótesis)." },
];

// ---- valores y respuestas -----------------------------------------------------------------------------------------------------------------------

export type P129Simple = { fecha_de_produccion: string; lote_de_produccion: string; pegamento_total_kg: string; numero_mrp_del_sistema: string; peso_fardo?: string; hora_inicio?: string; hora_fin?: string; observaciones?: string }; // peso_fardo: solo v1; horas: desde la v2
export type P129Values = P129Simple & { _groups: Record<string, Record<string, unknown>[]> };
export type P129Capture = CaptureOf<P129Values>;
export type P129Submission = SubmissionOf<P129Capture>;

export const isIsoDate = (value: string): boolean => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};
const nonEmpty = (value: unknown): value is string => typeof value === "string" && value !== "";

const STORED_HOUR = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/; // el cliente envía HH:MM; PostgreSQL devuelve HH:MM:SS
const HOUR = /^([01]\d|2[0-3]):[0-5]\d$/;

// Campos simples de la versión 1 (con «peso_fardo», sin horas): solo para LEER capturas antiguas.
function parseSimpleV1(value: unknown): P129Simple | null {
    if (!isRec(value)) return null;
    const { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, peso_fardo: bale, numero_mrp_del_sistema: mrp, observaciones: notes } = value;
    if (!nonEmpty(date) || !isIsoDate(date) || !nonEmpty(lot) || !nonEmpty(glue) || !nonEmpty(bale) || !nonEmpty(mrp)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: P129Simple = { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, peso_fardo: bale, numero_mrp_del_sistema: mrp };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

// Campos simples de la versión 2: sin «peso_fardo» y con las dos horas obligatorias.
function parseSimple(value: unknown): P129Simple | null {
    if (!isRec(value)) return null;
    const { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, hora_inicio: start, hora_fin: end, numero_mrp_del_sistema: mrp, observaciones: notes } = value;
    if (!nonEmpty(date) || !isIsoDate(date) || !nonEmpty(lot) || !nonEmpty(glue) || !nonEmpty(mrp)) return null;
    if (typeof start !== "string" || !STORED_HOUR.test(start) || typeof end !== "string" || !STORED_HOUR.test(end)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: P129Simple = { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, hora_inicio: start, hora_fin: end, numero_mrp_del_sistema: mrp };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

const parseValuesV1 = groupedValuesParser(parseSimpleV1, P129_GROUPS_V1);
const parseValuesV2 = groupedValuesParser(parseSimple, P129_GROUPS);
// Cada captura se interpreta con la definición de SU versión.
export const parseP129Values = (value: unknown, version?: number): P129Values | null => (version !== undefined && version < P129_V2 ? parseValuesV1(value) : parseValuesV2(value)) as P129Values | null;
export const parseP129Capture = (value: unknown): P129Capture | null => parseCaptureOf(value, parseP129Values, P1_29_CODE);
export const parseP129Submission = (value: unknown): P129Submission | null => parseSubmissionOf(value, parseP129Capture);
export const parseP129List = (value: unknown): P129Capture[] | null => parseCaptureListOf(value, parseP129Capture);

// ---- borrador, validación estructural y payload ---------------------------------------------------------------------------------------------------

export type P129Draft = { simple: Record<P129SimpleKey, string>; groups: GroupDrafts };
export const emptyP129Draft = (makeKey?: () => string): P129Draft => ({
    simple: { fecha_de_produccion: "", lote_de_produccion: "", hora_inicio: "", hora_fin: "", pegamento_total_kg: "", numero_mrp_del_sistema: "", observaciones: "" },
    groups: initialDrafts(P129_GROUPS, makeKey),
});

export type P129Check = { ok: true; values: Record<string, unknown> } | { ok: false; errors: RowError[] };

// Solo lo estructural: texto/fecha obligatorios no vacíos y el límite técnico; los grupos usan capture-groups (decimales como TEXTO con punto, sin float). No inventa formato,
// rango, unicidad, catálogo ni conversión de cantidades.
export function normalizeP129Draft(draft: P129Draft): P129Check {
    const errors: RowError[] = [];
    const simple: Record<string, unknown> = {};
    for (const field of P129_SIMPLE_FIELDS) {
        const text = (draft.simple[field.key] ?? "").trim();
        if (!text) { if (field.required) errors.push({ group: "", row: null, field: field.key, message: `${field.label}: es obligatorio.` }); continue; }
        if (text.length > MAX_TEXT_LENGTH) { errors.push({ group: "", row: null, field: field.key, message: `${field.label}: supera ${MAX_TEXT_LENGTH} caracteres.` }); continue; }
        if (field.kind === "date" && !isIsoDate(text)) { errors.push({ group: "", row: null, field: field.key, message: `${field.label}: ingresa una fecha válida (AAAA-MM-DD).` }); continue; }
        if (field.kind === "time" && !HOUR.test(text)) { errors.push({ group: "", row: null, field: field.key, message: `${field.label}: debe ser una hora válida HH:MM (por ejemplo 07:30).` }); continue; }
        simple[field.key] = text;
    }
    const built = buildGroups(P129_GROUPS, draft.groups);
    if (!built.ok) errors.push(...built.errors);
    return errors.length || !built.ok ? { ok: false, errors } : { ok: true, values: buildGroupedValues(simple, built.groups) };
}

export type P129Payload = { capture_id: string; form_code: typeof P1_29_CODE; assignment_id: string; device_key: string; values: Record<string, unknown> };
export const buildP129Payload = (captureId: string, assignmentId: string, deviceKey: string, values: Record<string, unknown>): P129Payload =>
    ({ capture_id: captureId, form_code: P1_29_CODE, assignment_id: assignmentId, device_key: deviceKey, values });

export type P129Attempt = PendingAttemptOf<P129Payload, P129Draft>;

export function createP129Attempt(draft: P129Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P129Attempt } | { ok: false; errors: RowError[] } {
    const check = normalizeP129Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP129Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ------------------------------------------------------------------------------

export type P129SubmitDeps = SubmitDepsOf<P129Payload, P129Submission, P129Capture>;
export type P129SubmitOutcome = SubmitOutcomeOf<P129Capture>;
export const submitP129Attempt = (attempt: P129Attempt, deps: P129SubmitDeps): Promise<P129SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP129 = (captureId: string, deps: P129SubmitDeps): Promise<P129SubmitOutcome> => reconcileOf(captureId, deps);
