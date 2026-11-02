// MF-13-02 · Textos de la pantalla de accesos. PURO. Nunca nombran el motivo interno de una denegación (perfil, sector, concesión, versión): solo lo que la persona puede hacer.
import type { AccessState } from "./eligibility.ts";

export type GateCopy = { title: string; message: string; retry: boolean };

export function accessGateCopy(state: AccessState): GateCopy {
    switch (state.status) {
        case "loading": return { title: "Verificando tus accesos…", message: "Consultando al servidor qué puedes usar. No se muestra ningún frente hasta confirmarlo.", retry: false };
        case "unconfirmed": return { title: "No se pudieron confirmar tus accesos", message: "El servidor no respondió o no hay conexión. Mientras no se confirmen no se muestra ningún frente; lo que estabas capturando se conserva en esta pantalla. Reintenta.", retry: true };
        case "denied":
        case "ready": return { title: "Sin accesos asignados", message: "Tu usuario no tiene frentes ni formularios habilitados en este momento. Solicítalos a Administración.", retry: false };
    }
}
