// Pantallas centrales CANDIDATAS del sector Conversión (G.12-C4-FINAL25): P1-12 «Producción diaria de papel higiénico», P1-13 «Producción diaria de servilletas y especiales» y P1-16
// «Registro de control de merma». Configuración PURA que enlaza cada formulario con su definición declarativa (candidate-form.ts), su cliente de API de Producción (/api/captures) y los textos
// de sus decisiones pendientes. Se ofrecen solo si el backend publica el formulario para la máquina de la sesión (GET /api/production/machines); con la configuración real Conversión no es
// operativo por defecto fuera del piloto QA y no se ofrece nada si no se concede el sector.
//
// P1-11 «Consumo de bobinas» y P1-29 «Producción tubetera» NO están aquí: usan grupos repetibles (filas de bobinas declaradas) y conservan su propio componente de captura
// (components/vinto/p1-11-capture.tsx, components/vinto/p1-29-capture.tsx), no el renderizador genérico de campos planos.
import { candidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P112, P112_AUTOMATIC, P112_PENDING, P1_12_CODE } from "./p1-12.ts";
import { P113, P113_AUTOMATIC, P113_PENDING, P1_13_CODE } from "./p1-13.ts";
import { P116, P116_AUTOMATIC, P116_PENDING, P1_16_CODE } from "./p1-16.ts";

export const CONVERSION_CANDIDATE_SCREENS = ["p112", "p113", "p116"] as const;
export type ConversionCandidateScreen = (typeof CONVERSION_CANDIDATE_SCREENS)[number];
export const isConversionCandidate = (screen: string | null): screen is ConversionCandidateScreen => screen !== null && (CONVERSION_CANDIDATE_SCREENS as readonly string[]).includes(screen);

export type ConversionCandidate = Omit<CandidateScreen, "api"> & { api: ReturnType<typeof candidateApi> }; // con `list` para el historial

export const CONVERSION_CANDIDATES: Record<ConversionCandidateScreen, ConversionCandidate> = {
    p112: { code: P1_12_CODE, form: P112, api: candidateApi(P112), kicker: "Papel higiénico · Conversión", title: "Producción diaria de papel higiénico", automatic: P112_AUTOMATIC, pending: P112_PENDING,
        historyNote: "Ficha candidata construida desde los 20 campos manuales de la definición legacy: los valores se muestran tal como se digitaron; sin saldos finales, mermas ni firma." },
    p113: { code: P1_13_CODE, form: P113, api: candidateApi(P113), kicker: "Servilletas y especiales · Conversión", title: "Producción diaria de servilletas y especiales", automatic: P113_AUTOMATIC, pending: P113_PENDING,
        historyNote: "Ficha candidata construida desde los 18 campos manuales de la definición legacy: los valores se muestran tal como se digitaron; sin mermas ni saldos finales calculados." },
    p116: { code: P1_16_CODE, form: P116, api: candidateApi(P116), kicker: "Control de merma · Conversión", title: "Registro de control de merma", automatic: P116_AUTOMATIC, pending: P116_PENDING,
        historyNote: "Ficha candidata construida desde los 8 campos manuales de la definición legacy: los valores se muestran tal como se digitaron; sin merma total calculada." },
};
