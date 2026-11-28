// RBE-03 · contrato tipado y reglas puras de la interfaz de Bobinas Refiladas para Exportación.
// La API/backend es la autoridad: este módulo valida la forma y la selección visual, nunca reserva ni autoriza crías.

export const REWINDING_EXPORT_SLOTS = ["A", "B", "C", "D", "E"] as const;
export type RewindingExportSlot = (typeof REWINDING_EXPORT_SLOTS)[number];
export type RewindingWorkOrderClassification = "production_confirmed" | "qa";

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const isText = (value: unknown): value is string => typeof value === "string";
const isNullableText = (value: unknown): value is string | null => value === null || isText(value);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const isUuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);
const isDecimal = (value: unknown): value is string => typeof value === "string" && DECIMAL.test(value);
const isNullableDecimal = (value: unknown): value is string | null => value === null || isDecimal(value);
const isPositiveInteger = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const isNonNegativeInteger = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const isDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
const isOffsetDateTime = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value);

function parseMachine(value: unknown): { code: string; name: string } | null {
    if (!isRec(value) || !isString(value.code) || !isText(value.name)) return null;
    return { code: value.code, name: value.name };
}

export type RewindingExportPv = { pv_reference: string; eligible_mothers: number };
export type RewindingExportProduct = { article_id: string; code: string; description: string };
export type RewindingExportMother = {
    mother_capture_id: string;
    mother_bobbin_id: string | null;
    mother_label: string;
    pv_reference: string;
    article_id: string;
    article_code: string;
    article_description: string;
    machine: { code: string; name: string };
    work_order: { id: string; number: string };
    operating_date: string;
    destination: string;
    formato_1: string;
    formato_2: string | null;
    formato_3: string | null;
    diametro: string;
    tubete: string;
    ayudante: string | null;
    operator: { user_id: string; display_name: string } | null;
};
export type RewindingExportChild = {
    bobbin_id: string;
    mother_capture_id: string;
    position: number;
    weight_kg: string;
    quality_status: "released";
};
export type RewindingExportPackageChild = {
    bobbin_id: string;
    package_slot: RewindingExportSlot;
    position: number;
    weight_kg: string;
};
export type RewindingExportPackage = {
    id: string;
    package_number: number;
    mother_capture_id: string;
    mother_label_snapshot: string;
    mother: RewindingExportMother;
    children: RewindingExportPackageChild[];
};
export type RewindingExportDraftSummary = {
    id: string;
    created_at: string;
    pv_reference: string;
    article_code: string;
    machine_code: string | null;
    package_count: number;
};
export type RewindingExportDraft = {
    id: string;
    status: "draft";
    created_at: string;
    pv_reference: string;
    article: { id: string; code: string; description: string };
    truck_number: string;
    order_number: string;
    observations: string;
    packages: RewindingExportPackage[];
};
export type RewindingExportPreview = {
    valid: boolean;
    package_count: number;
    child_count: number;
    warnings: { code: string; message: string }[];
    blocking_errors: { code: string; message: string }[];
};
export type RewindingWorkOrderOption = {
    id: string;
    number: string;
    status: "published" | "in_progress" | "closed";
    machine_code: string;
};
export type RewindingWorkOrderClassificationRecord = {
    work_order_id: string;
    classification: RewindingWorkOrderClassification | null;
    sequence_no: number | null;
    recorded_at: string | null;
    reason: string | null;
    recorded_by: { id: string; display_name: string } | null;
};

export function parseRewindingExportPv(value: unknown): RewindingExportPv | null {
    if (!isRec(value) || !isString(value.pv_reference) || !isNonNegativeInteger(value.eligible_mothers)) return null;
    return { pv_reference: value.pv_reference, eligible_mothers: value.eligible_mothers };
}
export function parseRewindingExportPvList(value: unknown): RewindingExportPv[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingExportPv);
    return items.some(item => item === null) ? null : items as RewindingExportPv[];
}
export function parseRewindingExportProduct(value: unknown): RewindingExportProduct | null {
    if (!isRec(value) || !isUuid(value.article_id) || !isString(value.code) || !isText(value.description)) return null;
    return { article_id: value.article_id, code: value.code, description: value.description };
}
export function parseRewindingExportProductList(value: unknown): RewindingExportProduct[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingExportProduct);
    return items.some(item => item === null) ? null : items as RewindingExportProduct[];
}
export function parseRewindingExportMother(value: unknown): RewindingExportMother | null {
    if (!isRec(value) || !isUuid(value.mother_capture_id) || !(value.mother_bobbin_id === null || isUuid(value.mother_bobbin_id))
        || !isString(value.mother_label) || !isString(value.pv_reference) || !isUuid(value.article_id)
        || !isString(value.article_code) || !isText(value.article_description) || !isDate(value.operating_date)
        || !isString(value.destination) || !isDecimal(value.formato_1) || !isNullableDecimal(value.formato_2)
        || !isNullableDecimal(value.formato_3) || !isDecimal(value.diametro) || !isString(value.tubete)
        || !isNullableText(value.ayudante)) return null;
    const machine = parseMachine(value.machine);
    const order = value.work_order;
    if (!machine || !isRec(order) || !isUuid(order.id) || !isString(order.number)) return null;
    let operator: RewindingExportMother["operator"] = null;
    if (value.operator !== null) {
        if (!isRec(value.operator) || !isUuid(value.operator.user_id) || !isString(value.operator.display_name)) return null;
        operator = { user_id: value.operator.user_id, display_name: value.operator.display_name };
    }
    return {
        mother_capture_id: value.mother_capture_id, mother_bobbin_id: value.mother_bobbin_id,
        mother_label: value.mother_label, pv_reference: value.pv_reference, article_id: value.article_id,
        article_code: value.article_code, article_description: value.article_description, machine,
        work_order: { id: order.id, number: order.number }, operating_date: value.operating_date,
        destination: value.destination, formato_1: value.formato_1, formato_2: value.formato_2,
        formato_3: value.formato_3, diametro: value.diametro, tubete: value.tubete,
        ayudante: value.ayudante, operator,
    };
}
export function parseRewindingExportMotherList(value: unknown): RewindingExportMother[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingExportMother);
    return items.some(item => item === null) ? null : items as RewindingExportMother[];
}
export function parseRewindingExportChild(value: unknown): RewindingExportChild | null {
    if (!isRec(value) || !isUuid(value.bobbin_id) || !isUuid(value.mother_capture_id)
        || !isPositiveInteger(value.position) || value.position > 22 || value.position === 12
        || !isDecimal(value.weight_kg) || Number(value.weight_kg) <= 0
        || value.quality_status !== "released") return null;
    return {
        bobbin_id: value.bobbin_id, mother_capture_id: value.mother_capture_id,
        position: value.position, weight_kg: value.weight_kg, quality_status: "released",
    };
}
export function parseRewindingExportChildList(value: unknown): RewindingExportChild[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingExportChild);
    return items.some(item => item === null) ? null : items as RewindingExportChild[];
}

function parsePackageChild(value: unknown): RewindingExportPackageChild | null {
    if (!isRec(value) || !isUuid(value.bobbin_id) || !REWINDING_EXPORT_SLOTS.includes(value.package_slot as RewindingExportSlot)
        || !isPositiveInteger(value.position) || value.position > 22 || value.position === 12 || !isDecimal(value.weight_kg) || Number(value.weight_kg) <= 0) return null;
    return {
        bobbin_id: value.bobbin_id, package_slot: value.package_slot as RewindingExportSlot,
        position: value.position, weight_kg: value.weight_kg,
    };
}
function parseRewindingExportPackage(value: unknown): RewindingExportPackage | null {
    if (!isRec(value) || !isUuid(value.id) || !isPositiveInteger(value.package_number)
        || !isUuid(value.mother_capture_id) || !isString(value.mother_label_snapshot) || !Array.isArray(value.children)) return null;
    const mother = parseRewindingExportMother(value.mother);
    const children = value.children.map(parsePackageChild);
    if (!mother || mother.mother_capture_id !== value.mother_capture_id || children.some(child => child === null)
        || children.length < 1 || children.length > 5 || !children.some(child => child?.package_slot === "A")
        || new Set((children as RewindingExportPackageChild[]).map(child => child.package_slot)).size !== children.length
        || new Set((children as RewindingExportPackageChild[]).map(child => child.bobbin_id)).size !== children.length) return null;
    return {
        id: value.id, package_number: value.package_number, mother_capture_id: value.mother_capture_id,
        mother_label_snapshot: value.mother_label_snapshot, mother,
        children: children as RewindingExportPackageChild[],
    };
}
export function parseRewindingExportDraftSummary(value: unknown): RewindingExportDraftSummary | null {
    if (!isRec(value) || !isUuid(value.id) || !isOffsetDateTime(value.created_at) || !isString(value.pv_reference)
        || !isString(value.article_code) || !(value.machine_code === null || isString(value.machine_code))
        || !isNonNegativeInteger(value.package_count)) return null;
    return {
        id: value.id, created_at: value.created_at, pv_reference: value.pv_reference,
        article_code: value.article_code, machine_code: value.machine_code, package_count: value.package_count,
    };
}
export function parseRewindingExportDraftSummaryList(value: unknown): RewindingExportDraftSummary[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingExportDraftSummary);
    return items.some(item => item === null) ? null : items as RewindingExportDraftSummary[];
}
export function parseRewindingExportDraft(value: unknown): RewindingExportDraft | null {
    if (!isRec(value) || !isUuid(value.id) || value.status !== "draft" || !isOffsetDateTime(value.created_at)
        || !isString(value.pv_reference) || !isText(value.truck_number) || !isText(value.order_number)
        || !isText(value.observations) || !Array.isArray(value.packages)) return null;
    const article = value.article;
    if (!isRec(article) || !isUuid(article.id) || !isString(article.code) || !isText(article.description)) return null;
    const packages = value.packages.map(parseRewindingExportPackage);
    if (packages.some(item => item === null)) return null;
    return {
        id: value.id, status: "draft", created_at: value.created_at, pv_reference: value.pv_reference,
        article: { id: article.id, code: article.code, description: article.description },
        truck_number: value.truck_number, order_number: value.order_number, observations: value.observations,
        packages: packages as RewindingExportPackage[],
    };
}
export function parseRewindingExportPreview(value: unknown): RewindingExportPreview | null {
    if (!isRec(value) || typeof value.valid !== "boolean" || !isNonNegativeInteger(value.package_count)
        || !isNonNegativeInteger(value.child_count) || !Array.isArray(value.warnings) || !Array.isArray(value.blocking_errors)) return null;
    const parseMessages = (items: unknown[]) => items.map(item => {
        if (!isRec(item) || !isString(item.code) || !isString(item.message)) return null;
        return { code: item.code, message: item.message };
    });
    const warnings = parseMessages(value.warnings), blocking = parseMessages(value.blocking_errors);
    if (warnings.some(item => item === null) || blocking.some(item => item === null)) return null;
    if (value.valid !== (blocking.length === 0)) return null;
    return {
        valid: value.valid, package_count: value.package_count, child_count: value.child_count,
        warnings: warnings as { code: string; message: string }[],
        blocking_errors: blocking as { code: string; message: string }[],
    };
}
export function parseRewindingWorkOrderOption(value: unknown): RewindingWorkOrderOption | null {
    if (!isRec(value) || !isUuid(value.id) || !isString(value.number)
        || (value.status !== "published" && value.status !== "in_progress" && value.status !== "closed")
        || !isString(value.machine_code)) return null;
    return { id: value.id, number: value.number, status: value.status, machine_code: value.machine_code };
}
export function parseRewindingWorkOrderOptionList(value: unknown): RewindingWorkOrderOption[] | null {
    if (!isRec(value) || !Array.isArray(value.items)) return null;
    const items = value.items.map(parseRewindingWorkOrderOption);
    return items.some(item => item === null) ? null : items as RewindingWorkOrderOption[];
}
export function parseRewindingWorkOrderClassification(value: unknown): RewindingWorkOrderClassificationRecord | null {
    if (!isRec(value) || !isUuid(value.work_order_id)) return null;
    if (value.classification === null) {
        if (value.sequence_no !== null || value.recorded_at !== null || value.reason !== null || value.recorded_by !== null) return null;
        return { work_order_id: value.work_order_id, classification: null, sequence_no: null, recorded_at: null, reason: null, recorded_by: null };
    }
    if (value.classification !== "production_confirmed" && value.classification !== "qa") return null;
    if (!isPositiveInteger(value.sequence_no) || !isOffsetDateTime(value.recorded_at) || !isString(value.reason)
        || !isRec(value.recorded_by) || !isUuid(value.recorded_by.id) || !isString(value.recorded_by.display_name)) return null;
    return {
        work_order_id: value.work_order_id, classification: value.classification,
        sequence_no: value.sequence_no, recorded_at: value.recorded_at, reason: value.reason,
        recorded_by: { id: value.recorded_by.id, display_name: value.recorded_by.display_name },
    };
}

export function formatRewindingExportFormat(mother: Pick<RewindingExportMother, "formato_1" | "formato_2">): string {
    return mother.formato_2 === null ? mother.formato_1 : mother.formato_1 + " + " + mother.formato_2;
}
export function formatRewindingExportCuts(mother: Pick<RewindingExportMother, "formato_3">): string {
    return mother.formato_3 ?? "—";
}
export function rewindingExportChildLabel(child: Pick<RewindingExportChild, "position" | "weight_kg">): string {
    return "Cría " + child.position + " - " + child.weight_kg + " kg";
}

export function rewindingExportContextDifferences(first: RewindingExportMother, next: RewindingExportMother): string[] {
    const differences: string[] = [];
    if (first.pv_reference !== next.pv_reference) differences.push("PV");
    if (first.article_id !== next.article_id) differences.push("producto");
    if (first.machine.code !== next.machine.code) differences.push("máquina");
    if (first.destination.trim() !== next.destination.trim()) differences.push("destino");
    if (first.formato_1 !== next.formato_1 || first.formato_2 !== next.formato_2) differences.push("Formato");
    if (first.formato_3 !== next.formato_3) differences.push("Cortes");
    return differences;
}

export type RewindingExportSelection = Partial<Record<RewindingExportSlot, string>>;
export function validateRewindingExportPackage(input: {
    mother: RewindingExportMother;
    availableChildren: readonly RewindingExportChild[];
    selection: RewindingExportSelection;
    existingPackages: readonly RewindingExportPackage[];
    editingPackageId?: string | null;
}): string[] {
    const errors: string[] = [];
    const selected = REWINDING_EXPORT_SLOTS.flatMap(slot => {
        const id = input.selection[slot];
        return id ? [{ slot, id }] : [];
    });
    if (!input.selection.A) errors.push("La Cría A es obligatoria.");
    if (selected.length < 1 || selected.length > 5) errors.push("Cada paquete debe contener entre una y cinco crías.");
    if (new Set(selected.map(item => item.id)).size !== selected.length) errors.push("No puedes repetir una cría dentro del mismo paquete.");
    const available = new Map(input.availableChildren.map(child => [child.bobbin_id, child]));
    for (const item of selected) {
        const child = available.get(item.id);
        if (!child) {
            errors.push("La Cría " + item.slot + " ya no está disponible. Actualiza la lista.");
            continue;
        }
        if (child.mother_capture_id !== input.mother.mother_capture_id) errors.push("La Cría " + item.slot + " no pertenece a la madre seleccionada.");
        if (child.quality_status !== "released") errors.push("La Cría " + item.slot + " no está liberada por Calidad.");
    }
    const usedElsewhere = new Set(input.existingPackages
        .filter(pkg => pkg.id !== (input.editingPackageId ?? null))
        .flatMap(pkg => pkg.children.map(child => child.bobbin_id)));
    if (selected.some(item => usedElsewhere.has(item.id))) errors.push("Una cría ya está seleccionada en otro paquete de este borrador.");
    return [...new Set(errors)];
}

export type RewindingExportPackagePayload = { mother_capture_id: string; children: { package_slot: RewindingExportSlot; child_bobbin_id: string }[] };

export function buildRewindingExportPackagePayload(input: {
    mother: RewindingExportMother;
    availableChildren: readonly RewindingExportChild[];
    selection: RewindingExportSelection;
}): RewindingExportPackagePayload {
    const byId = new Map(input.availableChildren.map(child => [child.bobbin_id, child]));
    const children = REWINDING_EXPORT_SLOTS.flatMap(slot => {
        const id = input.selection[slot];
        return id && byId.has(id) ? [{ package_slot: slot, child_bobbin_id: id }] : [];
    });
    return { mother_capture_id: input.mother.mother_capture_id, children };
}

export function buildRewindingExportDraftPayload(input: {
    pv_reference: string;
    article_id: string;
    truck_number: string;
    order_number: string;
    observations: string;
}) {
    return {
        pv_reference: input.pv_reference,
        article_id: input.article_id,
        truck_number: input.truck_number.trim(),
        order_number: input.order_number.trim(),
        observations: input.observations,
    };
}
