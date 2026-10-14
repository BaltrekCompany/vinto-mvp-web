// VINTO-P1-07 «Registro de producción de bobinas refiladas» (Rebobinado, máquinas legacy COPASA / BELOIT / OVER): contrato técnico CANDIDATO sobre el contexto de ASIGNACIÓN central (POST /api/captures). Los
// treinta y seis campos manuales son EXACTAMENTE los de la definición legacy (form_7_registro_de_productos_rebobinados, 41 campos: 36 manuales y 5 automáticos), con sus claves, etiquetas, orden, tipos y
// obligatoriedad. La definición original es la única fuente: no se reconstruye desde la pantalla legacy ni se renombra nada.
//
// Los pesos de crías son 21 campos INDIVIDUALES: `peso_cria_1` … `peso_cria_11` y `peso_cria_13` … `peso_cria_22`. NO existe `peso_cria_12` en la definición y no se inventa. Todos son decimales obligatorios tal
// como están en la definición legacy; la cardinalidad y la condicionalidad (cuántas crías hay en realidad) están PENDIENTES de homologación y no se resuelven aquí. Texto: etiqueta / número de bobina, destino,
// producto refilado, auxiliar, tensión, metraje y tubete. Decimales: peso, velocidades, diámetro, formatos 1-3 y las crías. `observaciones` es opcional. Unidades declaradas: kg, m/min y mm.
//
// Fecha, hora de inicio, hora final, turno y operador son automáticos: el backend resuelve la fecha operativa y el turno de la asignación y el responsable es el usuario autenticado (solo informativo). NO hay
// fuente aprobada para las horas de INICIO y FINAL: no se generan ni se sustituyen por la hora de registro.
//
// ESTO ES SOLO UNA CAPTURA TÉCNICA CANDIDATA, NO UNA GENEALOGÍA (docs/M5-A-p107-genealogia.md): `etiqueta_numero_de_bobina` es TEXTO y NO identifica una bobina madre; este circuito no crea bobinas hijas, no consume
// madres, no crea relaciones madre-hija, correlativos, balances de masa ni movimientos de inventario, y no toca quality_release. Que exista este circuito de captura NO equivale a una genealogía funcional.
//
// PENDIENTE DE VINTO (no se inventa): horas de inicio y final, identidad de la bobina madre, genealogía madre-hija, cardinalidad y condicionalidad de los pesos de crías, catálogo de productos y destinos, reglas
// de corte, rendimiento y mermas, y las máquinas y turnos oficiales de Rebobinado. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_07_CODE = "VINTO-P1-07";
// Números de las crías de la definición legacy: 1-11 y 13-22 (21 campos). El 12 NO existe.
export const P107_CRIA_NUMBERS: readonly number[] = [...Array.from({ length: 11 }, (_, i) => i + 1), ...Array.from({ length: 10 }, (_, i) => i + 13)];
const CRIAS: readonly FieldSpec[] = P107_CRIA_NUMBERS.map((n) => ({ key: `peso_cria_${n}`, label: `Peso cría ${n}`, kind: "decimal", required: true, suffix: "kg" }));
export const P107_FIELDS: readonly FieldSpec[] = [
    { key: "etiqueta_numero_de_bobina", label: "Etiqueta / número de bobina", kind: "text", required: true },
    { key: "peso", label: "Peso", kind: "decimal", required: true, suffix: "kg" },
    { key: "destino", label: "Destino", kind: "text", required: true },
    { key: "producto_refilado", label: "Producto refilado", kind: "text", required: true },
    { key: "auxiliar", label: "Auxiliar", kind: "text", required: true },
    { key: "velocidad_minima", label: "Velocidad mínima", kind: "decimal", required: true, suffix: "m/min" },
    { key: "tension", label: "Tensión", kind: "text", required: true },
    { key: "velocidad", label: "Velocidad", kind: "decimal", required: true, suffix: "m/min" },
    { key: "metraje", label: "Metraje", kind: "text", required: true },
    { key: "diametro", label: "Diámetro", kind: "decimal", required: true, suffix: "mm" },
    { key: "formato_1", label: "Formato 1", kind: "decimal", required: true },
    { key: "formato_2", label: "Formato 2", kind: "decimal", required: true },
    { key: "formato_3", label: "Formato 3", kind: "decimal", required: true },
    { key: "tubete", label: "Tubete", kind: "text", required: true },
    ...CRIAS,
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Agrupación SOLO VISUAL de la captura (no cambia la estructura persistida ni crea grupos repetibles): cada campo aparece exactamente una vez.
export const P107_SECTIONS: readonly { title: string; hint?: string; keys: readonly string[] }[] = [
    { title: "Bobina y destino", keys: ["etiqueta_numero_de_bobina", "peso", "destino", "producto_refilado", "auxiliar"] },
    { title: "Parámetros de proceso", keys: ["velocidad_minima", "tension", "velocidad", "metraje", "diametro", "formato_1", "formato_2", "formato_3", "tubete"] },
    { title: "Pesos de crías", hint: "21 campos individuales (1-11 y 13-22; no existe la cría 12). La definición legacy los marca todos obligatorios: cuántas crías hay en realidad está pendiente de homologación.", keys: CRIAS.map((c) => c.key) },
    { title: "Observaciones", keys: ["observaciones"] },
];
export const P107 = defineCandidateForm(P1_07_CODE, P107_FIELDS);
export const P107_AUTOMATIC = ["Fecha (fecha operativa de la asignación)", "Turno (el de la asignación)", "Operador (usuario autenticado, informativo)"] as const;
export const P107_UNRESOLVED_AUTOMATIC = ["Hora inicio", "Hora final"] as const; // sin fuente aprobada: no se generan ni se sustituyen por la hora de registro
export const P107_PENDING: readonly { label: string; pending: string }[] = [
    { label: "No es genealogía", pending: "Este circuito solo captura los campos manuales de P1-07. No crea bobinas hijas, no consume bobinas madre, no crea relaciones madre-hija ni correlativos, no calcula balances de masa ni mueve inventario, y no toca la liberación de Calidad. Capturar P1-07 NO equivale a una genealogía funcional." },
    { label: "Etiqueta / número de bobina", pending: "Es texto digitado y NO identifica una bobina madre: su identidad y relación siguen pendientes de VINTO." },
    { label: "Horas de inicio y final", pending: "No hay fuente aprobada: no se generan ni se toman de la hora de registro (captured_at)." },
    { label: "Pesos de crías", pending: "21 campos individuales (1-11 y 13-22; no existe la cría 12), todos decimales obligatorios según la definición legacy. La cardinalidad y la condicionalidad (cuántas salidas hay) están pendientes y no se calcula ningún total ni balance." },
    { label: "Catálogos y reglas", pending: "Producto refilado, destino, tubete, tensión y metraje son texto sin catálogo; no hay reglas de corte, rendimiento ni mermas aprobadas." },
    { label: "Máquinas, sector y turnos", pending: "Rebobinado no es un sector operativo (el seed aprobado solo tiene MP1 y MP3): COPASA, BELOIT, OVER y los turnos oficiales siguen pendientes. Solo se usan en entornos de prueba." },
];
