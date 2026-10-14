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
export const P124_BOBBIN_CODE_FIELD = "numero_de_bobina";
export const P124_FIELDS: readonly FieldSpec[] = [
    { key: P124_BOBBIN_CODE_FIELD, label: "Número de bobina", kind: "text", required: true },
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "crepado", label: "Crepado", kind: "decimal", required: true },
    { key: "gramaje", label: "Gramaje", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "resistencia_longitudinal_humeda_centro", label: "Resistencia longitudinal húmeda centro", kind: "decimal", required: true },
    { key: "resistencia_longitudinal_humeda_medio", label: "Resistencia longitudinal húmeda medio", kind: "decimal", required: true },
    { key: "resistencia_longitudinal_humeda_extremo", label: "Resistencia longitudinal húmeda extremo", kind: "decimal", required: true },
    { key: "resistencia_transversal_humeda_centro", label: "Resistencia transversal húmeda centro", kind: "decimal", required: true },
    { key: "resistencia_transversal_humeda_medio", label: "Resistencia transversal húmeda medio", kind: "decimal", required: true },
    { key: "resistencia_transversal_humeda_extremo", label: "Resistencia transversal húmeda extremo", kind: "decimal", required: true },
    { key: "tiempo_de_curado_condicion", label: "Tiempo de curado / condición", kind: "decimal", required: true, suffix: "min" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P124 = defineCandidateForm(P1_24_CODE, P124_FIELDS, { context: "bobbin" });
export const P124_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Hora (de registro, no del ensayo)", "Máquina (la de la bobina)", "Responsable (usuario autenticado, informativo)"] as const;
export const P124_CALCULATED = ["Promedio longitudinal húmedo", "Promedio transversal húmedo"] as const; // calculados en la definición, sin fórmula aprobada: no se calculan ni se muestran
export const P124_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Calculados", pending: "Los promedios longitudinal y transversal húmedos son calculados en la definición, sin fórmula aprobada (el transversal figura como texto en la definición legacy): no se calculan, no se guardan ni se muestran; el backend rechaza el envío de campos calculados." },
    { label: "Alcance de máquinas", pending: "La definición legacy menciona MP1, MP3 y todas las rebobinadoras. Solo se cubren bobinas F3 de MP1 / MP3; las rebobinadoras NO están cubiertas y requieren confirmar identidad de bobina, origen, máquinas y relaciones." },
    { label: "Número de bobina y producto", pending: "El número debe coincidir con la bobina seleccionada (se precarga y el backend rechaza otro valor). El producto es texto digitado: no se contrasta con el artículo de la bobina porque no hay una regla aprobada." },
    { label: "Curado y unidades", pending: "El tiempo de curado / condición es un decimal en minutos según la definición; no hay regla de curado, rangos, límites ni unidades declaradas para crepado y resistencias." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del ensayo. Frecuencia de ensayo pendiente." },
    { label: "Efecto sobre la bobina", pending: "Registrar este control no libera, rechaza ni aprueba la bobina." },
];
