// Pantallas centrales CANDIDATAS del sector Conversión (G.12-C4-FINAL25): P1-12 «Producción diaria de papel higiénico», P1-13 «Producción diaria de servilletas y especiales» y P1-16
// «Registro de control de merma». Configuración PURA que enlaza cada formulario con su definición declarativa (candidate-form.ts), su cliente de API de Producción (/api/captures) y los textos
// de sus decisiones pendientes. Se ofrecen solo si el backend publica el formulario para la máquina de la sesión (GET /api/production/machines); con la configuración real Conversión no es
// operativo por defecto fuera del piloto QA y no se ofrece nada si no se concede el sector.
//
// P1-11 «Consumo de bobinas» y P1-29 «Producción tubetera» NO están aquí: usan grupos repetibles (filas de bobinas declaradas) y conservan su propio componente de captura
// (components/vinto/p1-11-capture.tsx, components/vinto/p1-29-capture.tsx), no el renderizador genérico de campos planos.
import { candidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import type { FieldSpec } from "./candidate-form.ts";
import { P112, P112_AUTOMATIC, P112_PENDING, P1_12_CODE } from "./p1-12.ts";
import { P113_AUTOMATIC, P1_13_CODE } from "./p1-13.ts";
import { P113_V4, P113_V4_FIELDS } from "./p1-13-v3.ts";
import { P116, P116_AUTOMATIC, P116_FIELDS, P116_PENDING, P1_16_CODE } from "./p1-16.ts";

export const CONVERSION_CANDIDATE_SCREENS = ["p112", "p113", "p116"] as const;
export type ConversionCandidateScreen = (typeof CONVERSION_CANDIDATE_SCREENS)[number];
export const isConversionCandidate = (screen: string | null): screen is ConversionCandidateScreen => screen !== null && (CONVERSION_CANDIDATE_SCREENS as readonly string[]).includes(screen);

// MF-11: agrupación SOLO VISUAL (no cambia lo guardado): las horas generales de producción van aparte del resto de los campos de la definición.
const HOURS_HINT = "Hora local de planta (HH:MM), digitada. No es la hora de registro del sistema ni la hora de un pallet.";
const withHours = (fields: readonly FieldSpec[], restTitle: string) => [
    { title: "Horas de producción", hint: HOURS_HINT, keys: ["hora_inicio", "hora_fin"] },
    { title: restTitle, keys: fields.filter((f) => f.key !== "hora_inicio" && f.key !== "hora_fin").map((f) => f.key) },
];

export type ConversionCandidate = Omit<CandidateScreen, "api"> & { api: ReturnType<typeof candidateApi> }; // con `list` para el historial

export const CONVERSION_CANDIDATES: Record<ConversionCandidateScreen, ConversionCandidate> = {
    p112: { code: P1_12_CODE, form: P112, api: candidateApi(P112), kicker: "Papel higiénico · Conversión", title: "Producción diaria de papel higiénico", automatic: P112_AUTOMATIC, pending: P112_PENDING,
        sections: [{ title: "Producción por pallet", keys: ["cantidad_jabas", "hora_inicio", "hora_fin"] }],
        historyNote: "P1-12 v4: un pallet por captura, número por OT y línea; peso nominal maestro y peso total congelados al guardar. Las versiones 1-3 conservan sus campos históricos sin conversiones." },
    p113: { code: P1_13_CODE, form: P113_V4, api: candidateApi(P113_V4), kicker: "Servilletas y especiales · Conversión", title: "Producción diaria de servilletas y especiales", automatic: P113_AUTOMATIC, pending: [],
        sections: [{ title: "Consumo de bobina", keys: P113_V4_FIELDS.filter(f => !["cantidad_jabas", "hora_inicio", "hora_fin"].includes(f.key)).map(f => f.key) },
            { title: "Producción por pallet", keys: ["cantidad_jabas", "hora_inicio", "hora_fin"] }],
        historyNote: "P1-13 v4: solo tipo y número de bobina obligatorios; pallet únicamente cuando se informan jabas. Versiones 1/2/3 históricas conservadas." },
    p116: { code: P1_16_CODE, form: P116, api: candidateApi(P116), kicker: "Control de merma · Conversión", title: "Registro de control de merma", automatic: P116_AUTOMATIC, pending: P116_PENDING,
        sections: [{ title: "Pesada de merma", keys: P116_FIELDS.map(f => f.key) }],
        historyNote: "Desde v4, registro por pesada con correlativo, tipo, origen y peso real; sin horas digitadas. Las versiones 2/3 conservan sus horas históricas y las versiones 1/2 sus cantidades antiguas." },
};
