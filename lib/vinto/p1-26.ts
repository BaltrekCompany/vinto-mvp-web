// VINTO-P1-26 «Medición de secos» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control POR MÁQUINA (sin bobina, asignación ni OT). Los cuatro campos manuales son exactamente los de la definición legacy
// (form_26_medicion_de_secos, 9 campos: 4 manuales, 4 automáticos y 1 calculado): `punto_de_muestreo` es texto, masa húmeda y masa seca son decimales y `observaciones` es opcional. Fecha, hora, máquina y
// responsable son automáticos (el backend los resuelve al registrar).
//
// NO se calcula `porcentaje_de_secos`: es un campo calculado de la definición y no hay regla industrial confirmada (ni siquiera cuál es la base del porcentaje). No se calcula, no se guarda y no se muestra; el
// backend rechaza cualquier campo calculado enviado.
//
// PENDIENTE DE VINTO (no se inventa): fórmula de porcentaje de secos, rangos y unidades de las masas, catálogo de puntos de muestreo, la HORA DEL ENSAYO (`hora` es la de registro del servidor) y el alcance
// de máquinas: la definición legacy declara `allowedMachineIds: por_definir` aunque su etiqueta dice «MP1 / MP3». Habilitado solo en entornos de prueba.
// MF-08 · versión 2 (MD_Ejec 32 y 40): «Punto de muestreo» pasa a lista desplegable OBLIGATORIA con seis opciones cerradas (texto exacto = valor guardado; sin texto libre en capturas nuevas) y se añade «% Cantidad de seco»,
// CALCULADO por el backend: masa seca / masa húmeda × 100, dos decimales, solo lectura. Las dos masas son los campos `masa_seca` y `masa_humeda` de este mismo formulario (decimales, sin unidad declarada en ninguno).
// Con masa húmeda 0 no hay resultado: el campo no se guarda ni se muestra (nunca se inventa un valor). La versión 1 (punto de muestreo en texto libre) y sus capturas se conservan y no se recalculan. «Absorción de
// humedad» (MD_Ejec 33) NO se incluye en la v2.
// MF-11 · versión 3 (MD_Ejec 33): se añade «Absorción de humedad» (decimal DIGITADO, opcional, unidad visible %). No se calcula, no tiene rango ni límite y no altera «% Cantidad de seco». Las capturas v1 y v2 no lo traen
// y se leen sin él (nunca se les inventa un valor). La unidad % es solo visual (no está en el catálogo de unidades del seed).
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";
import { percentTwoDecimals } from "./quality-averages.ts";

export const P1_26_CODE = "VINTO-P1-26";
export const P126_SAMPLING_POINTS: readonly string[] = ["Caja de formación – Colador", "Tela – Pick up", "Fieltro I", "Fieltro II", "Prensa succión", "Prensa ciega"];
export const P126_FIELDS: readonly FieldSpec[] = [
    { key: "punto_de_muestreo", label: "Punto de muestreo", kind: "select", required: true, options: P126_SAMPLING_POINTS, optionsSinceVersion: 2 },
    { key: "masa_humeda", label: "Masa húmeda", kind: "decimal", required: true },
    { key: "masa_seca", label: "Masa seca", kind: "decimal", required: true },
    { key: "absorcion_de_humedad", label: "Absorción de humedad", kind: "decimal", required: false, suffix: "%", sinceVersion: 3 },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Calculado por el backend al guardar (solo lectura, desde la versión 2): las capturas anteriores no lo traen y no se recalculan.
export const P126_CALCULATED_FIELDS: readonly FieldSpec[] = [{ key: "porcentaje_cantidad_de_seco", label: "% Cantidad de seco", kind: "decimal", required: false, suffix: "%", sinceVersion: 2 }];
export const P126 = defineCandidateForm(P1_26_CODE, P126_FIELDS, { context: "machine", calculated: P126_CALCULATED_FIELDS });
/** Valor mostrado mientras se digita (el backend calcula y guarda el definitivo): masa seca / masa húmeda × 100; sin resultado con masa húmeda 0 o vacía. */
export const previewP126 = (draft: Readonly<Record<string, string>>): Record<string, string | null> => ({ porcentaje_cantidad_de_seco: percentTwoDecimals(draft.masa_seca, draft.masa_humeda) });
export const P126_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Hora (de registro, no del ensayo)", "Máquina", "Responsable (usuario autenticado, informativo)"] as const;
export const P126_PENDING: readonly { label: string; pending: string }[] = [
    { label: "% Cantidad de seco", pending: "Se calcula al guardar: masa seca ÷ masa húmeda × 100, con dos decimales (solo lectura). Con masa húmeda 0 no hay resultado. No se digita ni se recalculan las capturas anteriores." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del muestreo." },
    { label: "Máquinas y muestreo", pending: "La definición legacy dice «MP1 / MP3» pero su alcance de máquinas es «por definir»; el punto de muestreo es una lista cerrada de seis opciones (las capturas de la versión 1 lo conservan como texto libre)." },
    { label: "Masas", pending: "Decimales sin unidad, rango ni relación aprobada entre masa húmeda y masa seca." },
];
