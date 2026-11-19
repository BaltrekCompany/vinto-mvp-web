/**
 * OFF-04.3 LABORATORY page runtime (bundled only when OFFLINE_DRAFT_LAB=1; absent from default builds).
 * The "server" is the in-memory FakeSyncServer: no network access of any kind, no real API. DOM via textContent only.
 * The queue is the laboratory's own database, separate from the application send queue and from the synthetic lab queue.
 */
import { readLocalProfile } from "./offline-profile-store.ts";
import { unlockLocalVault } from "./offline-vault.ts";
import { DEVICE_KEY_STORAGE } from "./device";
import { FakeSyncServer, type Fault } from "./offline-sync-fake-server.ts";
import { syncNow } from "./offline-sync-engine.ts";
import { createSyncCapture, openSyncPayload } from "./offline-sync-capture.ts";
import { createIdbSyncStore } from "./offline-sync-store.ts";
import type { SyncRecord } from "./offline-sync-types.ts";

const $ = <T>(id: string) => document.getElementById(id) as unknown as T | null;
const status = $<HTMLParagraphElement>("sync-status"), unlockForm = $<HTMLFormElement>("sync-unlock-form"), secretInput = $<HTMLInputElement>("sync-unlock-secret");
const confirmBox = $<HTMLInputElement>("sync-confirm"), workspace = $<HTMLElement>("sync-workspace"), addButton = $<HTMLButtonElement>("sync-add");
const nowButton = $<HTMLButtonElement>("sync-now"), lockButton = $<HTMLButtonElement>("sync-lock"), dependsBox = $<HTMLInputElement>("sync-depends");
const list = $<HTMLUListElement>("sync-list"), counters = $<HTMLParagraphElement>("sync-counters"), resultLine = $<HTMLParagraphElement>("sync-result");
const faultSelect = $<HTMLSelectElement>("sync-fault"), armButton = $<HTMLButtonElement>("sync-arm"), contextBox = $<HTMLInputElement>("sync-context");
const sessionSelect = $<HTMLSelectElement>("sync-session"), clockButton = $<HTMLButtonElement>("sync-clock"), serverLine = $<HTMLParagraphElement>("sync-server");

const OTHER_USER = "22222222-2222-4222-8222-222222222222";
const store = createIdbSyncStore();
const server = new FakeSyncServer({ sessionUser: null, currentContext: "ctx-1" });
let session: { key: CryptoKey; identity: { ownerId: string; deviceKey: string } } | null = null;
let clockOffset = 0, running = false;
const tabId = "tab-" + crypto.randomUUID().slice(0, 8);
const nowMs = () => Date.now() + clockOffset;
const say = (t: string) => { if (status) status.textContent = t; };

const REASONS: Record<string, string> = {
    auth_required: "La sesión en línea no es válida: se pausó sin cambiar nada. Inicie sesión de nuevo como el autor original.",
    session_invalid: "No hay sesión en línea válida: sincronización pausada, ningún registro cambió.",
    different_user: "La sesión en línea es de otro usuario: sincronización pausada. Ninguna captura se reasigna ni se envía con otra cuenta.",
    busy: "Ya hay una sincronización en curso en esta pestaña.",
};

async function cacheSelf(): Promise<void> {
    try {
        if (!("caches" in window) || !navigator.onLine) return;
        await (await caches.open("vinto-off043lab-v1")).addAll(["/offline-sync-lab.html", "/offline-sync-lab.js"]);
    } catch { /* offline or blocked */ }
}

function render(records: readonly SyncRecord[]): void {
    if (!list || !counters) return;
    list.replaceChildren();
    const c: Record<string, number> = {};
    if (records.length === 0) { const li = document.createElement("li"); li.textContent = "Sin capturas de prueba."; list.appendChild(li); }
    for (const r of [...records].sort((a, b) => a.seq - b.seq)) {
        c[r.state] = (c[r.state] ?? 0) + 1;
        const li = document.createElement("li");
        li.dataset.captureId = r.capture_id; li.dataset.state = r.state; li.className = "st-" + r.state;
        li.textContent = r.capture_id.slice(0, 8) + " · " + r.state + " · intentos " + r.attempts + (r.uncertain ? " · incierto (se reconcilia antes de repetir)" : "") +
            (r.dependsOn ? " · depende de " + r.dependsOn.slice(0, 8) : "") + (r.serverRef ? " · servidor " + r.serverRef : "") +
            (r.warnings.length ? " · advertencia: " + r.warnings.join(",") : "") + (r.lastError && !["synced", "synced_warning"].includes(r.state) ? " · " + r.lastError : "");
        list.appendChild(li);
    }
    counters.textContent = "Contadores: " + (["queued", "syncing", "retry_wait", "synced", "synced_warning", "requires_review", "conflict"] as const).map(s => s + "=" + (c[s] ?? 0)).join(" · ");
    if (serverLine) serverLine.textContent = "Servidor simulado: " + server.accepted.size + " captura(s) lógica(s) registrada(s) en " + server.sendCount + " envío(s).";
}

async function refresh(): Promise<void> {
    if (!session) return;
    try { render(await store.list(session.identity.ownerId.toLowerCase(), session.identity.deviceKey.toLowerCase())); }
    catch { say("No se pudo leer la cola de laboratorio. No se muestra nada."); }
}

function currentSessionUser(): string | null {
    const mode = sessionSelect?.value ?? "valid";
    return mode === "expired" ? null : mode === "other" ? OTHER_USER : session?.identity.ownerId ?? null;
}

async function addCapture(): Promise<void> {
    if (!session) return;
    try {
        const existing = await store.list(session.identity.ownerId.toLowerCase(), session.identity.deviceKey.toLowerCase());
        const last = [...existing].sort((a, b) => b.seq - a.seq)[0];
        const n = existing.length + 1;
        await createSyncCapture(session.key, session.identity, store, { payload: { numero_de_cuba: "C-" + n + "-SINT", masa_g: String(100 + n) },
            contextVersion: "ctx-1", dependsOn: dependsBox?.checked && last ? last.capture_id : null, seq: Date.now() * 1000 + n }, nowMs);
        say("Captura de prueba creada en la cola de laboratorio (estado queued). No se envió nada.");
        await refresh();
    } catch { say("NO se creó la captura de prueba."); }
}

function armFault(): void {
    const v = faultSelect?.value ?? "";
    if (!v) { say("No hay falla seleccionada."); return; }
    const map: Record<string, Fault> = {
        lose_response: { type: "lose_response" }, timeout_after_persist: { type: "timeout_after_persist" }, network_before: { type: "network_before" },
        s503: { type: "status", status: 503 }, s401: { type: "status", status: 401 }, s403: { type: "status", status: 403 },
        review: { type: "review" }, warning: { type: "warning", warnings: ["context_changed_after_prepare"] },
    };
    server.script(map[v]);
    say("Falla armada para la próxima solicitud del servidor simulado: " + v + ".");
}

async function syncOnce(): Promise<void> {
    if (!session || running) return;
    running = true; if (nowButton) nowButton.disabled = true;
    try {
        server.sessionUser = currentSessionUser(); server.currentContext = contextBox?.checked ? "ctx-2" : "ctx-1";
        const user = currentSessionUser();
        const result = await syncNow({
            store, transport: server.transport(), session: async () => user ? { userId: user } : null, openPayload: openSyncPayload(session.key, session.identity),
            identity: session.identity, tabId, now: nowMs, options: { timeoutMs: 3000, baseDelayMs: 5000, maxDelayMs: 120000, leaseMs: 30000, maxAttempts: 6 },
        });
        render(await store.list(session.identity.ownerId.toLowerCase(), session.identity.deviceKey.toLowerCase()));
        if (resultLine) resultLine.textContent = result.paused ? REASONS[result.paused] ?? "Pausada." :
            "Sincronización terminada: enviadas " + result.sent + ", conciliadas " + result.reconciled + ", en espera " + result.skipped.waiting + ", bloqueadas por dependencia " + result.skipped.blocked +
            (result.stopped ? ". Se detuvo por: " + result.stopped + " (se reintenta con espera creciente)." : ".") +
            (result.outcomes.length ? " Resultados: " + result.outcomes.map(o => o.capture_id.slice(0, 8) + "→" + o.to + "(" + o.detail + ")").join("; ") : "");
        say(result.paused ? REASONS[result.paused] ?? "Pausada." : "Sincronización con el servidor simulado finalizada. Nada se envió a ninguna API real.");
    } catch { say("La sincronización se interrumpió por un error de almacenamiento. Ningún registro se perdió; se recupera al reintentar."); await refresh(); }
    finally { running = false; if (nowButton) nowButton.disabled = false; }
}

async function start(): Promise<void> {
    if (!status || !unlockForm || !secretInput || !confirmBox || !workspace || !addButton || !nowButton || !lockButton) return;
    void cacheSelf();
    if (!window.isSecureContext) { say("Se requiere un contexto seguro."); return; }
    let record;
    try { record = await readLocalProfile(); } catch { say("No es posible leer el perfil local."); return; }
    if (!record) { say("No hay perfil local preparado en este navegador."); return; }
    let deviceKey: string | null = null;
    try { deviceKey = localStorage.getItem(DEVICE_KEY_STORAGE); } catch { /* fail closed */ }
    if (!deviceKey || deviceKey.toLowerCase() !== record.deviceKey) { say("El perfil no corresponde a este navegador. No se desbloqueará."); return; }
    say("Perfil local encontrado. Ingrese su frase offline y confirme el uso de datos sintéticos.");
    unlockForm.hidden = false;
    unlockForm.addEventListener("submit", async (event: SubmitEvent) => {
        event.preventDefault();
        const secret = secretInput.value; secretInput.value = "";
        if (!confirmBox.checked) { say("Confirme que usará únicamente datos sintéticos y el servidor simulado."); return; }
        try {
            const key = await unlockLocalVault(record, secret);
            session = { key, identity: { ownerId: record.ownerId, deviceKey: record.deviceKey } };
            unlockForm.hidden = true; workspace.hidden = false;
            await refresh();
            say("Laboratorio de sincronización desbloqueado. Servidor simulado; nada se envía a ninguna API real.");
        } catch { say("No fue posible desbloquear. El laboratorio permanece bloqueado."); }
    });
    addButton.addEventListener("click", () => { void addCapture(); });
    nowButton.addEventListener("click", () => { void syncOnce(); });
    armButton?.addEventListener("click", armFault);
    clockButton?.addEventListener("click", () => { clockOffset += 60_000; say("Reloj simulado avanzado 60 s (afecta solo a los tiempos de espera del laboratorio)."); });
    lockButton.addEventListener("click", () => { session = null; workspace.hidden = true; unlockForm.hidden = false; say("Laboratorio bloqueado. La clave se descartó de la memoria."); });
}

void start();
