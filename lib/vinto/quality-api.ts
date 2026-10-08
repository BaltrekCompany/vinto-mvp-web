import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseQualityBobbinInbox, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";

// Inbox central de Calidad: SOLO lectura. Cookie HttpOnly vía requestJson (credentials "include"); sin tokens ni cabeceras manuales.
// Sin parámetro status: el backend devuelve por defecto las pendientes (quality_release.status = 'pending').

export function listQualityBobbins(signal?: AbortSignal): Promise<ApiResult<QualityBobbinInboxItem[]>> {
    return requestJson("/api/quality/bobbins", { signal }, parseQualityBobbinInbox);
}
