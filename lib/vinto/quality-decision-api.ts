import { requestJson, type ApiResult } from "@/lib/vinto/central-http";

export const REJECTION_TYPES = [
    { value: "rechazado", label: "Rechazado" },
    { value: "reutilizable", label: "Reutilizable" },
] as const;

export const REJECTION_CLASSES = [
    { value: "dimensiones", label: "Dimensiones" },
    { value: "formato", label: "Formato" },
    { value: "defecto_visible", label: "Defecto visible" },
    { value: "humedad", label: "Humedad" },
    { value: "propiedades_bobina", label: "Propiedades de la bobina" },
    { value: "otros", label: "Otros" },
] as const;

export type QualityDecision = {
    decision_id: string;
    action: "release" | "reject";
    rejection_type?: string;
    classification?: string;
    detail?: string;
    corrective_action?: string;
};

export type QualityDecisionResult = { bobbin_id: string; status: "released" | "rejected"; already_decided: boolean };

export function parseQualityDecisionResult(value: unknown): QualityDecisionResult | null {
    if (typeof value !== "object" || !value) return null;
    const v = value as Record<string, unknown>;
    if (typeof v.bobbin_id !== "string" || !["released", "rejected"].includes(String(v.status)) || typeof v.already_decided !== "boolean") return null;
    return { bobbin_id: v.bobbin_id, status: v.status as "released" | "rejected", already_decided: v.already_decided };
}

export function submitQualityDecision(bobbinId: string, body: QualityDecision): Promise<ApiResult<QualityDecisionResult>> {
    return requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbinId)}/decision`,
        { method: "POST", body }, parseQualityDecisionResult);
}
