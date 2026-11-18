/**
 * OFF-03B.1: offline boot inspection only.
 * No access to industrial forms or backend authorization; no cookies or fetch.
 * Runtime is bundled from the same TypeScript crypto modules used online.
 */
import { readLocalProfile } from "./offline-profile-store.ts";
import { unlockLocalVault } from "./offline-vault.ts";
import { readOfflineScope } from "./offline-scope-store.ts";
import { readQualityPackage } from "./offline-quality-store.ts";
import { readRenewalStatus } from "./offline-renewal.ts";
import { DEVICE_KEY_STORAGE } from "./device";

const status = document.getElementById("offline-profile-status");
const form = document.getElementById("offline-unlock-form") as HTMLFormElement | null;
const input = document.getElementById("offline-unlock-secret") as HTMLInputElement | null;
const submit = document.getElementById("offline-unlock-submit") as HTMLButtonElement | null;
const scopeList = document.getElementById("offline-scope-list") as HTMLUListElement | null;
const packagePanel = document.getElementById("offline-package-details") as HTMLDivElement | null;

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
                // Never use a signed read-only scope as a write permission.
                // Inspect full versioned definitions only after AES decryption,
                // pinned Ed25519 package signature and content SHA256 verification.
                // OFF-03C.4: a revocation learned online (or an unverifiable marker) means the
                // historical set must NOT be presented as available, even though its signature is intact.
                const renewal = scope ? await readRenewalStatus(key, { ownerId: record.ownerId, deviceKey: record.deviceKey }) : null;
                const withheld = renewal?.status === "revocation_known" || renewal?.status === "unreadable";
                const packageCards: HTMLDetailsElement[] = [];
                if (scope && packagePanel && !withheld) {
                    const candidates = scope.envelope.payload.form_scopes.filter(item =>
                        item.operation === "quality_machine_capture" &&
                        /^VINTO-P1-(18|22|26|27)$/.test(item.form_code)).slice(0,12);
                    for (const item of candidates) {
                        const stored = await readQualityPackage(key,
                            { ownerId: record.ownerId, deviceKey: record.deviceKey },
                            scope, item.machine_code, item.form_code);
                        if (!stored) continue;
                        const definition = stored.envelope.payload.definition;
                        const card = document.createElement("details");
                        const title = document.createElement("summary");
                        title.textContent = item.machine_code + " · " + definition.form_name +
                            " · " + definition.form_code + " (v" + definition.form_version + ")";
                        card.appendChild(title);
                        const list = document.createElement("ul");
                        for (const field of definition.fields) {
                            const li = document.createElement("li");
                            li.textContent = field.label + " [" + field.value_type + "]" +
                                (field.required ? " · obligatorio" : "") +
                                (field.source === "calculated" ? " · calculado por backend" : "") +
                                (field.unit ? " · " + field.unit : "");
                            if (field.options.length) {
                                const choices = document.createElement("ul");
                                for (const option of field.options) {
                                    const choice = document.createElement("li");
                                    choice.textContent = option.label;
                                    choices.appendChild(choice);
                                }
                                li.appendChild(choices);
                            }
                            list.appendChild(li);
                        }
                        card.appendChild(list);
                        packageCards.push(card);
                    }
                }
                // No CryptoKey is stored in state or passed to a capture form.
                form.hidden = true;
                if (!scope) {
                    show("Perfil local verificado sin Internet. Las capturas y los permisos industriales siguen deshabilitados.");
                    return;
                }
                if (withheld) {
                    if (scopeList) { scopeList.hidden = true; scopeList.replaceChildren(); }
                    if (packagePanel) { packagePanel.hidden = true; packagePanel.replaceChildren(); }
                    show(renewal?.status === "revocation_known"
                        ? "Se detectó con Internet que este alcance ya no está vigente (revocado o reducido). No se muestran formularios. Renueve el alcance con Internet. Las capturas y los permisos industriales siguen deshabilitados."
                        : "No se puede confirmar el estado de renovación del alcance local. Por seguridad no se muestran formularios. Renueve con Internet. Las capturas y los permisos industriales siguen deshabilitados.");
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
                if (packagePanel) {
                    packagePanel.replaceChildren(...packageCards);
                    packagePanel.hidden = packageCards.length === 0;
                }
                const freshness = renewal?.status === "renewed_online" && renewal.recordedAt
                    ? " Última renovación con Internet: " + new Date(renewal.recordedAt).toLocaleString("es") +
                      ". Sin Internet no se puede confirmar que los permisos sigan vigentes."
                    : " Este alcance no tiene marca de renovación; renuévelo con Internet.";
                show("Firma y perfil verificados sin Internet. Índice de " +
                    scope.envelope.payload.form_scopes.length + " formularios disponibles solo para consulta. " +
                    "Las capturas y los permisos industriales siguen deshabilitados." + freshness);
            } catch {
                if (scopeList) { scopeList.hidden = true; scopeList.replaceChildren(); }
                if (packagePanel) { packagePanel.hidden = true; packagePanel.replaceChildren(); }
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
