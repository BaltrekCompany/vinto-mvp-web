// Inbox CENTRAL de Calidad (solo lectura): tipos de GET /api/quality/bobbins y parser defensivo. PURO (sin red, sin DOM, sin imports en
// tiempo de ejecución) para probarlo con Node. El backend es la autoridad: aquí no se calcula nada ni se escribe nada (sin liberar,
// rechazar ni capturas de Calidad). Los decimales viajan como TEXTO y se conservan tal cual ("0.10" sigue siendo "0.10").

export const QUALITY_STATUSES = ["pending", "released", "rejected"] as const;
export type QualityInboxStatus = (typeof QUALITY_STATUSES)[number];

export type QualityBobbinInboxItem = {
    bobbin: {
        id: string;
        code: string;
        machine: { code: string; name: string };
        management_start_year: number;
        sequence_number: number;
        start_time: string;
        end_time: string;
        diameter_mm: string;
        weight_kg: string;
        grammage_g_m2: string | null; // null: el producto no tiene gramaje en el maestro (no es un error)
        number_of_cuts: string;
        notes: string | null;
    };
    production: {
        capture_id: string;
        captured_at: string;
        operating_date: string;
        shift: { code: string; name: string };
        work_order: { id: string; number: string };
        line: { id: string; line_code: string; pv_reference: string; article: { code: string; description: string } };
    };
    quality: { status: QualityInboxStatus };
};

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isInt = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value);
const DECIMAL = /^-?\d+(\.\d+)?$/;
const NEGATIVE = (decimal: string) => decimal.startsWith("-") && !/^-0+(\.0+)?$/.test(decimal); // sin float; -0 no es negativo

const pair = (value: unknown): { code: string; name: string } | null =>
    isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;

// Solo texto decimal (el backend serializa así); un número JSON no se acepta para no perder la forma exacta.
const decimal = (value: unknown): string | null => (typeof value === "string" && DECIMAL.test(value) ? value : null);

// Construye un objeto LIMPIO (los campos desconocidos no se propagan). null = respuesta inválida.
export function parseQualityBobbinInboxItem(value: unknown): QualityBobbinInboxItem | null {
    if (!isRec(value) || !isRec(value.bobbin) || !isRec(value.production) || !isRec(value.quality)) return null;
    const b = value.bobbin, p = value.production, q = value.quality;

    const machine = pair(b.machine);
    const diameter = decimal(b.diameter_mm), weight = decimal(b.weight_kg);
    const grammage = b.grammage_g_m2 === null ? null : decimal(b.grammage_g_m2);
    if (!isStr(b.id) || !isStr(b.code) || !machine) return null;
    if (!isInt(b.management_start_year) || b.management_start_year <= 0 || !isInt(b.sequence_number) || b.sequence_number <= 0) return null;
    if (b.code !== String(b.sequence_number)) return null; // contrato F3 / CHECK de 0004: code = sequence_number::text
    if (!isStr(b.start_time) || !isStr(b.end_time) || !isStr(b.number_of_cuts)) return null;
    if (diameter === null || weight === null || NEGATIVE(weight)) return null; // diámetro: decimal válido, sin rango funcional
    if (b.grammage_g_m2 !== null && grammage === null) return null;
    if (!(b.notes === null || typeof b.notes === "string")) return null;

    const shift = pair(p.shift), order = p.work_order, line = p.line;
    if (!isStr(p.capture_id) || !isStr(p.captured_at) || !isStr(p.operating_date) || !shift) return null;
    if (!isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference)) return null;
    if (!isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;

    const status = (QUALITY_STATUSES as readonly unknown[]).includes(q.status) ? (q.status as QualityInboxStatus) : null;
    if (status === null) return null;

    return {
        bobbin: {
            id: b.id, code: b.code, machine, management_start_year: b.management_start_year, sequence_number: b.sequence_number,
            start_time: b.start_time, end_time: b.end_time, diameter_mm: diameter, weight_kg: weight, grammage_g_m2: grammage,
            number_of_cuts: b.number_of_cuts, notes: b.notes,
        },
        production: {
            capture_id: p.capture_id, captured_at: p.captured_at, operating_date: p.operating_date, shift,
            work_order: { id: order.id, number: order.number },
            line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        },
        quality: { status },
    };
}

// Si UN item es inválido se rechaza la respuesta completa: nunca se oculta en silencio una bobina del inbox.
export function parseQualityBobbinInbox(value: unknown): QualityBobbinInboxItem[] | null {
    if (!Array.isArray(value)) return null;
    const items: QualityBobbinInboxItem[] = [];
    for (const raw of value) {
        const item = parseQualityBobbinInboxItem(raw);
        if (item === null) return null;
        items.push(item);
    }
    return items;
}

// Presentación: el gramaje ausente no es un error.
export const NO_GRAMMAGE_LABEL = "Sin gramaje en maestro";
export const grammageLabel = (grammage: string | null): string => (grammage === null ? NO_GRAMMAGE_LABEL : `${grammage} g/m²`);
export const qualityStatusLabel = (status: QualityInboxStatus): string => (status === "pending" ? "Pendiente" : status === "released" ? "Liberada" : "Rechazada");
