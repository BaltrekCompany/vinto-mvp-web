import { apiBaseUrl } from "@/lib/vinto/api";
import { createAdminClient } from "@/lib/vinto/admin";
import { createGrantsClient } from "@/lib/vinto/admin-grants";

// Cliente de /api/admin ligado a la base de la API y al fetch del navegador. Toda la lógica (validación, mapeo de errores) vive en lib/vinto/admin.ts.
export const adminApi = createAdminClient(apiBaseUrl, (url, init) => fetch(url, init));

// Concesiones máquina-formulario (MF-13-01C.3): mismo fetch del navegador, misma petición administrativa (cookie HttpOnly) y mismos fallos.
export const grantsApi = createGrantsClient(apiBaseUrl, (url, init) => fetch(url, init));
