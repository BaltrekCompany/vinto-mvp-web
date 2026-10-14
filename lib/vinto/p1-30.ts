// VINTO-P1-30 «Producción Perichun» (Rebobinado, máquina legacy PERICHUN): contrato técnico CANDIDATO sobre el contexto de ASIGNACIÓN central (POST /api/captures). Los diez campos manuales son exactamente los de
// la definición legacy (form_30_produccion_perichun, 15 campos: 10 manuales y 5 automáticos), con sus claves, etiquetas, orden, tipos y obligatoriedad: `peso_de_bobina` y `numero_mrp` son TEXTO (no se convierten
// a decimal por su nombre; «kg» solo es la unidad declarada); gramaje, formato MP1, formato de salida, resistencias y velocidad son decimales; `observaciones` es opcional. Unidades declaradas: g/m², kg y m/min.
//
// Fecha, hora de inicio, hora de término, operador y turno son automáticos en la definición. El backend resuelve la fecha operativa y el turno de la asignación y el responsable (usuario autenticado, solo
// informativo). NO hay fuente aprobada para las horas de INICIO y TÉRMINO: no se generan ni se sustituyen por la hora de registro (`captured_at`).
//
// `numero_de_bobina` es TEXTO digitado: NO crea una bobina física, no la busca ni la valida contra F3 y no consume ni relaciona nada. `numero_mrp` es texto sin regla ni relación con MRP. No se calculan pesos,
// velocidades ni resistencias.
//
// PENDIENTE DE VINTO (no se inventa): horas de inicio y término, identidad y alcance del número de bobina, relación con MRP, validaciones, rangos y límites, y las máquinas y turnos oficiales de Rebobinado
// (el sector no es operativo: el seed aprobado solo contiene MP1 y MP3). Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_30_CODE = "VINTO-P1-30";
export const P130_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: true },
    { key: "gramaje_g_m2", label: "Gramaje g/m²", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "peso_de_bobina", label: "Peso de bobina", kind: "text", required: true, suffix: "kg" },
    { key: "formato_mp1", label: "Formato MP1", kind: "decimal", required: true },
    { key: "formato_de_salida", label: "Formato de salida", kind: "decimal", required: true },
    { key: "resistencia_longitudinal", label: "Resistencia longitudinal", kind: "decimal", required: true },
    { key: "resistencia_transversal", label: "Resistencia transversal", kind: "decimal", required: true },
    { key: "numero_mrp", label: "Número MRP", kind: "text", required: true },
    { key: "velocidad", label: "Velocidad", kind: "decimal", required: true, suffix: "m/min" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P130 = defineCandidateForm(P1_30_CODE, P130_FIELDS);
export const P130_AUTOMATIC = ["Fecha (fecha operativa de la asignación)", "Turno (el de la asignación)", "Operador (usuario autenticado, informativo)"] as const;
export const P130_UNRESOLVED_AUTOMATIC = ["Hora inicio", "Hora término"] as const; // sin fuente aprobada: no se generan ni se sustituyen por la hora de registro
export const P130_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Horas de inicio y término", pending: "No hay fuente aprobada: no se generan ni se toman de la hora de registro (captured_at). Si VINTO las exige, requieren un campo o regla aprobados." },
    { label: "Número de bobina", pending: "Es texto digitado: no crea ni busca una bobina física, no se valida contra F3 y su identidad y alcance siguen pendientes de VINTO." },
    { label: "Número MRP", pending: "Texto sin regla: no se valida ni se relaciona con MRP; esa relación sigue pendiente." },
    { label: "Peso, velocidad y resistencias", pending: "El peso de bobina es TEXTO en la definición legacy y no se convierte; velocidad, formatos y resistencias son decimales sin rango ni límite aprobados. Nada se calcula." },
    { label: "Máquina, sector y turnos", pending: "Rebobinado no es un sector operativo (el seed aprobado solo tiene MP1 y MP3): PERICHUN y los turnos oficiales siguen pendientes. Solo se usan en entornos de prueba." },
];
