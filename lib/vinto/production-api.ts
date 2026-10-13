import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseAvailability, type Availability } from "@/lib/vinto/availability";

// Máquinas y formularios centrales operables por la sesión (solo lectura; el backend verifica sector operativo, concesiones y política de formularios).
// `withArticles` pide además los artículos vinculados a cada máquina (programación de OT sin listas estáticas).
export function getProductionAvailability(signal?: AbortSignal, withArticles = false): Promise<ApiResult<Availability>> {
    return requestJson(`/api/production/machines${withArticles ? "?articles=true" : ""}`, { signal }, parseAvailability);
}
