// MF-06 (MD_Ejec 27, 28 y 29) · versión 2: se retiran «Número de bobina», «Producto» y «Gramaje laboratorio g/m²»; «Caudal RH [ml/min]» se añade al inicio (decimal, OPCIONAL) y «# Cortes» antes de «Observaciones»
// (entero no negativo, OBLIGATORIO solo desde la versión 2: las capturas de la versión 1 no lo tienen y se leen sin exigirlo; `sinceVersion`). La versión 1 y sus capturas se conservan.
// VINTO-P1-25 «Resistencia en húmedo-curado» (Calidad): contrato técnico CANDIDATO, control ligado a UNA BOBINA física F3 de MP1 / MP3 (POST /api/quality/bobbins/{id}/captures). Los catorce campos manuales son
// exactamente los de la definición legacy (form_25_resistencia_en_humedo_curado, 20 campos: 14 manuales, 3 automáticos y 3 calculados), con sus claves, etiquetas, orden, tipos y obligatoriedad: número de bobina,
// producto y `curado_min` son TEXTO (curado_min NO se convierte a decimal por su nombre); gramaje de laboratorio, crepado, las seis resistencias y las dos elongaciones son decimales; `observaciones` es opcional.
// Las unidades (g/m², kgf) ya figuran en las etiquetas. Fecha, hora y responsable son automáticos: el backend deriva turno y fecha operativa de la bobina (F3 de origen) y el responsable es el usuario autenticado.
//
// `numero_de_bobina` debe coincidir con la bobina seleccionada (se precarga y no se edita; el backend rechaza otro valor). `producto` es texto digitado: NO se contrasta con el artículo del maestro.
//
// NO se calculan `promedio_resistencia_longitudinal_kgf`, `promedio_resistencia_longitudinal_humeda_kgf` ni `porcentaje_de_resistencia_humeda`: no hay fórmula aprobada. No se calculan, no se guardan y no se
// muestran; el backend rechaza cualquier campo calculado enviado.
//
// ALCANCE PENDIENTE: la definición legacy dice «MP1 / MP3» pero su alcance de máquinas es `por_definir`. MP1 / MP3 se usan SOLO en las fixtures técnicas de prueba; la decisión de VINTO sigue pendiente. No hay
// bobinas de rebobinadoras. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_25_CODE = "VINTO-P1-25";
// MF-07 (MD_Ejec 25) · versión 3: las posiciones pasan de centro / medio / extremo a Comando / Medio / Transversal (la DIRECCIÓN, longitudinal, va aparte de la POSICIÓN); las claves técnicas NO cambian y las capturas v1/v2
// se muestran con sus etiquetas de entonces (`renamedAt`). Se añaden dos promedios CALCULADOS por el backend (media aritmética simple de las tres posiciones, dos decimales, solo lectura): resistencia longitudinal (seca) y
// resistencia longitudinal húmeda. Las elongaciones ya existentes se conservan; Caudal RH y # Cortes (MF-06) no cambian.
const POSITION_LABEL = { centro: "Comando", medio: "Medio", extremo: "Transversal" } as const;
const longitudinal = (wetKind: "" | "humeda_", position: keyof typeof POSITION_LABEL): FieldSpec => ({
    key: `resistencia_longitudinal_${wetKind}${position}_kgf`, label: `Resistencia longitudinal ${wetKind ? "húmeda " : ""}– ${POSITION_LABEL[position]} kgf`, kind: "decimal", required: true,
    renamedAt: { version: 3, previous: `Resistencia longitudinal ${wetKind ? "húmeda " : ""}${position} kgf` },
});
export const P125_FIELDS: readonly FieldSpec[] = [
    { key: "caudal_rh_ml_min", label: "Caudal RH [ml/min]", kind: "decimal", required: false },
    { key: "crepado", label: "Crepado", kind: "decimal", required: true },
    { key: "curado_min", label: "Curado min", kind: "text", required: true },
    longitudinal("", "centro"),
    longitudinal("", "medio"),
    longitudinal("", "extremo"),
    { key: "elongacion_media_longitudinal", label: "Elongación media longitudinal", kind: "decimal", required: true },
    longitudinal("humeda_", "centro"),
    longitudinal("humeda_", "medio"),
    longitudinal("humeda_", "extremo"),
    { key: "elongacion_media_transversal", label: "Elongación media transversal", kind: "decimal", required: true },
    { key: "n_cortes", label: "# Cortes", kind: "integer", required: true, sinceVersion: 2 },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Calculados por el backend al guardar (solo lectura, desde la versión 3); las capturas anteriores no los traen.
export const P125_CALCULATED_FIELDS: readonly FieldSpec[] = [
    { key: "promedio_resistencia_longitudinal_kgf", label: "Promedio resistencia longitudinal kgf", kind: "decimal", required: false, sinceVersion: 3 },
    { key: "promedio_resistencia_longitudinal_humeda_kgf", label: "Promedio resistencia longitudinal húmeda kgf", kind: "decimal", required: false, sinceVersion: 3 },
];
export const P125_MEANS: Readonly<Record<string, readonly string[]>> = {
    promedio_resistencia_longitudinal_kgf: ["resistencia_longitudinal_centro_kgf", "resistencia_longitudinal_medio_kgf", "resistencia_longitudinal_extremo_kgf"],
    promedio_resistencia_longitudinal_humeda_kgf: ["resistencia_longitudinal_humeda_centro_kgf", "resistencia_longitudinal_humeda_medio_kgf", "resistencia_longitudinal_humeda_extremo_kgf"],
};
// Campos de la versión 1 retirados en la versión 2 (MF-06): solo lectura, para el historial de las capturas antiguas.
export const P125_LEGACY_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: false },
    { key: "producto", label: "Producto", kind: "text", required: false },
    { key: "gramaje_laboratorio_g_m2", label: "Gramaje laboratorio g/m²", kind: "decimal", required: false },
];
export const P125 = defineCandidateForm(P1_25_CODE, P125_FIELDS, { context: "bobbin", legacy: P125_LEGACY_FIELDS, calculated: P125_CALCULATED_FIELDS });
export const P125_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Hora (de registro, no del ensayo)", "Responsable (usuario autenticado, informativo)"] as const;
export const P125_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Promedios", pending: "Los promedios de resistencia longitudinal y de resistencia longitudinal húmeda (media aritmética simple de Comando, Medio y Transversal, dos decimales) los calcula el sistema al guardar; no se digitan. El porcentaje de resistencia húmeda no se calcula (no fue aprobado). Las capturas anteriores no se recalculan." },
    { label: "Alcance de máquinas", pending: "La definición legacy dice «MP1 / MP3» pero su alcance de máquinas es «por definir». MP1 / MP3 se usan solo como contexto técnico de prueba; la decisión de VINTO sigue pendiente y las rebobinadoras NO están cubiertas." },
    { label: "Curado", pending: "«Curado min» es TEXTO en la definición legacy: se guarda tal como se digita, sin convertirlo a número ni aplicar una regla de curado." },
    { label: "Número de bobina y producto", pending: "Ya no se digitan (MF-06): la bobina y su artículo vienen de la bobina seleccionada y se muestran solo como contexto informativo; las capturas de la versión 1 los conservan." },
    { label: "Rangos y límites", pending: "Resistencias, elongaciones, gramaje y crepado son decimales sin rango ni límite de aceptación aprobados; las elongaciones no declaran unidad." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del ensayo. Frecuencia de ensayo pendiente." },
    { label: "Efecto sobre la bobina", pending: "Registrar este control no libera, rechaza ni aprueba la bobina." },
];
