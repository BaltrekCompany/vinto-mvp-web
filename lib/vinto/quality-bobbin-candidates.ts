// Pantalla central CANDIDATA de Calidad ligada a UNA BOBINA física (DEV-Q2 y DEV-Q3): P1-21 «Perfil de gramaje y humedad», P1-24 «Propiedades físicas en húmedo» y P1-25 «Resistencia en húmedo-curado». Configuración PURA que enlaza el formulario con su definición declarativa (contexto "bobbin"), su cliente de
// API (rutas de capturas de Calidad por bobina) y los textos de sus decisiones pendientes. Se ofrece solo si el backend publica el candidato para la máquina de la bobina (GET /api/quality/bobbin-forms).
import { bobbinCandidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P121, P121_AUTOMATIC, P121_COLUMNS, P121_PENDING, P121_POSITION_NUMBERS, P1_21_CODE, p121Key, previewP121 } from "./p1-21.ts";
import { previewMeans } from "./quality-averages.ts";
import { P124, P124_AUTOMATIC, P124_MEANS, P124_PENDING, P1_24_CODE } from "./p1-24.ts";
import { P128, P128_ACTION_LABEL, P128_AUTOMATIC, P128_BOBBIN_CODE_FIELD, P128_OFFICIAL_STATUS_NOTE, P128_PENDING, P128_UNRESOLVED_AUTOMATIC, P1_28_CODE } from "./p1-28.ts";
import { P125, P125_AUTOMATIC, P125_MEANS, P125_PENDING, P1_25_CODE } from "./p1-25.ts";
import type { QualityBobbinScreen } from "./quality-offers.ts";

export type QualityBobbinCandidate = CandidateScreen & { bobbinApi: ReturnType<typeof bobbinCandidateApi> };

const make = (rest: Omit<CandidateScreen, "api">, api: ReturnType<typeof bobbinCandidateApi>): QualityBobbinCandidate => ({ ...rest, api, bobbinApi: api });

export const QUALITY_BOBBIN_CANDIDATES: Record<QualityBobbinScreen, QualityBobbinCandidate> = {
    p121: make({ code: P1_21_CODE, form: P121, kicker: "Calidad · control de una bobina", title: "Perfil de gramaje y humedad", automatic: P121_AUTOMATIC, pending: P121_PENDING,
        table: { columns: P121_COLUMNS, positions: P121_POSITION_NUMBERS, keyFor: p121Key }, preview: previewP121,
        historyNote: "Control de ESTA bobina (registros guardados en PostgreSQL): tabla de hasta 27 posiciones; los promedios los calcula el sistema con las filas completas. Registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P121)),
    p124: make({ code: P1_24_CODE, form: P124, kicker: "Calidad · control de una bobina", title: "Propiedades físicas en húmedo", automatic: P124_AUTOMATIC, pending: P124_PENDING,
        preview: (draft) => previewMeans(P124_MEANS, draft),
        historyNote: "Control candidato de ESTA bobina (MP1 / MP3; rebobinadoras no cubiertas). Los promedios húmedos los calcula el sistema al guardar (desde la versión 3); registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P124)),
    p125: make({ code: P1_25_CODE, form: P125, kicker: "Calidad · control de una bobina", title: "Resistencia en húmedo-curado", automatic: P125_AUTOMATIC, pending: P125_PENDING,
        preview: (draft) => previewMeans(P125_MEANS, draft),
        historyNote: "Control candidato de ESTA bobina (alcance de máquinas por definir). Los promedios de resistencia longitudinal los calcula el sistema al guardar (desde la versión 3); el porcentaje no se calcula y registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P125)),
    p128: make({ code: P1_28_CODE, form: P128, kicker: "Calidad · ficha documental de una bobina", title: "Registro de bobinas rechazadas", automatic: P128_AUTOMATIC, pending: P128_PENDING, unresolved: P128_UNRESOLVED_AUTOMATIC,
        bobbinCodeField: P128_BOBBIN_CODE_FIELD, actionLabel: P128_ACTION_LABEL, officialStatusNote: P128_OFFICIAL_STATUS_NOTE,
        hints: { estado_disposicion_final: "Estado / disposición final DECLARADO en la ficha: no es el estado oficial de Calidad de la bobina." },
        historyNote: "Registros documentales de ESTA bobina: lo declarado (motivo, acción, peso rechazado y estado / disposición) no rechaza, bloquea ni libera la bobina ni cambia su estado oficial de Calidad." }, bobbinCandidateApi(P128)),
};
