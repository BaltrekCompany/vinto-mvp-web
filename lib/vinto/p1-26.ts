// VINTO-P1-26 «Medición de secos» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control POR MÁQUINA (sin bobina, asignación ni OT). Los cuatro campos manuales son exactamente los de la definición legacy
// (form_26_medicion_de_secos, 9 campos: 4 manuales, 4 automáticos y 1 calculado): `punto_de_muestreo` es texto, masa húmeda y masa seca son decimales y `observaciones` es opcional. Fecha, hora, máquina y
// responsable son automáticos (el backend los resuelve al registrar).
//
// NO se calcula `porcentaje_de_secos`: es un campo calculado de la definición y no hay regla industrial confirmada (ni siquiera cuál es la base del porcentaje). No se calcula, no se guarda y no se muestra; el
// backend rechaza cualquier campo calculado enviado.
//
// PENDIENTE DE VINTO (no se inventa): fórmula de porcentaje de secos, rangos y unidades de las masas, catálogo de puntos de muestreo, la HORA DEL ENSAYO (`hora` es la de registro del servidor) y el alcance
// de máquinas: la definición legacy declara `allowedMachineIds: por_definir` aunque su etiqueta dice «MP1 / MP3». Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_26_CODE = "VINTO-P1-26";
export const P126_FIELDS: readonly FieldSpec[] = [
    { key: "punto_de_muestreo", label: "Punto de muestreo", kind: "text", required: true },
    { key: "masa_humeda", label: "Masa húmeda", kind: "decimal", required: true },
    { key: "masa_seca", label: "Masa seca", kind: "decimal", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P126 = defineCandidateForm(P1_26_CODE, P126_FIELDS, { context: "machine" });
export const P126_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Hora (de registro, no del ensayo)", "Máquina", "Responsable (usuario autenticado, informativo)"] as const;
export const P126_CALCULATED = ["Porcentaje de secos"] as const; // calculado en la definición, sin fórmula aprobada: no se calcula ni se muestra
export const P126_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Porcentaje de secos", pending: "Calculado en la definición, sin fórmula aprobada: no se calcula, no se guarda ni se muestra; el backend rechaza el envío de campos calculados." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del muestreo." },
    { label: "Máquinas y muestreo", pending: "La definición legacy dice «MP1 / MP3» pero su alcance de máquinas es «por definir»; el punto de muestreo es texto libre sin catálogo." },
    { label: "Masas", pending: "Decimales sin unidad, rango ni relación aprobada entre masa húmeda y masa seca." },
];
