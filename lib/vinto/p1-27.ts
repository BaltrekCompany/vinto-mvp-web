// VINTO-P1-27 «Análisis de agua para caldero» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control POR MÁQUINA (sin bobina, asignación ni OT; POST /api/quality/machines/{máquina}/captures). Los 23 campos
// manuales son EXACTAMENTE los de la definición legacy (form_27_analisis_de_agua_para_caldero, 27 campos: 23 manuales, 3 automáticos y 1 calculado), con sus claves, etiquetas, orden, tipos y obligatoriedad,
// generados desde esa definición. pH y dureza son decimales; sólidos disueltos, conductividad, cloruros y la calibración del equipo son TEXTO aunque parezcan magnitudes (no se convierten a decimal);
// `observaciones` es opcional. La definición no declara unidades: no se muestra ninguna.
//
// Fecha, turno y responsable son automáticos: el backend resuelve la máquina (de la ruta), la fecha operativa y el turno al REGISTRAR y el responsable es el usuario autenticado (solo informativo).
// NO se calcula `purga_caldero_alcalinidad_total`: es un campo calculado y no hay fórmula aprobada; no se calcula, no se guarda, no se muestra y el backend rechaza cualquier campo calculado enviado.
//
// UN SOLO CONTRATO COMPLETO: el formulario contiene las mediciones de condensado de MP1 Y de MP3. Ningún campo se elimina ni se oculta según la máquina elegida y no se divide el formulario: la captura se asocia
// a la máquina seleccionada con los 23 campos. Las secciones de la pantalla son solo visuales.
//
// PENDIENTE DE VINTO (no se inventa): identidad del caldero, asociación de las muestras, frecuencia de registro, rangos y límites, unidades, la fórmula de la alcalinidad total, cuáles campos de condensado debe
// llenar cada máquina y la HORA de toma de muestras (`captured_at` es la hora de registro). Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_27_CODE = "VINTO-P1-27";
export const P127_FIELDS: readonly FieldSpec[] = [
    { key: "ablandador_ph", label: "Ablandador pH", kind: "decimal", required: true },
    { key: "ablandador_dureza", label: "Ablandador dureza", kind: "decimal", required: true },
    { key: "ablandador_solidos_disueltos", label: "Ablandador sólidos disueltos", kind: "text", required: true },
    { key: "ablandador_conductividad", label: "Ablandador conductividad", kind: "text", required: true },
    { key: "agua_alimentacion_caldero_ph", label: "Agua alimentación caldero pH", kind: "decimal", required: true },
    { key: "agua_alimentacion_caldero_dureza", label: "Agua alimentación caldero dureza", kind: "decimal", required: true },
    { key: "agua_alimentacion_caldero_solidos_disueltos", label: "Agua alimentación caldero sólidos disueltos", kind: "text", required: true },
    { key: "agua_alimentacion_caldero_conductividad", label: "Agua alimentación caldero conductividad", kind: "text", required: true },
    { key: "purga_caldero_ph", label: "Purga caldero pH", kind: "decimal", required: true },
    { key: "purga_caldero_dureza", label: "Purga caldero dureza", kind: "decimal", required: true },
    { key: "purga_caldero_solidos_disueltos", label: "Purga caldero sólidos disueltos", kind: "text", required: true },
    { key: "purga_caldero_conductividad", label: "Purga caldero conductividad", kind: "text", required: true },
    { key: "purga_caldero_cloruros", label: "Purga caldero cloruros", kind: "text", required: true },
    { key: "condensado_mp1_ph", label: "Condensado MP1 pH", kind: "decimal", required: true },
    { key: "condensado_mp1_dureza", label: "Condensado MP1 dureza", kind: "decimal", required: true },
    { key: "condensado_mp1_solidos_disueltos", label: "Condensado MP1 sólidos disueltos", kind: "text", required: true },
    { key: "condensado_mp1_conductividad", label: "Condensado MP1 conductividad", kind: "text", required: true },
    { key: "condensado_mp3_ph", label: "Condensado MP3 pH", kind: "decimal", required: true },
    { key: "condensado_mp3_dureza", label: "Condensado MP3 dureza", kind: "decimal", required: true },
    { key: "condensado_mp3_solidos_disueltos", label: "Condensado MP3 sólidos disueltos", kind: "text", required: true },
    { key: "condensado_mp3_conductividad", label: "Condensado MP3 conductividad", kind: "text", required: true },
    { key: "calibracion_equipo_multiparametro", label: "Calibración equipo multiparámetro", kind: "text", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Agrupación SOLO VISUAL (no representa grupos industriales aprobados): cada campo manual aparece exactamente una vez, en el orden del contrato.
export const P127_SECTIONS: readonly { title: string; hint?: string; keys: readonly string[] }[] = [
    { title: "Ablandador", keys: ["ablandador_ph", "ablandador_dureza", "ablandador_solidos_disueltos", "ablandador_conductividad"] },
    { title: "Agua de alimentación", keys: ["agua_alimentacion_caldero_ph", "agua_alimentacion_caldero_dureza", "agua_alimentacion_caldero_solidos_disueltos", "agua_alimentacion_caldero_conductividad"] },
    { title: "Purga de caldero", keys: ["purga_caldero_ph", "purga_caldero_dureza", "purga_caldero_solidos_disueltos", "purga_caldero_conductividad", "purga_caldero_cloruros"] },
    { title: "Condensado MP1", keys: ["condensado_mp1_ph", "condensado_mp1_dureza", "condensado_mp1_solidos_disueltos", "condensado_mp1_conductividad"] },
    { title: "Condensado MP3", keys: ["condensado_mp3_ph", "condensado_mp3_dureza", "condensado_mp3_solidos_disueltos", "condensado_mp3_conductividad"] },
    { title: "Calibración y observaciones", keys: ["calibracion_equipo_multiparametro", "observaciones"] },
];
export const P127 = defineCandidateForm(P1_27_CODE, P127_FIELDS, { context: "machine" });
export const P127_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Turno (el que resuelve el backend)", "Responsable (usuario autenticado, informativo)"] as const;
export const P127_CALCULATED = ["Purga caldero alcalinidad total"] as const; // calculado en la definición, sin fórmula aprobada: no se calcula ni se muestra
export const P127_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Alcalinidad total", pending: "Calculada en la definición, sin fórmula aprobada: no se calcula, no se guarda ni se muestra; el backend rechaza el envío de campos calculados." },
    { label: "Contrato completo en cada captura", pending: "El formulario incluye condensado de MP1 y de MP3: se conservan los 23 campos aunque elijas una máquina; no se ocultan ni se dividen. A qué máquina corresponde cada muestra queda pendiente de VINTO." },
    { label: "Caldero y muestras", pending: "Identidad del caldero, asociación de las muestras y frecuencia de registro pendientes de VINTO." },
    { label: "Tipos y unidades", pending: "Sólidos disueltos, conductividad, cloruros y calibración son TEXTO en la definición legacy y se guardan como se digitan; pH y dureza son decimales sin unidad, rango ni límite aprobados." },
    { label: "Hora de toma de muestras", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real de la toma de muestras." },
];
