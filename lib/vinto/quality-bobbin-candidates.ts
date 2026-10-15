// Pantalla central CANDIDATA de Calidad ligada a UNA BOBINA física (DEV-Q2 y DEV-Q3): P1-21 «Perfil de gramaje y humedad», P1-24 «Propiedades físicas en húmedo» y P1-25 «Resistencia en húmedo-curado». Configuración PURA que enlaza el formulario con su definición declarativa (contexto "bobbin"), su cliente de
// API (rutas de capturas de Calidad por bobina) y los textos de sus decisiones pendientes. Se ofrece solo si el backend publica el candidato para la máquina de la bobina (GET /api/quality/bobbin-forms).
import { bobbinCandidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P121, P121_AUTOMATIC, P121_BOBBIN_CODE_FIELD, P121_CALCULATED, P121_PENDING, P1_21_CODE } from "./p1-21.ts";
import { P124, P124_AUTOMATIC, P124_BOBBIN_CODE_FIELD, P124_CALCULATED, P124_PENDING, P1_24_CODE } from "./p1-24.ts";
import { P128, P128_ACTION_LABEL, P128_AUTOMATIC, P128_BOBBIN_CODE_FIELD, P128_OFFICIAL_STATUS_NOTE, P128_PENDING, P128_UNRESOLVED_AUTOMATIC, P1_28_CODE } from "./p1-28.ts";
import { P125, P125_AUTOMATIC, P125_BOBBIN_CODE_FIELD, P125_CALCULATED, P125_PENDING, P1_25_CODE } from "./p1-25.ts";
import type { QualityBobbinScreen } from "./quality-offers.ts";

export type QualityBobbinCandidate = CandidateScreen & { bobbinApi: ReturnType<typeof bobbinCandidateApi> };

const make = (rest: Omit<CandidateScreen, "api">, api: ReturnType<typeof bobbinCandidateApi>): QualityBobbinCandidate => ({ ...rest, api, bobbinApi: api });

export const QUALITY_BOBBIN_CANDIDATES: Record<QualityBobbinScreen, QualityBobbinCandidate> = {
    p121: make({ code: P1_21_CODE, form: P121, kicker: "Calidad · control de una bobina", title: "Perfil de gramaje y humedad", automatic: P121_AUTOMATIC, pending: P121_PENDING, calculated: P121_CALCULATED,
        bobbinCodeField: P121_BOBBIN_CODE_FIELD,
        historyNote: "Control candidato de ESTA bobina (registros guardados en PostgreSQL). Una captura es una posición declarada; no se calculan humedad ni promedios y registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P121)),
    p124: make({ code: P1_24_CODE, form: P124, kicker: "Calidad · control de una bobina", title: "Propiedades físicas en húmedo", automatic: P124_AUTOMATIC, pending: P124_PENDING, calculated: P124_CALCULATED,
        bobbinCodeField: P124_BOBBIN_CODE_FIELD,
        historyNote: "Control candidato de ESTA bobina (MP1 / MP3; rebobinadoras no cubiertas). Los valores se muestran tal como se digitaron: no se calculan promedios y registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P124)),
    p125: make({ code: P1_25_CODE, form: P125, kicker: "Calidad · control de una bobina", title: "Resistencia en húmedo-curado", automatic: P125_AUTOMATIC, pending: P125_PENDING, calculated: P125_CALCULATED,
        bobbinCodeField: P125_BOBBIN_CODE_FIELD,
        historyNote: "Control candidato de ESTA bobina (alcance de máquinas por definir). Los valores se muestran tal como se digitaron: no se calculan promedios ni porcentaje y registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P125)),
    p128: make({ code: P1_28_CODE, form: P128, kicker: "Calidad · ficha documental de una bobina", title: "Registro de bobinas rechazadas", automatic: P128_AUTOMATIC, pending: P128_PENDING, unresolved: P128_UNRESOLVED_AUTOMATIC,
        bobbinCodeField: P128_BOBBIN_CODE_FIELD, actionLabel: P128_ACTION_LABEL, officialStatusNote: P128_OFFICIAL_STATUS_NOTE,
        hints: { estado_disposicion_final: "Estado / disposición final DECLARADO en la ficha: no es el estado oficial de Calidad de la bobina." },
        historyNote: "Registros documentales de ESTA bobina: lo declarado (motivo, acción, peso rechazado y estado / disposición) no rechaza, bloquea ni libera la bobina ni cambia su estado oficial de Calidad." }, bobbinCandidateApi(P128)),
};
