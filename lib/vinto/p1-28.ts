// VINTO-P1-28 «Registro de bobinas rechazadas» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, FICHA DOCUMENTAL ligada a UNA BOBINA física F3 (POST /api/quality/bobbins/{id}/captures). Los siete campos manuales
// son EXACTAMENTE los de la definición legacy (form_28_registro_de_bobinas_rechazadas, 13 campos: 7 manuales y 6 automáticos), con sus claves, etiquetas, orden, tipos y obligatoriedad, generados desde esa
// definición: número de bobina, producto y acción correctiva son texto; detalle / motivo de rechazo es textarea obligatorio; peso rechazado es decimal (kg); «Estado / disposición final» es TEXTO libre;
// `observaciones` es opcional.
//
// ES UN REGISTRO DOCUMENTAL, NO UNA DECISIÓN DE RECHAZO: lo que se digite (motivo, acción correctiva, peso rechazado y el estado / disposición final DECLARADO en la ficha) no rechaza, bloquea, libera ni cambia el
// estado oficial de Calidad de la bobina (quality_release), el inventario ni su disponibilidad. No hay endpoint de rechazo ni Q-LIB. El estado oficial se muestra aparte, solo lectura.
//
// `numero_de_bobina` debe coincidir con la bobina seleccionada (se precarga, no se edita y el backend rechaza otro valor con 422); la bobina se identifica por su UUID. `producto` es texto digitado: no se contrasta
// con el artículo de la bobina. Fecha, hora, máquina, operador, responsable de calidad y visto bueno de Producción son automáticos en la definición y NO se generan: el usuario autenticado registra la captura pero
// NO es el operador histórico, ni una firma, ni la aprobación de Calidad, ni el visto bueno de Producción. No se inventa la hora original del rechazo (`captured_at` es la hora de registro).
//
// ALCANCE ACTUAL: el inbox muestra bobinas pendientes de Calidad; la disponibilidad histórica de bobinas rechazadas y su disposición definitiva requieren un diseño posterior con VINTO. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_28_CODE = "VINTO-P1-28";
export const P128_BOBBIN_CODE_FIELD = "numero_de_bobina";
export const P128_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: true },
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "detalle_motivo_de_rechazo", label: "Detalle / motivo de rechazo", kind: "textarea", required: true },
    { key: "accion_correctiva", label: "Acción correctiva", kind: "text", required: true },
    { key: "peso_rechazado", label: "Peso rechazado", kind: "decimal", required: true, suffix: "kg" },
    { key: "estado_disposicion_final", label: "Estado / disposición final", kind: "text", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P128 = defineCandidateForm(P1_28_CODE, P128_FIELDS, { context: "bobbin" });
export const P128_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Máquina (la de la bobina)"] as const;
export const P128_UNRESOLVED_AUTOMATIC = ["Hora (la de registro no es la hora original del rechazo)", "Operador (no es el usuario autenticado)", "Responsable de calidad", "Visto bueno Producción"] as const; // sin fuente aprobada: no se generan
export const P128_ACTION_LABEL = "Registrar ficha documental P1-28 (candidato)";
export const P128_OFFICIAL_STATUS_NOTE = "El «Estado / disposición final» de la ficha es lo que se DECLARA al registrar; el estado oficial de Calidad de la bobina lo controla quality_release y no cambia con esta captura.";
export const P128_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Registro documental, no rechazo oficial", pending: "Esta ficha NO rechaza, bloquea ni libera la bobina: no modifica quality_release, inventario ni disponibilidad, no hay endpoint de rechazo ni Q-LIB. El estado oficial de Calidad sigue siendo el que se muestra aparte (solo lectura)." },
    { label: "Estado / disposición final declarado", pending: "Es texto libre declarado en la ficha: no es una decisión oficial ni un estado de la bobina, y no hay catálogo ni reglas de disposición aprobados." },
    { label: "Firmas y vistos buenos", pending: "Operador, responsable de calidad y visto bueno de Producción no tienen fuente aprobada: no se generan. El usuario autenticado solo identifica quién registra; no es firma, aprobación ni visto bueno." },
    { label: "Hora y bobinas rechazadas", pending: "No hay hora original del rechazo (la hora guardada es la de registro). El alcance actual registra una declaración documental sobre la bobina visible; la disponibilidad histórica de bobinas rechazadas y su disposición definitiva requieren un diseño posterior con VINTO." },
    { label: "Número de bobina y producto", pending: "El número debe coincidir con la bobina seleccionada (se precarga y el backend rechaza otro valor). El producto es texto digitado: no se contrasta con el artículo de la bobina." },
];
