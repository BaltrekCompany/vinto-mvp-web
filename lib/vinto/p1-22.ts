// VINTO-P1-22 «Grado de refinación Schopper» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control POR MÁQUINA (sin bobina, asignación ni OT). Los seis campos manuales son exactamente los de la definición
// legacy (form_22_grado_de_refinacion_schopper, 10 campos: 6 manuales y 4 automáticos): `numero_de_cuba` es texto; masa húmeda, volumen desplazado, °SR y amperaje son decimales; `observacion` es opcional.
// Fecha, hora, máquina y responsable son automáticos: el backend resuelve la máquina (de la ruta), el turno y la fecha operativa al REGISTRAR y el responsable es el usuario autenticado.
//
// PENDIENTE DE VINTO (no se inventa): rangos y límites de masa, volumen, °SR y amperaje, unidades (la definición solo declara «A» para el amperaje), fórmula o criterio de aceptación del grado de refinación,
// catálogo de cubas, y la HORA DEL ENSAYO: `hora` se guarda como hora de registro del servidor, que no es la hora real de la prueba. Habilitado solo en entornos de prueba.
// MF-08 (MD_Ejec 31) · versión 2: se retira «Volumen desplazado»; los demás campos y reglas no cambian. La versión 1 y sus capturas se conservan y el valor retirado se lee como solo lectura («versión anterior»).
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_22_CODE = "VINTO-P1-22";
export const P122_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_cuba", label: "Número de cuba", kind: "text", required: true },
    { key: "masa_humeda", label: "Masa húmeda", kind: "decimal", required: true },
    { key: "grado_de_refinacion_sr", label: "Grado de refinación °SR", kind: "decimal", required: true },
    { key: "amperaje", label: "Amperaje", kind: "decimal", required: true, suffix: "A" },
    { key: "observacion", label: "Observación", kind: "textarea", required: false },
];
// Campos de la versión 1 retirados en la versión 2: solo lectura, para el historial de las capturas antiguas.
export const P122_LEGACY_FIELDS: readonly FieldSpec[] = [{ key: "volumen_desplazado", label: "Volumen desplazado", kind: "decimal", required: false }];
export const P122 = defineCandidateForm(P1_22_CODE, P122_FIELDS, { context: "machine", legacy: P122_LEGACY_FIELDS });
export const P122_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Hora (de registro, no del ensayo)", "Máquina", "Responsable (usuario autenticado, informativo)"] as const;
export const P122_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real de la prueba. Si VINTO la exige, requiere un campo aprobado." },
    { label: "Rangos y unidades", pending: "Masa, °SR y amperaje son decimales sin unidad, rango ni límite aprobados (solo se declara «A» para el amperaje)." },
    { label: "Resultado", pending: "El grado de refinación se guarda tal como se digita: no se calcula ni se evalúa contra un criterio de aceptación. Registrar un control no libera ni rechaza ninguna bobina." },
    { label: "Responsable", pending: "Es el usuario autenticado, solo informativo: no es una firma." },
];
