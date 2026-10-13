import { apiBaseUrl } from "@/lib/vinto/api";
import { createAdminClient } from "@/lib/vinto/admin";

// Cliente de /api/admin ligado a la base de la API y al fetch del navegador. Toda la lógica (validación, mapeo de errores) vive en lib/vinto/admin.ts.
export const adminApi = createAdminClient(apiBaseUrl, (url, init) => fetch(url, init));
