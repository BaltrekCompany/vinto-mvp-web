/** RG-MP3-01: nuevo formulario exclusivo de MP3; no altera P1-01 (MP1). */
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";
import { MP3_INSPECTION_FIELDS, MP3_INSPECTION_FORM_CODE, MP3_INSPECTION_SECTIONS } from "./mp3-operation-spec.ts";

export const MP3_OPERATION_FIELDS: readonly FieldSpec[] = MP3_INSPECTION_FIELDS.map(f => ({
    key: f.key, label: f.label, kind: f.kind, required: f.required,
    ...(f.unit ? { suffix: f.unit } : {}),
}));
export const MP3_OPERATION_SECTIONS = MP3_INSPECTION_SECTIONS.map(s => ({
    title: s.title,
    hint: s.title === "Pulper" ? "Completa las siete lecturas obligatorias." :
        "Lecturas opcionales. Las casillas repetidas guardan cada valor por separado.",
    keys: s.fields.map(f => f.key),
}));
/** Se conserva la etiqueta impresa; la posición diferencia casillas iguales. */
export const MP3_OPERATION_HINTS: Readonly<Record<string, string>> = Object.fromEntries(
    MP3_INSPECTION_FIELDS.filter(f => f.slot !== undefined).map(f => [
        f.key, `Casilla ${f.slot} · lectura independiente dentro de ${f.label}`
    ]),
);
export const MP3_OPERATION = defineCandidateForm(MP3_INSPECTION_FORM_CODE, MP3_OPERATION_FIELDS);
export const MP3_OPERATION_AUTOMATIC = [
    "Operador (usuario autenticado)",
    "Fecha operativa y turno de la asignación",
    "Máquina MP3, OT, línea y producto de la asignación",
    "Hora de registro del servidor",
] as const;
export const MP3_OPERATION_PENDING = [
    { label: "Registro por turno", pending: "Solo una captura por máquina MP3, fecha operativa y turno; el servidor rechaza duplicados." },
] as const;
