import { requestJson } from "./central-http.ts";
import { isRec, isStr } from "./capture-core.ts";

export type PalletPreview = {
    work_order: string;
    line_code: string;
    pv_reference: string;
    machine: string;
    article_code: string;
    article_description: string;
    nominal_weight_kg: string | null;
    weight_available: boolean;
    unit: string | null;
};

export function parsePalletPreview(raw: unknown): PalletPreview | null {
    if (!isRec(raw) || !isStr(raw.work_order) || !isStr(raw.line_code) ||
        !isStr(raw.pv_reference) || !isStr(raw.machine) || !isStr(raw.article_code) ||
        typeof raw.article_description !== "string" || typeof raw.weight_available !== "boolean") return null;
    if (raw.weight_available && (typeof raw.nominal_weight_kg !== "string" ||
        !/^\d+(?:\.\d+)?$/.test(raw.nominal_weight_kg) || Number(raw.nominal_weight_kg) <= 0)) return null;
    if (!raw.weight_available && raw.nominal_weight_kg !== null) return null;
    if (raw.unit !== null && typeof raw.unit !== "string") return null;
    return {
        work_order: raw.work_order, line_code: raw.line_code, pv_reference: raw.pv_reference,
        machine: raw.machine, article_code: raw.article_code,
        article_description: raw.article_description,
        nominal_weight_kg: raw.nominal_weight_kg as string | null,
        weight_available: raw.weight_available, unit: raw.unit as string | null
    };
}

export function previewTotalKg(weight: string | null, jabas: string): string | null {
    if (weight === null || !/^\d+(?:\.\d{1,6})?$/.test(weight) || !/^\d{1,9}$/.test(jabas)) return null;
    const count = BigInt(jabas);
    if (count < 1n) return null;
    // Exacto hasta seis decimales; evita redondear el Peso del Excel antes de guardar.
    const [whole, decimals = ""] = weight.split(".");
    const microKg = BigInt(whole) * 1_000_000n + BigInt(decimals.padEnd(6, "0"));
    if (microKg <= 0n) return null;
    const totalMicro = microKg * count;
    const totalWhole = totalMicro / 1_000_000n;
    const tail = String(totalMicro % 1_000_000n).padStart(6, "0").replace(/0+$/, "");
    return `${totalWhole}.${tail.padEnd(2, "0")}`;
}

export const getPalletPreview = (assignmentId: string, signal?: AbortSignal) =>
    requestJson(`/api/production/pallet-preview?assignment_id=${encodeURIComponent(assignmentId)}`, { signal }, parsePalletPreview);
