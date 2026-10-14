"use client";

import { useState } from "react";
import { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";
import { CandidateHistory } from "@/components/vinto/candidate-history";
import type { CandidateAttempt, CandidateCapture } from "@/lib/vinto/candidate-form";
import { QUALITY_BOBBIN_CANDIDATES } from "@/lib/vinto/quality-bobbin-candidates";
import type { QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import type { QualityBobbinScreen } from "@/lib/vinto/quality-offers";
import { candidateHistoryKey } from "@/lib/vinto/resource-view";
import { useResource } from "@/lib/vinto/use-central";

// Candidato de Calidad ligado a UNA BOBINA física (DEV-Q2, P1-21): la captura declarativa (contexto "bobbin") y, debajo, el historial CENTRAL de ESTA bobina para este formulario. La bobina seleccionada del inbox (o el
// snapshot de un intento pendiente) es la autoridad: no usa la asignación activa, Capture/save(), vinto-p1-records ni localStorage. La clave del historial incluye la sesión y la bobina, de modo que nunca se ve el
// historial de otra cuenta ni de otra bobina. Registrar un control no libera ni rechaza la bobina.
type Props = {
    screen: QualityBobbinScreen;
    item: QualityBobbinInboxItem; // la bobina del intento pendiente si existe; si no, la seleccionada
    scope: string; // sessionScope(user)
    online: boolean;
    attempt: CandidateAttempt | null;
    setAttempt: (attempt: CandidateAttempt | null) => void;
    back: () => void;
    user?: { display_name: string } | null;
    onSessionLost: () => void;
};

export function QualityBobbinCandidateCapture({ screen, item, scope, online, attempt, setAttempt, back, user, onSessionLost }: Props) {
    const candidate = QUALITY_BOBBIN_CANDIDATES[screen];
    const [refreshKey, setRefreshKey] = useState(0);
    const history = useResource<CandidateCapture[]>(candidateHistoryKey(`${screen}-${item.bobbin.id}`, scope, refreshKey), true, signal => candidate.bobbinApi.list(item.bobbin.id, signal), onSessionLost);
    return <>
        <CandidateFormCapture key={`${screen}:${item.bobbin.id}`} candidate={candidate} bobbin={item} online={online} attempt={attempt} setAttempt={setAttempt} back={back}
            onSubmitted={() => setRefreshKey(n => n + 1)} onAssignmentChanged={back} onSessionLost={onSessionLost} user={user}/>
        <div className="mx-auto max-w-[1600px] px-4 pb-8" data-section="bobbin-candidate-history"><CandidateHistory candidate={candidate} resource={history.view} refresh={history.refresh}/></div>
    </>;
}
