// MF-06 (MD_Ejec 22) · versión 2: se retiran «Número de bobina» y «Producto» (la bobina y su artículo ya vienen de la bobina seleccionada); la versión 1 y sus capturas se conservan y siguen siendo legibles (el parser
// ignora claves que ya no declara). Ya no se envía ni se valida `numero_de_bobina`: el backend solo lo contrasta si la versión publicada lo declara.
// VINTO-P1-24 «Propiedades físicas en húmedo» (Calidad): contrato técnico CANDIDATO, control ligado a UNA BOBINA física F3 de MP1 / MP3 (POST /api/quality/bobbins/{id}/captures). Los doce campos manuales son
// exactamente los de la definición legacy (form_24_propiedades_fisicas_en_humedo, 18 campos: 12 manuales, 4 automáticos y 2 calculados), con sus claves, etiquetas, orden, tipos y obligatoriedad: número de bobina
// y producto son texto; crepado, gramaje, las seis resistencias húmedas y el tiempo de curado / condición son decimales; `observaciones` es opcional. Unidades declaradas: g/m² (gramaje) y min (tiempo de curado).
// Fecha, hora, máquina y responsable son automáticos: el backend deriva máquina, turno y fecha operativa de la bobina (F3 de origen) y el responsable es el usuario autenticado.
//
// `numero_de_bobina` debe coincidir con la bobina seleccionada (se precarga y no se edita; el backend rechaza otro valor). `producto` es texto digitado: NO se contrasta con el artículo del maestro (no hay regla
// aprobada); el artículo real de la bobina se muestra solo como contexto informativo.
//
// NO se calculan `promedio_longitudinal_humedo` ni `promedio_transversal_humedo`: la definición los declara calculados (el segundo con tipo TEXTO en la definición legacy; no se corrige por suposición) y no hay
// fórmula aprobada. No se calculan, no se guardan y no se muestran; el backend rechaza cualquier campo calculado enviado.
//
// ALCANCE: la definición legacy menciona MP1, MP3 y TODAS LAS REBOBINADORAS. Este candidato solo cubre bobinas F3 de MP1 / MP3 (el único contexto de bobina física que existe); NO hay bobinas de rebobinadoras
// y no se fabrican: cubrirlas exige confirmar la identidad de la bobina, su origen, las máquinas y las relaciones. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_24_CODE = "VINTO-P1-24";
// MF-07 (MD_Ejec 26, que el Excel original asignó por error a «Resistencia en húmedo-curado») · versión 3: las posiciones de medición pasan de centro / medio / extremo a Comando / Medio / Transversal (la DIRECCIÓN —longitudinal
// o transversal— va en la etiqueta y es distinta de la POSICIÓN); las claves técnicas NO cambian y las capturas v1/v2 se muestran con sus etiquetas de entonces (`renamedAt`). Se añaden dos promedios CALCULADOS por el backend
// (media aritmética simple de las tres posiciones, dos decimales, solo lectura; sin recalcular capturas anteriores).
const POSITION_LABEL = { centro: "Comando", medio: "Medio", extremo: "Transversal" } as const;
const wet = (direction: "longitudinal" | "transversal", position: keyof typeof POSITION_LABEL): FieldSpec => ({
    key: `resistencia_${direction}_humeda_${position}`, label: `Resistencia ${direction} húmeda – ${POSITION_LABEL[position]}`, kind: "decimal", required: true,
    renamedAt: { version: 3, previous: `Resistencia ${direction} húmeda ${position}` },
});
export const P124_FIELDS: readonly FieldSpec[] = [
    { key: "crepado", label: "Crepado (%)", kind: "decimal", required: true, suffix: "%", renamedAt: { version: 4, previous: "Crepado" } }, // MF-11 (MD_Ejec 51): solo etiqueta y unidad visual; sin rango ni conversión de valores
    { key: "gramaje", label: "Gramaje", kind: "decimal", required: true, suffix: "g/m²" },
    wet("longitudinal", "centro"),
    wet("longitudinal", "medio"),
    wet("longitudinal", "extremo"),
    wet("transversal", "centro"),
    wet("transversal", "medio"),
    wet("transversal", "extremo"),
    { key: "tiempo_de_curado_condicion", label: "Tiempo de curado / condición", kind: "decimal", required: true, suffix: "min" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Calculados por el backend al guardar (solo lectura, desde la versión 3); las capturas anteriores no los traen.
export const P124_CALCULATED_FIELDS: readonly FieldSpec[] = [
    { key: "promedio_longitudinal_humedo", label: "Promedio resistencia longitudinal húmeda", kind: "decimal", required: false, sinceVersion: 3 },
    { key: "promedio_transversal_humedo", label: "Promedio resistencia transversal húmeda", kind: "decimal", required: false, sinceVersion: 3 },
];
export const P124_MEANS: Readonly<Record<string, readonly string[]>> = {
    promedio_longitudinal_humedo: ["resistencia_longitudinal_humeda_centro", "resistencia_longitudinal_humeda_medio", "resistencia_longitudinal_humeda_extremo"],
    promedio_transversal_humedo: ["resistencia_transversal_humeda_centro", "resistencia_transversal_humeda_medio", "resistencia_transversal_humeda_extremo"],
};
// Campos de la versión 1 retirados en la versión 2 (MF-06): solo lectura, para el historial de las capturas antiguas.
export const P124_LEGACY_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: false },
    { key: "producto", label: "Producto", kind: "text", required: false },
];
export const P124 = defineCandidateForm(P1_24_CODE, P124_FIELDS, { context: "bobbin", legacy: P124_LEGACY_FIELDS, calculated: P124_CALCULATED_FIELDS });
export const P124_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Hora (de registro, no del ensayo)", "Máquina (la de la bobina)", "Responsable (usuario autenticado, informativo)"] as const;
export const P124_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Promedios", pending: "Los promedios de resistencia longitudinal húmeda y transversal húmeda (media aritmética simple de Comando, Medio y Transversal, dos decimales) los calcula el sistema al guardar; no se digitan. Las capturas anteriores no se recalculan." },
    { label: "Alcance de máquinas", pending: "La definición legacy menciona MP1, MP3 y todas las rebobinadoras. Solo se cubren bobinas F3 de MP1 / MP3; las rebobinadoras NO están cubiertas y requieren confirmar identidad de bobina, origen, máquinas y relaciones." },
    { label: "Número de bobina y producto", pending: "Ya no se digitan (MF-06): la bobina y su artículo vienen de la bobina seleccionada y se muestran solo como contexto informativo; las capturas de la versión 1 los conservan." },
    { label: "Curado y unidades", pending: "El tiempo de curado / condición es un decimal en minutos según la definición; no hay regla de curado, rangos, límites ni unidades declaradas para crepado y resistencias." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del ensayo. Frecuencia de ensayo pendiente." },
    { label: "Efecto sobre la bobina", pending: "Registrar este control no libera, rechaza ni aprueba la bobina." },
];
