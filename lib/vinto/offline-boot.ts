/**
 * OFF-03B.1: offline boot inspection only.
 * No access to industrial forms or backend authorization; no cookies or fetch.
 * Runtime is bundled from the same TypeScript crypto modules used online.
 */
import { readLocalProfile } from "./offline-profile-store.ts";
import { unlockLocalVault } from "./offline-vault.ts";
import { readOfflineScope } from "./offline-scope-store.ts";
import { DEVICE_KEY_STORAGE } from "./device";

const status = document.getElementById("offline-profile-status");
const form = document.getElementById("offline-unlock-form") as HTMLFormElement | null;
const input = document.getElementById("offline-unlock-secret") as HTMLInputElement | null;
const submit = document.getElementById("offline-unlock-submit") as HTMLButtonElement | null;
const scopeList = document.getElementById("offline-scope-list") as HTMLUListElement | null;

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
                const key = await unlockLocalVault(record, password);
                const scope = await readOfflineScope(key, { ownerId: record.ownerId, deviceKey: record.deviceKey });
                // No key is retained. The signed scope is READ-ONLY metadata.
                form.hidden = true;
                if (!scope) {
                    show("Perfil local verificado sin Internet. Las capturas y los permisos industriales siguen deshabilitados.");
                    return;
                }
                if (scopeList) {
                    scopeList.replaceChildren();
                    for (const item of scope.envelope.payload.form_scopes) {
                        const li = document.createElement("li");
                        li.textContent = item.machine_code + " — " + item.form_code + " (v" + item.form_version + ")";
                        scopeList.appendChild(li);
                    }
                    scopeList.hidden = false;
                }
                show("Firma y perfil verificados sin Internet. Índice de " +
                    scope.envelope.payload.form_scopes.length + " formularios disponibles solo para consulta. " +
                    "Las capturas y los permisos industriales siguen deshabilitados.");
            } catch {
                if (scopeList) { scopeList.hidden = true; scopeList.replaceChildren(); }
                show("No fue posible desbloquear o validar el alcance firmado. Las capturas siguen deshabilitadas.");
            } finally {
                submit.disabled = false;
            }
        });
    } catch {
        show("No es posible verificar el perfil local. El almacenamiento puede estar bloqueado o dañado.");
    }
}

void start();
