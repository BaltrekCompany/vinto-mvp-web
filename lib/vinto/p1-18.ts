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
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_18_CODE = "VINTO-P1-18";
export const P118_FIELDS: readonly FieldSpec[] = [
    { key: "producto", label: "Producto", kind: "text", required: true },
    { key: "numero_de_cuba", label: "Número de cuba", kind: "text", required: true },
    { key: "punto_de_muestreo", label: "Punto de muestreo", kind: "text", required: true },
    { key: "masa_humeda_g", label: "Masa húmeda g", kind: "decimal", required: true },
    { key: "masa_seca_g", label: "Masa seca g", kind: "decimal", required: true },
    { key: "papel_filtro_g", label: "Papel filtro g", kind: "text", required: true },
    { key: "papel_muestra_g", label: "Papel + muestra g", kind: "text", required: true },
    { key: "peso_muestra_g", label: "Peso muestra g", kind: "decimal", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P118 = defineCandidateForm(P1_18_CODE, P118_FIELDS, { context: "machine" });
export const P118_AUTOMATIC = ["Fecha (fecha operativa del registro)", "Hora (de registro, no del ensayo)", "Máquina", "Responsable (usuario autenticado, informativo)"] as const;
export const P118_CALCULATED = ["Consistencia %"] as const; // calculado en la definición, sin fórmula aprobada: no se calcula ni se muestra
export const P118_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Consistencia %", pending: "Calculado en la definición, sin fórmula aprobada: no se calcula, no se guarda ni se muestra; el backend rechaza el envío de campos calculados." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real del muestreo." },
    { label: "Unidades y rangos", pending: "Las masas y el peso de la muestra son decimales sin rango ni límite aprobados. «Peso muestra g» declara «g» en la etiqueta y «kg» como unidad en la definición: es una contradicción pendiente de VINTO y no se muestra ninguna unidad." },
    { label: "Pesos de papel", pending: "«Papel filtro g» y «Papel + muestra g» son texto en la definición legacy: se guardan tal como se digitan, sin convertirlos a número ni usarlos en ningún cálculo." },
    { label: "Catálogos", pending: "Producto, número de cuba y punto de muestreo son texto libre sin catálogo aprobado." },
];
