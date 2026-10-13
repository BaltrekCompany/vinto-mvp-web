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

export type SimpleKind = "text" | "textarea" | "date";
export type SimpleFieldSpec = { key: P129SimpleKey; label: string; kind: SimpleKind; required: boolean; unit?: string; hint?: string };
export type P129SimpleKey = "fecha_de_produccion" | "lote_de_produccion" | "pegamento_total_kg" | "peso_fardo" | "numero_mrp_del_sistema" | "observaciones";

export const P129_SIMPLE_FIELDS: readonly SimpleFieldSpec[] = [
    { key: "fecha_de_produccion", label: "Fecha de producción", kind: "date", required: true, hint: "Campo manual de la ficha: no se reemplaza por la fecha operativa de la asignación." },
    { key: "lote_de_produccion", label: "Lote de producción", kind: "text", required: true },
    { key: "pegamento_total_kg", label: "Pegamento total", kind: "text", required: true, unit: "kg", hint: "Una sola cantidad global por lote/turno. Tipo declarado: texto; formato por confirmar." },
    { key: "peso_fardo", label: "Peso fardo", kind: "text", required: true, unit: "kg", hint: "Tipo declarado: texto; formato por confirmar." },
    { key: "numero_mrp_del_sistema", label: "Número MRP del sistema", kind: "text", required: true, hint: "Se digita; este sistema no genera ni valida el número MRP." },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];

// Grupos CANDIDATOS. `minRows`/`maxRows`/`repeatable` son HIPÓTESIS de prueba (idénticas a las del fixture de backend), no reglas industriales: la definición legacy no declara límites.
export const P129_GROUPS: readonly GroupSpec[] = [
    { code: "rodelas", label: "Rodelas de papel kraft", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "rodela_papel_kraft_identificacion", label: "Identificación de la rodela / lote", kind: "text", required: true },
        { key: "rodela_papel_kraft_peso_kg", label: "Peso de la rodela", kind: "decimal", required: true, unit: "kg" },
    ] },
    { code: "formatos", label: "Formatos de tubete", repeatable: true, minRows: 1, maxRows: null, fields: [
        { key: "formato_tipo_de_tubete", label: "Tipo de tubete", kind: "text", required: true }, // la fuente propone un catálogo que aún no existe: texto libre por ahora
        { key: "cantidad_tubetes_producidos_por_formato", label: "Cantidad de tubetes producidos", kind: "text", required: true },
        { key: "cantidad_tubetes_observados_por_formato", label: "Cantidad de tubetes observados", kind: "textarea", required: false },
        { key: "merma_kg_por_formato", label: "Merma", kind: "decimal", required: true, unit: "kg" },
        { key: "diametro_interno_mm_por_formato", label: "Diámetro interno", kind: "decimal", required: true, unit: "mm" },
        { key: "diametro_externo_mm_por_formato", label: "Diámetro externo", kind: "decimal", required: true, unit: "mm" },
        { key: "cantidad_de_hojas_por_formato", label: "Cantidad de hojas", kind: "text", required: true },
        { key: "espesor_mm_por_formato", label: "Espesor", kind: "decimal", required: true }, // sin unidad visible: la metadata legacy dice kg para un campo llamado mm (discrepancia sin resolver)
        { key: "peso_kg_por_formato", label: "Peso", kind: "decimal", required: true, unit: "kg" },
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
    { id: "espesor", title: "Unidad del espesor", detail: "«espesor_mm_por_formato» se llama en mm pero la metadata legacy registra kg: unidad por confirmar." },
    { id: "catalogo", title: "Tipos de tubete", detail: "La fuente propone un catálogo controlado que aún no existe; hoy es texto libre." },
    { id: "visto-bueno", title: "Visto bueno y responsable", detail: "Hay que confirmar responsable, mecanismo y efectos sobre la aprobación; no se crea ninguna firma ni aprobación ficticia." },
    { id: "alcance", title: "Alcance de los grupos", detail: "La cantidad de filas de rodelas y formatos por lote/turno, y si cada grupo es obligatorio, requieren validación (los límites de prueba son hipótesis)." },
];

// ---- valores y respuestas -----------------------------------------------------------------------------------------------------------------------

export type P129Simple = { fecha_de_produccion: string; lote_de_produccion: string; pegamento_total_kg: string; peso_fardo: string; numero_mrp_del_sistema: string; observaciones?: string };
export type P129Values = P129Simple & { _groups: Record<string, Record<string, unknown>[]> };
export type P129Capture = CaptureOf<P129Values>;
export type P129Submission = SubmissionOf<P129Capture>;

export const isIsoDate = (value: string): boolean => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};
const nonEmpty = (value: unknown): value is string => typeof value === "string" && value !== "";

function parseSimple(value: unknown): P129Simple | null {
    if (!isRec(value)) return null;
    const { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, peso_fardo: bale, numero_mrp_del_sistema: mrp, observaciones: notes } = value;
    if (!nonEmpty(date) || !isIsoDate(date) || !nonEmpty(lot) || !nonEmpty(glue) || !nonEmpty(bale) || !nonEmpty(mrp)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: P129Simple = { fecha_de_produccion: date, lote_de_produccion: lot, pegamento_total_kg: glue, peso_fardo: bale, numero_mrp_del_sistema: mrp };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

const parseValues = groupedValuesParser(parseSimple, P129_GROUPS);
export const parseP129Capture = (value: unknown): P129Capture | null => parseCaptureOf(value, parseValues as (v: unknown) => P129Values | null, P1_29_CODE);
export const parseP129Submission = (value: unknown): P129Submission | null => parseSubmissionOf(value, parseP129Capture);
export const parseP129List = (value: unknown): P129Capture[] | null => parseCaptureListOf(value, parseP129Capture);

// ---- borrador, validación estructural y payload ---------------------------------------------------------------------------------------------------

export type P129Draft = { simple: Record<P129SimpleKey, string>; groups: GroupDrafts };
export const emptyP129Draft = (makeKey?: () => string): P129Draft => ({
    simple: { fecha_de_produccion: "", lote_de_produccion: "", pegamento_total_kg: "", peso_fardo: "", numero_mrp_del_sistema: "", observaciones: "" },
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
