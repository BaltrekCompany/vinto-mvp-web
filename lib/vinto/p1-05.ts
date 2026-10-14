// VINTO-P1-05 «Registro de tubetes» (Bobinas MP1 / MP3): contrato técnico CANDIDATO. Los diez campos manuales son exactamente los de la definición legacy (form_5_registro_de_tubetes, 14 campos: 10 manuales
// y 4 automáticos); fecha, turno, máquina y responsable son automáticos: los resuelve el backend (asignación y sesión) y no se digitan. Todos los campos son texto como en la definición legacy.
//
// PENDIENTE DE VINTO (no se inventa): catálogo oficial de tubetes (código, tipo, estado, procedencia y destino son TEXTO LIBRE), criterios de utilización, recuperación y devolución, reglas de inventario,
// correlativos, y cualquier asociación automática con una bobina (el número de bobina es un dato declarado, no se valida contra Producción). Habilitado solo en entornos de prueba.
import { defineCandidateForm, type CandidateAttempt, type CandidateCapture, type FieldSpec } from "./candidate-form.ts";

export const P1_05_CODE = "VINTO-P1-05";
export const P105_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: true },
    { key: "numero_codigo_de_tubete", label: "Número / código de tubete", kind: "text", required: true },
    { key: "tipo_de_tubete", label: "Tipo de tubete", kind: "text", required: true },
    { key: "cantidad_utilizada", label: "Cantidad utilizada", kind: "text", required: true },
    { key: "cantidad_recuperada", label: "Cantidad recuperada", kind: "text", required: true },
    { key: "cantidad_devuelta", label: "Cantidad devuelta", kind: "text", required: true },
    { key: "estado_del_tubete", label: "Estado del tubete", kind: "text", required: true },
    { key: "procedencia", label: "Procedencia", kind: "text", required: true },
    { key: "destino", label: "Destino", kind: "text", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P105 = defineCandidateForm(P1_05_CODE, P105_FIELDS);
export const P105_AUTOMATIC = ["Fecha", "Turno", "Máquina", "Responsable"] as const; // campos automáticos de la definición legacy
export const P105_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Catálogo de tubetes", pending: "Código, tipo, estado, procedencia y destino son texto libre: no existe catálogo oficial." },
    { label: "Cantidades", pending: "Texto tal como en la definición legacy: sin unidad, rango, utilización, recuperación ni balance." },
    { label: "Número de bobina", pending: "Dato declarado: no se valida ni se asocia automáticamente con una bobina de Producción." },
    { label: "Responsable", pending: "Es el usuario autenticado, solo informativo: no es una firma ni se asume que sea el operador de la ficha." },
];
export type P105Capture = CandidateCapture;
export type P105Attempt = CandidateAttempt;
