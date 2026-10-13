// Vista previa de VINTO-P1-10 «Registro de fardos» (Rebobinado), M2-B1. SOLO PRESENTACIÓN: este módulo no envía nada, no usa red, no guarda nada y no
// decide ninguna regla de negocio. La estructura sale de la definición existente (lib/vinto/form-definitions.ts); las reglas aún sin confirmar
// (docs/M2-B-P1-10-contrato.md) se listan como PENDIENTES, nunca como resueltas. Los datos de demostración son ficticios y se identifican como tales.
// P1-10 NO está en el bundle de producción ni en la política de captura central del backend, y Rebobinado sigue sin ser operativo.

import { FORM_DEFINITIONS } from "./form-definitions.ts";
import { CONTEXT_NOTES, P1_10_CODE } from "./p1-10.ts";
import type { FieldDefinition, FormDefinition } from "./types.ts";

export { P1_10_CODE };

export function p110Definition(): FormDefinition {
    const definition = FORM_DEFINITIONS.find((form) => form.code === P1_10_CODE);
    if (!definition) throw new Error(`Falta la definición ${P1_10_CODE}`);
    return definition;
}

export type PreviewField = { key: string; label: string; description: string; declaredType: FieldDefinition["type"]; required: boolean; unit: string | null };
export type ContextualField = PreviewField & { origin: string; pending: string };

const toField = (field: FieldDefinition): PreviewField => ({
    key: field.key, label: field.label, description: field.description, declaredType: field.type, required: field.required, unit: field.unit ?? null,
});

export function previewSpec() {
    const definition = p110Definition();
    const manual = definition.fields.filter((field) => field.source === "manual").sort((a, b) => a.order - b.order).map(toField);
    const contextual: ContextualField[] = definition.fields.filter((field) => field.source !== "manual").sort((a, b) => a.order - b.order).map((field) => ({
        ...toField(field),
        origin: CONTEXT_NOTES[field.key]?.origin ?? "Origen por definir.",
        pending: CONTEXT_NOTES[field.key]?.pending ?? "Por confirmar.",
    }));
    return { code: definition.code, name: definition.name, machineLabel: definition.machineLabel, allowedMachineIds: [...definition.allowedMachineIds], manual, contextual };
}

// Reglas de negocio SIN confirmar (docs/M2-B-P1-10-contrato.md, secciones C a E). La vista previa las muestra tal cual; no implementa ninguna.
export const PENDING_RULES: readonly { id: string; title: string; detail: string }[] = [
    { id: "correlativo", title: "Correlativo de fardo", detail: "No hay numerador ni formato confirmados. Esta vista no genera ni valida el número de fardo (ni formato ni unicidad)." },
    { id: "peso", title: "Peso del fardo", detail: "La definición lo declara como texto. Tipo, decimales, rango, unidad (kg) y bruto/neto están por confirmar." },
    { id: "producto", title: "Código / número de producto", detail: "Por confirmar si debe coincidir con el producto de la línea asignada, salir de un catálogo o ser libre." },
    { id: "maquinas", title: "Máquinas permitidas", detail: "«Todas las rebobinadoras» frente a COPASA: sin decisión. No se asume ninguna otra máquina." },
    { id: "responsable", title: "Responsable", detail: "No se asume que sea el operador que captura." },
    { id: "firma", title: "Firma / aprobación", detail: "Sin definición. No se simula ninguna firma digital." },
    { id: "habilitacion", title: "Habilitación", detail: "Rebobinado no es un sector operativo y P1-10 no está habilitado para captura central: esta vista no puede registrar nada." },
];

// Datos de DEMOSTRACIÓN, ficticios y no persistentes: solo para ver el formulario. Nunca se envían.
export const DEMO_DISCLAIMER = "DATOS FICTICIOS DE DEMOSTRACIÓN";
export const DEMO_DRAFT = {
    codigo_numero_de_producto: "EJEMPLO-PRODUCTO",
    numero_de_fardo: "EJEMPLO-000",
    peso_fardo: "0,0 (ejemplo)",
    observaciones: "Texto de ejemplo; esta vista previa no registra capturas.",
} as const;
export const DEMO_CONTEXT: Readonly<Record<string, string>> = {
    fecha: "AAAA-MM-DD (ejemplo)",
    maquina: "Rebobinadora (ejemplo)",
    responsable: "Persona ficticia (ejemplo)",
    firma: "— sin firma: pendiente de definición —",
};
