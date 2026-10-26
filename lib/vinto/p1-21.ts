// MF-07 (MD_Ejec 21) · versión 2 de VINTO-P1-21 «Perfil de gramaje y humedad» (Calidad, MP1 / MP3): control ligado a UNA BOBINA física (POST /api/quality/bobbins/{id}/captures), ahora con UNA tabla de 27 posiciones.
// Cada posición (fila 1 a 27) tiene Gramaje (g/m²), Peso seco (kg) y % Humedad; los tres valores se DIGITAN (el % de humedad NO se calcula a partir de gramaje ni de peso seco: no hay fórmula aprobada).
// Reglas aprobadas: al menos UNA fila completa; una fila está completa con los tres valores y puede quedar totalmente vacía, pero una fila a medias se rechaza; las filas vacías no se rellenan con cero y un «0» es un valor.
// El backend es la fuente de verdad de los CALCULADOS: promedio de gramaje, de peso seco y de % humedad (media aritmética simple, dos decimales) usando SOLO las filas completas, y cuántas posiciones se usaron. Aquí solo se muestran
// mientras se digita (`previewP121`). La bobina viene de la bobina seleccionada (ya no se digita «Número de bobina»); la posición es el número de fila (ya no hay «Posición de perfil» de texto libre).
// Persistencia: 81 campos decimales por posición (gramaje_01 … humedad_27) en el motor actual de capturas, sin tocar la versión 1 ni sus capturas (que se leen con `legacy`).
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";
import { meanTwoDecimals } from "./quality-averages.ts";

export const P1_21_CODE = "VINTO-P1-21";
export const P121_POSITIONS = 27;
export const P121_COLUMNS = [
    { prefix: "gramaje", label: "Gramaje", suffix: "g/m²" },
    { prefix: "peso_seco", label: "Peso seco (kg)", suffix: "kg" },
    { prefix: "humedad", label: "% Humedad", suffix: "%" },
] as const;
export const p121Key = (prefix: string, position: number): string => `${prefix}_${String(position).padStart(2, "0")}`;
export const P121_POSITION_NUMBERS: readonly number[] = Array.from({ length: P121_POSITIONS }, (_, i) => i + 1);
export const P121_ROWS: readonly (readonly string[])[] = P121_POSITION_NUMBERS.map((n) => P121_COLUMNS.map((c) => p121Key(c.prefix, n)));
export const P121_FIELDS: readonly FieldSpec[] = [
    ...P121_POSITION_NUMBERS.flatMap((n) => P121_COLUMNS.map((c): FieldSpec => ({ key: p121Key(c.prefix, n), label: `${c.label} · posición ${n}`, kind: "decimal", required: false, suffix: c.suffix, sinceVersion: 2 }))),
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Calculados por el backend al guardar (solo lectura). Las capturas de la versión 1 no los traen.
export const P121_CALCULATED_FIELDS: readonly FieldSpec[] = [
    { key: "promedio_gramaje", label: "Promedio gramaje", kind: "decimal", required: false, suffix: "g/m²", sinceVersion: 2 },
    { key: "promedio_peso_seco", label: "Promedio peso seco", kind: "decimal", required: false, suffix: "kg", sinceVersion: 2 },
    { key: "promedio_humedad", label: "Promedio % humedad", kind: "decimal", required: false, suffix: "%", sinceVersion: 2 },
    { key: "posiciones_utilizadas", label: "Posiciones utilizadas en los promedios", kind: "integer", required: false, sinceVersion: 2 },
];
// Campos de la versión 1 (una captura = una posición), retirados en la versión 2: solo lectura, para el historial de las capturas antiguas. El número de bobina ya figura en el encabezado del historial.
export const P121_LEGACY_FIELDS: readonly FieldSpec[] = [
    { key: "numero_de_bobina", label: "Número de bobina", kind: "text", required: false },
    { key: "posicion_de_perfil", label: "Posición de perfil", kind: "text", required: false },
    { key: "gramaje", label: "Gramaje", kind: "decimal", required: false, suffix: "g/m²" },
    { key: "peso_seco", label: "Peso seco", kind: "decimal", required: false, suffix: "kg" },
];
export const P121 = defineCandidateForm(P1_21_CODE, P121_FIELDS, {
    context: "bobbin", legacy: P121_LEGACY_FIELDS, calculated: P121_CALCULATED_FIELDS,
    completeRows: { rows: P121_ROWS, min: 1, label: (index) => `Posición ${index + 1}` },
});

type Values = Readonly<Record<string, string | undefined>>;
const filled = (value: string | undefined): value is string => value !== undefined && value.trim() !== "";
/** Posiciones (1 a 27) con los TRES valores digitados; un «0» cuenta como valor. */
export const completePositions = (values: Values): number[] => P121_POSITION_NUMBERS.filter((n) => P121_COLUMNS.every((c) => filled(values[p121Key(c.prefix, n)])));
/** Promedios y posiciones usadas, solo con filas completas y con la misma regla del backend (visualización; el backend es la fuente de verdad). */
export function previewP121(values: Values): Record<string, string | null> {
    const used = completePositions(values);
    const mean = (prefix: string) => meanTwoDecimals(used.map((n) => values[p121Key(prefix, n)] as string));
    return { promedio_gramaje: mean("gramaje"), promedio_peso_seco: mean("peso_seco"), promedio_humedad: mean("humedad"), posiciones_utilizadas: used.length ? String(used.length) : null };
}

export const P121_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Hora (de registro, no del ensayo)", "Máquina (la de la bobina)", "Responsable (usuario autenticado, informativo)"] as const;
export const P121_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Tabla de 27 posiciones", pending: "Registra al menos una fila completa (Gramaje, Peso seco y % Humedad). Una fila a medias no se guarda; las filas vacías se ignoran y no se rellenan con cero." },
    { label: "Promedios", pending: "Los tres promedios (media aritmética simple, dos decimales) los calcula el sistema al guardar usando solo las filas completas; se indica cuántas posiciones se usaron. No se digitan." },
    { label: "% Humedad", pending: "Se digita en cada posición; el sistema no lo calcula a partir del gramaje ni del peso seco." },
    { label: "Número de bobina y posición", pending: "Ya no se digitan: la bobina es la seleccionada y la posición es el número de fila. Las capturas de la versión 1 los conservan." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real de la medición." },
    { label: "Efecto sobre la bobina", pending: "Registrar este control no libera ni rechaza la bobina: la liberación de Calidad sigue pendiente." },
];
