// VINTO-P1-18 «Porcentaje de consistencia» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control POR MÁQUINA (sin bobina, asignación ni OT). Los nueve campos manuales son exactamente los de la definición
// legacy (form_18_porcentaje_de_consistencia, 14 campos: 9 manuales, 4 automáticos y 1 calculado), con sus claves, etiquetas, orden, tipos y obligatoriedad: producto, número de cuba, punto de muestreo, papel filtro
// y papel + muestra son TEXTO (no se convierten a decimal por su nombre: «g» en la etiqueta no los vuelve numéricos); masa húmeda, masa seca y peso de la muestra son decimales; `observaciones` es opcional.
// Fecha, hora, máquina y responsable son automáticos: el backend resuelve la máquina (de la ruta), el turno y la fecha operativa al REGISTRAR y el responsable es el usuario autenticado.
//
// NO se calcula `consistencia`: es un campo calculado de la definición y no hay fórmula aprobada (no se sabe qué masas la componen ni cómo intervienen el papel filtro y el peso de la muestra). No se calcula, no se
// guarda y no se muestra; el backend rechaza cualquier campo calculado enviado.
//
// PENDIENTE DE VINTO (no se inventa): fórmula y base de la consistencia, rangos y unidades (la etiqueta de `peso_muestra_g` dice «g» y la definición declara «kg»; no se muestra ninguna unidad), catálogos de producto,
// cuba y punto de muestreo, el significado y formato de los dos pesos de papel (texto libre) y la HORA DEL ENSAYO (`hora` es la de registro del servidor). Habilitado solo en entornos de prueba.
// MF-08 · versión 2 (MD_Ejec 37, 38 y 39): se retira «Punto de muestreo»; «% Consistencia» (decimal DIGITADO, en %, OPCIONAL: su obligatoriedad no fue confirmada y no se infiere del símbolo %) va inmediatamente después de
// «Masa seca g»; «Hora» (HH:MM, hora local de planta, OBLIGATORIA desde la versión 2) es la hora real del ensayo digitada: no es la hora automática de registro, no se convierte a UTC y no se deduce ninguna fecha por cruzar
// la medianoche (la fecha operativa sigue siendo la del registro). La versión 1 y sus capturas se conservan; los campos retirados se leen como solo lectura. Hora se ubica tras «Número de cuba» (el Excel no indica posición).
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_18_CODE = "VINTO-P1-18";
export const P118_FIELDS: readonly FieldSpec[] = [
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "numero_de_cuba", label: "Número de cuba", kind: "text", required: true },
    { key: "hora_del_ensayo", label: "Hora", kind: "time", required: true, sinceVersion: 2 },
    { key: "masa_humeda_g", label: "Masa húmeda g", kind: "decimal", required: true },
    { key: "masa_seca_g", label: "Masa seca g", kind: "decimal", required: true },
    { key: "porcentaje_consistencia", label: "% Consistencia", kind: "decimal", required: false, suffix: "%" },
    { key: "papel_filtro_g", label: "Papel filtro g", kind: "text", required: true },
    { key: "papel_muestra_g", label: "Papel + muestra g", kind: "text", required: true },
    { key: "peso_muestra_g", label: "Peso muestra g", kind: "decimal", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Campos de la versión 1 retirados en la versión 2: solo lectura, para el historial de las capturas antiguas.
export const P118_LEGACY_FIELDS: readonly FieldSpec[] = [{ key: "punto_de_muestreo", label: "Punto de muestreo", kind: "text", required: false }];
export const P118 = defineCandidateForm(P1_18_CODE, P118_FIELDS, { context: "machine", legacy: P118_LEGACY_FIELDS });
export const P118_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Hora (de registro, no del ensayo)", "Máquina", "Responsable (usuario autenticado, informativo)"] as const;
export const P118_CALCULATED = ["Consistencia %"] as const; // calculado en la definición, sin fórmula aprobada: no se calcula ni se muestra
export const P118_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Consistencia %", pending: "Calculado en la definición, sin fórmula aprobada: no se calcula, no se guarda ni se muestra; el backend rechaza el envío de campos calculados." },
    { label: "Hora del ensayo", pending: "«Hora» es la hora real del ensayo, digitada (HH:MM, hora local de planta) y obligatoria desde la versión 2; es distinta de la hora automática de registro. No se convierte a UTC ni se deduce otra fecha si el ensayo cruza la medianoche." },
    { label: "% Consistencia", pending: "Se digita (decimal, en %) y es opcional en esta versión: no se calcula, no hay rango ni límite de aceptación y su obligatoriedad no fue confirmada." },
    { label: "Unidades y rangos", pending: "Las masas y el peso de la muestra son decimales sin rango ni límite aprobados. «Peso muestra g» declara «g» en la etiqueta y «kg» como unidad en la definición: es una contradicción pendiente de VINTO y no se muestra ninguna unidad." },
    { label: "Pesos de papel", pending: "«Papel filtro g» y «Papel + muestra g» son texto en la definición legacy: se guardan tal como se digitan, sin convertirlos a número ni usarlos en ningún cálculo." },
    { label: "Catálogos", pending: "Producto y número de cuba son texto libre sin catálogo aprobado. El punto de muestreo ya no se digita (MF-08); las capturas de la versión 1 lo conservan." },
];
