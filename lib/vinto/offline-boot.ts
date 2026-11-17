/**
 * OFF-03B.1: offline boot inspection only.
 * No access to industrial forms or backend authorization; no cookies or fetch.
 * Runtime is bundled from the same TypeScript crypto modules used online.
 */
import { readLocalProfile } from "./offline-profile-store.ts";
import { unlockLocalVault } from "./offline-vault.ts";
import { DEVICE_KEY_STORAGE } from "./device";

const status = document.getElementById("offline-profile-status");
const form = document.getElementById("offline-unlock-form") as HTMLFormElement | null;
const input = document.getElementById("offline-unlock-secret") as HTMLInputElement | null;
const submit = document.getElementById("offline-unlock-submit") as HTMLButtonElement | null;

function show(message: string): void {
    if (status) status.textContent = message;
}

async function start(): Promise<void> {
    if (!status || !form || !input || !submit) return;
    // A foreign/anonymous browser cannot activate a profile. First enrolment is online only.
    if (!window.isSecureContext) {
        show("El navegador no ofrece un contexto seguro para desbloqueo local.");
        return;
    }
    try {
        const record = await readLocalProfile();
        if (!record) {
            show("No hay ningún perfil preparado en este navegador. Debe realizarse la preparación con Internet.");
            return;
        }
        let deviceKey: string | null = null;
        try { deviceKey = localStorage.getItem(DEVICE_KEY_STORAGE); } catch { /* fail closed */ }
        if (!deviceKey || deviceKey.toLowerCase() !== record.deviceKey) {
            show("El perfil no corresponde al identificador local de este navegador. No se desbloqueará.");
            return;
        }
        show("Perfil local preparado. Ingrese su frase offline para verificarlo.");
        form.hidden = false;
        form.addEventListener("submit", async (event: SubmitEvent) => {
            event.preventDefault();
            const password = input.value;
            input.value = "";
            submit.disabled = true;
            show("Verificando perfil local...");
            try {
                // Do not retain key after this diagnostic. OFF-03B.2 will supply
                // granted, encrypted form snapshots and a bounded unlock session.
                await unlockLocalVault(record, password);
                form.hidden = true;
                show("Perfil local verificado sin Internet. Las capturas y los permisos industriales siguen deshabilitados.");
            } catch {
                show("No fue posible desbloquear este perfil local. Verifique la frase de acceso.");
            } finally {
                submit.disabled = false;
            }
        });
    } catch {
        show("No es posible verificar el perfil local. El almacenamiento puede estar bloqueado o dañado.");
    }
}

void start();
