// VINTO-P1-21 «Perfil de gramaje y humedad» (Calidad, MP1 / MP3): contrato técnico CANDIDATO, control ligado a UNA BOBINA física (POST /api/quality/bobbins/{id}/captures). Los cinco campos manuales son exactamente
// los de la definición legacy (form_21_perfil_de_gramaje_y_humedad, 12 campos: 5 manuales, 4 automáticos y 3 calculados): `numero_de_bobina` y `posicion_de_perfil` son texto, gramaje y peso seco son decimales
// (unidades declaradas: g/m² y kg) y `observaciones` es opcional. Fecha, hora, máquina y responsable son automáticos: el backend deriva máquina, turno y fecha operativa de la bobina (F3 de origen).
//
// `numero_de_bobina` debe coincidir con la bobina seleccionada: la pantalla lo precarga con el código de la bobina y el backend rechaza (422) cualquier otro valor. No es un catálogo ni una búsqueda.
//
// NO se calculan `humedad`, `promedio_gramaje` ni `promedio_humedad`: son campos calculados de la definición y no hay fórmula aprobada (ni qué relaciona gramaje y peso seco, ni qué se promedia). No se calculan, no
// se guardan y no se muestran; el backend rechaza cualquier campo calculado enviado.
//
// PENDIENTE DE VINTO (no se inventa): CARDINALIDAD del perfil. Por ahora UNA captura = los valores manuales de UNA posición declarada de la bobina; no hay perfil multiposición, series de ensayo ni promedios.
// También: catálogo de posiciones, rangos, a qué muestra corresponde el peso seco y la HORA DEL ENSAYO. Registrar un control no libera ni rechaza la bobina. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_21_CODE = "VINTO-P1-21";
export const P121_BOBBIN_CODE_FIELD = "numero_de_bobina";
export const P121_FIELDS: readonly FieldSpec[] = [
    { key: P121_BOBBIN_CODE_FIELD, label: "Número de bobina", kind: "text", required: true },
    { key: "posicion_de_perfil", label: "Posición de perfil", kind: "text", required: true },
    { key: "gramaje", label: "Gramaje", kind: "decimal", required: true, suffix: "g/m²" },
    { key: "peso_seco", label: "Peso seco", kind: "decimal", required: true, suffix: "kg" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P121 = defineCandidateForm(P1_21_CODE, P121_FIELDS, { context: "bobbin" });
export const P121_AUTOMATIC = ["Fecha (fecha operativa de la bobina)", "Hora (de registro, no del ensayo)", "Máquina (la de la bobina)", "Responsable (usuario autenticado, informativo)"] as const;
export const P121_CALCULATED = ["Humedad %", "Promedio gramaje", "Promedio humedad"] as const; // calculados en la definición, sin fórmula aprobada: no se calculan ni se muestran
export const P121_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Calculados", pending: "Humedad, promedio de gramaje y promedio de humedad son calculados en la definición, sin fórmula aprobada: no se calculan, no se guardan ni se muestran; el backend rechaza el envío de campos calculados." },
    { label: "Cardinalidad del perfil", pending: "Una captura representa los valores manuales de UNA posición declarada de la bobina. Perfil multiposición, series de ensayo y promedios siguen pendientes de VINTO." },
    { label: "Número de bobina", pending: "Debe coincidir con la bobina seleccionada: se precarga con su código y el backend rechaza cualquier otro valor. La captura queda asociada solo a esa bobina." },
    { label: "Hora del ensayo", pending: "La hora que guarda el sistema es la de registro (servidor): no es la hora real de la medición." },
    { label: "Posición, rangos y muestra", pending: "La posición de perfil es texto libre sin catálogo; gramaje (g/m²) y peso seco (kg) no tienen rango aprobado ni se sabe a qué muestra corresponde el peso seco." },
    { label: "Efecto sobre la bobina", pending: "Registrar este control no libera ni rechaza la bobina: la liberación de Calidad sigue pendiente." },
];
