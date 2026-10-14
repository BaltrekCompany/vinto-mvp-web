// VINTO-P1-02 «Parámetros de operación de máquina MP1» (Bobinas, MP1): contrato técnico CANDIDATO sobre el contexto de ASIGNACIÓN central (POST /api/captures). Los 48 campos manuales son EXACTAMENTE los de la
// definición legacy (form_2_parametros_de_operacion_de_maquina, 52 campos: 48 manuales y 4 automáticos), con sus claves, etiquetas, orden, tipos, obligatoriedad y unidades declaradas (el sufijo es la unidad de la
// definición). Se generaron desde esa definición, no desde la pantalla legacy. Son TEXTO (no se convierten a decimal aunque su nombre sugiera una medida): producto (digitado, NO se deriva del artículo),
// apertura_gas, apertura_termocompresor, relacion_chorro_tela, altura_caja_entrada, apertura_labio, dosificacion_release, los ocho limpieza_* y novedades. El resto son decimales.
//
// Nombre del operador, fecha, hora y turno son automáticos en la definición: el backend resuelve la fecha operativa y el turno de la asignación y registra al usuario autenticado (solo informativo: NO es una firma).
// La hora de REGISTRO del servidor (captured_at) no es la hora de la medición: no hay una hora de toma de parámetros aprobada y no se genera. Sin firmas, revisiones ni aprobaciones.
//
// PENDIENTE DE VINTO (no se inventa): rangos y límites, valores estándar, frecuencia de toma de parámetros, validaciones cruzadas entre mediciones, catálogos, la hora real de la medición y el significado de las
// unidades de «Apertura válvula de gramaje» (g/m² en la definición). Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_02_CODE = "VINTO-P1-02";
export const P102_FIELDS: readonly FieldSpec[] = [
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "velocidad_cilindro_yankee", label: "Velocidad cilindro Yankee", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_cilindro_yankee", label: "Corriente cilindro Yankee", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_prensa", label: "Velocidad prensa", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_prensa", label: "Corriente prensa", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_tela", label: "Velocidad tela", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_tela", label: "Corriente tela", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_pope", label: "Velocidad pope", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_pope", label: "Corriente pope", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_bomba_5", label: "Velocidad bomba 5", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_bomba_5", label: "Corriente bomba 5", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_bomba_fan", label: "Velocidad bomba Fan", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_bomba_fan", label: "Corriente bomba Fan", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_refinador", label: "Velocidad refinador", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_refinador", label: "Corriente refinador", kind: "decimal", required: true, suffix: "A" },
    { key: "velocidad_safem", label: "Velocidad Safem", kind: "decimal", required: true, suffix: "m/min" },
    { key: "corriente_safem", label: "Corriente Safem", kind: "decimal", required: true, suffix: "A" },
    { key: "vacio_safem", label: "Vacío Safem", kind: "decimal", required: true },
    { key: "vacio_fieltro", label: "Vacío fieltro", kind: "decimal", required: true },
    { key: "vacio_tela", label: "Vacío tela", kind: "decimal", required: true },
    { key: "apertura_gas", label: "Apertura gas", kind: "text", required: true },
    { key: "presion_cilindro_yankee", label: "Presión cilindro Yankee", kind: "decimal", required: true },
    { key: "apertura_termocompresor", label: "Apertura termocompresor", kind: "text", required: true },
    { key: "temperatura_lado_humedo_campana", label: "Temperatura lado húmedo campana", kind: "decimal", required: true, suffix: "°C" },
    { key: "temperatura_lado_seco_campana", label: "Temperatura lado seco campana", kind: "decimal", required: true, suffix: "°C" },
    { key: "gramaje_minimo", label: "Gramaje mínimo", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "gramaje_medio", label: "Gramaje medio", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "gramaje_maximo", label: "Gramaje máximo", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "humedad_minima", label: "Humedad mínima", kind: "decimal", required: true, suffix: "%" },
    { key: "humedad_media", label: "Humedad media", kind: "decimal", required: true, suffix: "%" },
    { key: "humedad_maxima", label: "Humedad máxima", kind: "decimal", required: true, suffix: "%" },
    { key: "peso_seco_minimo", label: "Peso seco mínimo", kind: "decimal", required: true, suffix: "kg" },
    { key: "peso_seco_medio", label: "Peso seco medio", kind: "decimal", required: true, suffix: "kg" },
    { key: "peso_seco_maximo", label: "Peso seco máximo", kind: "decimal", required: true, suffix: "kg" },
    { key: "apertura_valvula_de_gramaje", label: "Apertura válvula de gramaje", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "relacion_chorro_tela", label: "Relación chorro/tela", kind: "text", required: true },
    { key: "altura_caja_entrada", label: "Altura caja entrada", kind: "text", required: true },
    { key: "apertura_labio", label: "Apertura labio", kind: "text", required: true },
    { key: "dosificacion_release", label: "Dosificación Release", kind: "text", required: true },
    { key: "limpieza_sala_de_control", label: "Limpieza sala de control", kind: "text", required: true },
    { key: "limpieza_pasillo_lado_comando", label: "Limpieza pasillo lado comando", kind: "text", required: true },
    { key: "limpieza_pasillo_lado_transmision", label: "Limpieza pasillo lado transmisión", kind: "text", required: true },
    { key: "limpieza_sotano", label: "Limpieza sótano", kind: "text", required: true },
    { key: "limpieza_escaner", label: "Limpieza escáner", kind: "text", required: true },
    { key: "limpieza_mezzanine", label: "Limpieza mezzanine", kind: "text", required: true },
    { key: "limpieza_enfardadora", label: "Limpieza enfardadora", kind: "text", required: true },
    { key: "limpieza_rectificadora", label: "Limpieza rectificadora", kind: "text", required: true },
    { key: "novedades", label: "Novedades", kind: "text", required: true },
];
// Agrupación SOLO VISUAL de la captura (no cambia la estructura persistida ni representa grupos industriales aprobados): cada campo aparece exactamente una vez, en el orden del contrato.
export const P102_SECTIONS: readonly { title: string; hint?: string; keys: readonly string[] }[] = [
    { title: "Velocidad y corriente", keys: ["producto", "velocidad_cilindro_yankee", "corriente_cilindro_yankee", "velocidad_prensa", "corriente_prensa", "velocidad_tela", "corriente_tela", "velocidad_pope", "corriente_pope", "velocidad_bomba_5", "corriente_bomba_5", "velocidad_bomba_fan", "corriente_bomba_fan", "velocidad_refinador", "corriente_refinador", "velocidad_safem", "corriente_safem"] },
    { title: "Vacíos y presiones", keys: ["vacio_safem", "vacio_fieltro", "vacio_tela", "apertura_gas", "presion_cilindro_yankee", "apertura_termocompresor"] },
    { title: "Temperaturas y gramaje", keys: ["temperatura_lado_humedo_campana", "temperatura_lado_seco_campana", "gramaje_minimo", "gramaje_medio", "gramaje_maximo"] },
    { title: "Humedad y peso seco, y ajustes de caja de entrada", keys: ["humedad_minima", "humedad_media", "humedad_maxima", "peso_seco_minimo", "peso_seco_medio", "peso_seco_maximo", "apertura_valvula_de_gramaje", "relacion_chorro_tela", "altura_caja_entrada", "apertura_labio", "dosificacion_release"] },
    { title: "Limpieza y novedades", keys: ["limpieza_sala_de_control", "limpieza_pasillo_lado_comando", "limpieza_pasillo_lado_transmision", "limpieza_sotano", "limpieza_escaner", "limpieza_mezzanine", "limpieza_enfardadora", "limpieza_rectificadora", "novedades"] },
];
export const P102 = defineCandidateForm(P1_02_CODE, P102_FIELDS);
export const P102_AUTOMATIC = ["Nombre del operador (usuario autenticado, informativo; no es una firma)", "Fecha (fecha operativa de la asignación)", "Turno (el de la asignación)"] as const;
export const P102_UNRESOLVED_AUTOMATIC = ["Hora (la del registro del servidor no es la hora de la medición)"] as const; // sin fuente aprobada: no se genera ni se sustituye por la hora de registro
export const P102_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Hora de la medición", pending: "La hora de la definición es automática pero no hay fuente aprobada: no se genera ni se toma de la hora de registro (captured_at), que no es la hora de la medición." },
    { label: "Tipos de los campos", pending: "Producto, aperturas, relación chorro/tela, altura de caja, dosificación, limpiezas y novedades son TEXTO en la definición legacy y se guardan tal como se digitan, sin convertirlos a número. Producto no se deriva del artículo de la asignación." },
    { label: "Rangos y reglas", pending: "Sin rangos, límites, valores estándar, frecuencia de toma, validaciones cruzadas ni catálogos aprobados; nada se calcula." },
    { label: "Firmas y revisiones", pending: "No hay firma, revisión ni aprobación: el usuario autenticado es solo informativo." },
];
