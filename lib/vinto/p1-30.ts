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
// MF-10 · versión 2 (MD_Ejec 34 y 47): se retiran «Gramaje», «Número MRP», «Resistencia longitudinal» y «Resistencia transversal»; se añade «Lote» (texto, obligatorio) en el lugar de «Resistencia longitudinal» y las horas
// «Hora inicio» y «Hora fin» (HH:MM, hora local de planta, obligatorias desde la v2; no se derivan de la hora de registro, no se calcula la duración ni se valida el orden, sin fechas deducidas por cruzar la medianoche).
// La versión 1 y sus capturas se conservan; los campos retirados se leen como «versión anterior» y no se inventa un Lote para registros anteriores.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_30_CODE = "VINTO-P1-30";
export const P130_FIELDS: readonly FieldSpec[] = [
    { key: "hora_inicio", label: "Hora inicio", kind: "time", required: true, sinceVersion: 2 },
    { key: "hora_fin", label: "Hora fin", kind: "time", required: true, sinceVersion: 2 },
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: true },
    { key: "peso_de_bobina", label: "Peso de bobina", kind: "text", required: true, suffix: "kg" },
    { key: "formato_mp1", label: "Formato MP1", kind: "decimal", required: true },
    { key: "formato_de_salida", label: "Formato de salida", kind: "decimal", required: true },
    { key: "lote", label: "Lote", kind: "text", required: true, sinceVersion: 2 },
    { key: "velocidad", label: "Velocidad", kind: "decimal", required: true, suffix: "m/min" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Campos de la versión 1 retirados en la versión 2: solo lectura, para el historial de las capturas antiguas.
export const P130_LEGACY_FIELDS: readonly FieldSpec[] = [
    { key: "gramaje_g_m2", label: "Gramaje g/m²", kind: "decimal", required: false, suffix: "g/m²" },
    { key: "resistencia_longitudinal", label: "Resistencia longitudinal", kind: "decimal", required: false },
    { key: "resistencia_transversal", label: "Resistencia transversal", kind: "decimal", required: false },
    { key: "numero_mrp", label: "Número MRP", kind: "text", required: false },
];
export const P130 = defineCandidateForm(P1_30_CODE, P130_FIELDS, { legacy: P130_LEGACY_FIELDS });
export const P130_AUTOMATIC = ["Fecha (fecha operativa de la asignación)", "Turno (el de la asignación)", "Operador (usuario autenticado, informativo)"] as const;
export const P130_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Horas de inicio y fin", pending: "Se digitan (HH:MM, hora local de planta) y son obligatorias desde la versión 2; no se derivan de la hora de registro, no se calcula la duración ni se valida el orden, y no se asume otra fecha si cruzan la medianoche." },
    { label: "Lote", pending: "Texto obligatorio desde la versión 2 (reemplaza a las resistencias); no se inventa un Lote para las capturas anteriores. Gramaje, resistencias y número MRP ya no se digitan; la versión 1 los conserva." },
    { label: "Número de bobina", pending: "Es texto digitado: no crea ni busca una bobina física, no se valida contra F3 y su identidad y alcance siguen pendientes de VINTO." },
    { label: "Peso, velocidad y formatos", pending: "El peso de bobina es TEXTO en la definición legacy y no se convierte; velocidad y formatos son decimales sin rango ni límite aprobados. Nada se calcula." },
    { label: "Máquina, sector y turnos", pending: "Rebobinado no es un sector operativo (el seed aprobado solo tiene MP1 y MP3): PERICHUN y los turnos oficiales siguen pendientes. Solo se usan en entornos de prueba." },
];
