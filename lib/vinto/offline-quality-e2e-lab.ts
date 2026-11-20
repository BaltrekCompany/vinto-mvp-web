/**
 * OFF-04.5B-06B LABORATORY page runtime (bundled only when OFFLINE_DRAFT_LAB=1; absent from default builds).
 *
 * End to end, with SYNTHETIC data only:  online login (real VINTO session cookie) → device preparation (local vault, signed scope and package from the QA
 * synthetic issuer) → capture offline → encrypted draft → immutable local pending → EXPLICIT bridge to the sync-engine queue → "Sincronizar ahora" through the
 * OFF-04.3 engine → isolated QA receiver (OFF-04.4).
 * The ONLY network target is the page's OWN origin (HTTPS, or loopback http for a disposable CI/dev server) through `api()`: relative `/api/...` paths, cookie
 * credentials, no identity header, no configurable URL. Sync is only for the ORIGINAL author's authenticated session. It never touches the application's send
 * queue, never enables industrial capture, and "Sincronizado" means technical receipt only (never industrial approval).
 */
import { readLocalProfile, storeLocalProfile } from "./offline-profile-store.ts";
import { createLocalVault, unlockLocalVault, VaultError } from "./offline-vault.ts";
import { readOfflineScope, storeOfflineScope, type VerifiedLocalScope } from "./offline-scope-store.ts";
import { readQualityPackage, storeQualityPackage } from "./offline-quality-store.ts";
import { interpretLogin, interpretSession, type AuthUser } from "./auth.ts";
import { readRenewalStatus } from "./offline-renewal.ts";
import { QUALITY_OPERATIONS, type VerifiedQualityDefinition, type QualityField } from "./offline-quality-verify.ts";
import { bobbinContextVersion, type BobbinContext } from "./offline-draft-schema.ts";
import { listBobbinContexts, storeBobbinContext, BobbinStoreError } from "./offline-bobbin-store.ts";
import { DEVICE_KEY_STORAGE, getDeviceKey } from "./device";
import { isCalculated, isLabEligible, type DraftValues } from "./offline-draft-schema.ts";
import { DraftError, listQualityDrafts, loadQualityDraft, saveQualityDraft, type DraftSummary } from "./offline-draft-store.ts";
import { captureIdFor, LabQueueError, loadFrozenForDraft, queueLabDraft } from "./offline-lab-queue.ts";
import { createSyncCapture, openSyncPayload } from "./offline-sync-capture.ts";
import { syncNow } from "./offline-sync-engine.ts";
import { createHttpSyncTransport, type HttpCall } from "./offline-sync-http-transport.ts";
import { createIdbSyncStore } from "./offline-sync-store.ts";
import type { SyncRecord, SyncState } from "./offline-sync-types.ts";

const $ = <T>(id: string) => document.getElementById(id) as unknown as T | null;
const status = $<HTMLParagraphElement>("e2e-status"), unlockForm = $<HTMLFormElement>("e2e-unlock-form"), secretInput = $<HTMLInputElement>("e2e-unlock-secret");
const confirmBox = $<HTMLInputElement>("e2e-confirm"), workspace = $<HTMLElement>("e2e-workspace"), select = $<HTMLSelectElement>("e2e-package");
const newButton = $<HTMLButtonElement>("e2e-new"), lockButton = $<HTMLButtonElement>("e2e-lock"), counters = $<HTMLParagraphElement>("e2e-counters");
const capturesList = $<HTMLUListElement>("e2e-captures"), modeLine = $<HTMLParagraphElement>("e2e-receiver-mode");
const authStatus = $<HTMLParagraphElement>("e2e-auth-status"), loginForm = $<HTMLFormElement>("e2e-login-form"), loginUser = $<HTMLInputElement>("e2e-login-user"), loginPass = $<HTMLInputElement>("e2e-login-pass");
const logoutButton = $<HTMLButtonElement>("e2e-logout"), prepareForm = $<HTMLFormElement>("e2e-prepare-form"), prepareMachine = $<HTMLInputElement>("e2e-prepare-machine"), preparePass = $<HTMLInputElement>("e2e-prepare-pass");
const syncButton = $<HTMLButtonElement>("e2e-sync-now"), clockButton = $<HTMLButtonElement>("e2e-clock"), resultLine = $<HTMLParagraphElement>("e2e-result");
const editor = $<HTMLFormElement>("e2e-editor"), fieldsBox = $<HTMLDivElement>("e2e-fields"), info = $<HTMLParagraphElement>("e2e-info");
const title = $<HTMLHeadingElement>("e2e-editor-title"), queueButton = $<HTMLButtonElement>("e2e-queue");
const bobbinBox = $<HTMLElement>("e2e-bobbin-box"), bobbinSelect = $<HTMLSelectElement>("e2e-bobbin"), bobbinCode = $<HTMLInputElement>("e2e-bobbin-code");
const bobbinPrepare = $<HTMLButtonElement>("e2e-bobbin-prepare"), bobbinInfo = $<HTMLParagraphElement>("e2e-bobbin-info");

const FORMS_RE = /^VINTO-P1-(18|19|20|21|22|24|25|26|27|28)$/;   // the ten Quality forms of OFF-04.6 (the QA issuer decides which ones this user holds)
const MACHINE_RE = /^[A-Za-z0-9_.-]{1,48}$/;
type Session = { key: CryptoKey; identity: { ownerId: string; deviceKey: string }; scope: VerifiedLocalScope; packages: VerifiedQualityDefinition[] };
type Editing = { id: string; revision: number | null; pkg: VerifiedQualityDefinition; readOnly: boolean; bobbin: BobbinContext | null };
let session: Session | null = null, editing: Editing | null = null, clockOffset = 0, syncing = false;
const syncStore = createIdbSyncStore();
const tabId = "tab-" + crypto.randomUUID().slice(0, 8);
const nowMs = () => Date.now() + clockOffset;
const say = (t: string) => { if (status) status.textContent = t; };

/** Same origin only: HTTPS, or loopback http for a disposable CI/dev server. There is no way to point the page at another URL. */
function sameOriginAllowed(): boolean {
    return location.protocol === "https:" || (location.protocol === "http:" && (location.hostname === "127.0.0.1" || location.hostname === "localhost"));
}
const ONLINE_OK = sameOriginAllowed();

/** The page's single network primitive: a relative /api/ path on its own origin, with the real session cookie and no identity header. */
async function api(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal): Promise<{ status: number; json: unknown }> {
    if (!ONLINE_OK || !/^\/api\/[A-Za-z0-9_\-/]*$/.test(path)) throw new Error("path");
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "include", cache: "no-store", signal });
    return { status: res.status, json: await res.json().catch(() => ({})) };
}
type Me = { status: "ok"; user: AuthUser } | { status: "anonymous" } | { status: "unreachable" };
async function currentUser(signal?: AbortSignal): Promise<Me> {
    try {
        const res = await api("GET", "/api/auth/me", undefined, signal);
        const view = interpretSession(res.status, res.json);
        return view.status === "authenticated" ? { status: "ok", user: view.user } : view.status === "anonymous" ? { status: "anonymous" } : { status: "unreachable" };
    } catch { return { status: "unreachable" }; }
}

const CAPTION: Record<string, string> = {
    draft: "Guardado localmente (borrador editable) — aún NO es un pendiente",
    pending: "Pendiente local — NO sincronizado (aún no está en la cola de sincronización)",
    queued: "Pendiente de sincronización",
    retry_wait: "Pendiente de sincronización (reintento programado)",
    syncing: "Sincronizando…",
    synced: "Sincronizado: recepción técnica confirmada (NO es aprobación industrial)",
    synced_warning: "Sincronizado con advertencia: recepción técnica confirmada (NO es aprobación industrial)",
    requires_review: "Requiere revisión",
    conflict: "Conflicto",
};
const LOST = "LABORATORIO BLOQUEADO: la base de laboratorio se perdió o fue reemplazada. No se reactiva nada.";
const ISSUE: Record<string, string> = { required: "obligatorio", type: "valor no válido para el tipo", option: "no es una opción permitida", unknown: "campo desconocido", calculated: "campo calculado", too_long: "demasiado largo" };
const isLost = (e: unknown) => (e instanceof DraftError || e instanceof LabQueueError) && e.reason === "lab_lost";

function lockAll(message: string): void {
    session = null; editing = null;
    if (workspace) workspace.hidden = true;
    if (editor) editor.hidden = true;
    if (unlockForm) unlockForm.hidden = false;
    say(message);
}
const byBobbin = (pkg: VerifiedQualityDefinition, scope: VerifiedLocalScope): boolean => {
    const p = pkg.envelope.payload;
    return scope.envelope.payload.form_scopes.some(x => x.machine_code === p.machine_code && x.form_code === p.form_code && x.operation === "quality_bobbin_capture");
};
const bobbinLine = (b: BobbinContext | null) => b ? " · bobina " + b.bobbin_code + " (OT " + b.work_order + ", línea " + b.line_code + ", PV " + b.pv_reference + ", " + b.article_code + ", turno " + b.shift_code + ", " + b.operating_date + ")" : "";
const describe = (pkg: VerifiedQualityDefinition) => { const p = pkg.envelope.payload; return p.machine_code + " · " + p.definition.form_name + " · " + p.form_code + " (v" + p.form_version + ")"; };

function inputFor(field: QualityField, value: string | boolean | undefined, readOnly: boolean): HTMLElement {
    let el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    if (field.options.length > 0 || field.value_type === "boolean") {
        el = document.createElement("select");
        const blank = document.createElement("option"); blank.value = ""; blank.textContent = "—"; el.appendChild(blank);
        const choices = field.value_type === "boolean" ? [{ k: "true", l: "Sí" }, { k: "false", l: "No" }] : field.options.map(o => ({ k: o.option_key, l: o.label }));
        for (const c of choices) { const o = document.createElement("option"); o.value = c.k; o.textContent = c.l; el.appendChild(o); }
        el.value = value === undefined ? "" : String(value);
    } else if (field.value_type === "textarea") {
        el = document.createElement("textarea"); el.rows = 3; el.value = typeof value === "string" ? value : "";
    } else {
        el = document.createElement("input"); el.type = field.value_type === "date" ? "date" : field.value_type === "time" ? "time" : "text";
        if (field.value_type === "decimal") el.inputMode = "decimal";
        el.value = typeof value === "string" ? value : "";
    }
    el.id = "f-" + field.key; el.dataset.key = field.key;
    if (isCalculated(field)) { el.disabled = true; el.dataset.calculated = "1"; el.value = ""; if (!(el instanceof HTMLSelectElement)) el.placeholder = "calculado por el servidor al sincronizar"; } else if (readOnly) el.disabled = true;
    return el as unknown as HTMLElement;
}

function renderEditor(e: Editing, values: DraftValues, note: string): void {
    if (!editor || !fieldsBox || !info || !title) return;
    title.textContent = describe(e.pkg) + bobbinLine(e.bobbin) + (e.revision === null ? " — nuevo borrador" : " — revisión " + e.revision);
    info.textContent = note;
    editor.dataset.draftId = e.id;
    fieldsBox.replaceChildren();
    for (const field of [...e.pkg.envelope.payload.definition.fields].sort((a, b) => a.display_order - b.display_order)) {
        const wrap = document.createElement("label"), label = document.createElement("span");
        label.textContent = field.label + (field.required && !isCalculated(field) ? " *" : "");
        wrap.appendChild(label); wrap.appendChild(inputFor(field, values[field.key], e.readOnly));
        const err = document.createElement("span"); err.className = "err"; err.id = "err-" + field.key; wrap.appendChild(err);
        fieldsBox.appendChild(wrap);
    }
    const save = $<HTMLButtonElement>("e2e-save"); if (save) save.disabled = e.readOnly;
    if (queueButton) queueButton.hidden = e.readOnly || e.revision === null;
    editor.hidden = false;
}
function collect(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const el of Array.from(fieldsBox?.querySelectorAll("[data-key]") ?? []) as unknown as { value: string; dataset: DOMStringMap }[]) {
        if (el.dataset.calculated === "1") continue;
        const key = el.dataset.key as string;
        const f = editing?.pkg.envelope.payload.definition.fields.find(x => x.key === key);
        if (f?.value_type === "boolean") { if (el.value === "true") out[key] = true; else if (el.value === "false") out[key] = false; } else out[key] = el.value;
    }
    return out;
}
function showIssues(issues: readonly { key: string; code: string }[]): void {
    for (const el of Array.from(fieldsBox?.querySelectorAll<HTMLElement>(".err") ?? [])) el.textContent = "";
    for (const i of issues) { const el = document.getElementById("err-" + i.key); if (el) el.textContent = ISSUE[i.code] ?? i.code; }
}

type Row = { draft: Extract<DraftSummary, { corrupt: false }> | null; id: string; stage: string; sync: SyncRecord | null };
async function rows(): Promise<{ list: Row[]; sync: SyncRecord[]; pendings: number }> {
    const s = session!;
    const drafts = await listQualityDrafts(s.key, s.identity);
    const sync = await syncStore.list(s.identity.ownerId.toLowerCase(), s.identity.deviceKey.toLowerCase());
    const byCapture = new Map(sync.map(r => [r.capture_id, r]));
    const list: Row[] = [];
    let pendings = 0;
    for (const d of drafts) {
        if (d.corrupt) { list.push({ draft: null, id: d.id, stage: "corrupt", sync: null }); continue; }
        const record = byCapture.get(await captureIdFor(s.identity.ownerId, s.identity.deviceKey, d.id)) ?? null;
        if (d.frozen) pendings += 1;
        list.push({ draft: d, id: d.id, stage: record ? record.state : d.frozen ? "pending" : "draft", sync: record });
    }
    return { list, sync, pendings };
}

async function refresh(): Promise<void> {
    if (!session || !capturesList || !counters) return;
    let data;
    try { data = await rows(); } catch (error) { if (isLost(error)) { lockAll(LOST); return; } say("No se pudo leer el almacenamiento local. No se muestra nada."); return; }
    capturesList.replaceChildren();
    if (data.list.length === 0) { const li = document.createElement("li"); li.textContent = "Sin capturas en este navegador."; capturesList.appendChild(li); }
    const c: Record<string, number> = {};
    for (const r of data.list) {
        c[r.stage] = (c[r.stage] ?? 0) + 1;
        const li = document.createElement("li");
        li.dataset.draftId = r.id; li.dataset.stage = r.stage; li.className = "st-" + r.stage;
        if (r.sync) li.dataset.captureId = r.sync.capture_id;
        if (!r.draft) { li.textContent = "Borrador " + r.id.slice(0, 8) + " ilegible: se conserva sin modificar."; capturesList.appendChild(li); continue; }
        const caption = document.createElement("span");
        caption.textContent = r.draft.formCode + " · " + r.draft.machineCode + " · " + r.id.slice(0, 8) + " · " + (CAPTION[r.stage] ?? r.stage) +
            (r.sync ? " · intentos " + r.sync.attempts + (r.sync.uncertain ? " · incierto (se concilia antes de repetir)" : "") + (r.sync.serverRef ? " · servidor " + r.sync.serverRef : "") +
                (r.sync.warnings.length ? " · advertencia: " + r.sync.warnings.join(",") : "") + (r.sync.lastError && !["synced", "synced_warning"].includes(r.sync.state) ? " · " + r.sync.lastError : "") : "");
        li.appendChild(caption);
        const open = document.createElement("button"); open.type = "button"; open.className = "open"; open.textContent = "Abrir"; open.addEventListener("click", () => { void openDraft(r.id); });
        li.appendChild(open);
        if (r.stage === "pending") {
            const bridge = document.createElement("button"); bridge.type = "button"; bridge.className = "bridge"; bridge.dataset.draftId = r.id;
            bridge.textContent = "Incorporar a la cola de sincronización"; bridge.addEventListener("click", () => { void bridgeToSync(r.id); });
            li.appendChild(bridge);
        }
        capturesList.appendChild(li);
    }
    const sc = (s: SyncState) => data.sync.filter(r => r.state === s).length;
    counters.textContent = "Contadores: borradores=" + (c.draft ?? 0) + " · pendientes locales=" + (c.pending ?? 0) + " · en cola: queued=" + sc("queued") + " syncing=" + sc("syncing") +
        " retry_wait=" + sc("retry_wait") + " synced=" + sc("synced") + " synced_warning=" + sc("synced_warning") + " requires_review=" + sc("requires_review") + " conflict=" + sc("conflict");
}

let bobbinsOfMachine: BobbinContext[] = [];
/** Show the bobbin controls only for by-bobbin forms, and list the contexts prepared (online) for the selected machine and signed-scope snapshot. */
async function refreshBobbins(): Promise<void> {
    if (!session || !bobbinBox || !bobbinSelect) return;
    const pkg = session.packages[Number(select?.value ?? 0)];
    const wanted = !!pkg && byBobbin(pkg, session.scope);
    bobbinBox.hidden = !wanted;
    bobbinsOfMachine = [];
    bobbinSelect.replaceChildren();
    if (!wanted || !pkg) return;
    try {
        const r = await listBobbinContexts(session.key, session.identity, session.scope.envelope.payload.snapshot_id, pkg.envelope.payload.machine_code);
        bobbinsOfMachine = r.contexts;
        for (const b of r.contexts) { const o = document.createElement("option"); o.value = b.bobbin_id; o.textContent = b.bobbin_code + " · OT " + b.work_order + " · " + b.article_code; bobbinSelect.appendChild(o); }
        if (bobbinInfo) bobbinInfo.textContent = r.contexts.length === 0 ? "Sin bobinas preparadas para esta máquina: use «Preparar contexto de bobina» (requiere conexión)." :
            r.contexts.length + " bobina(s) preparada(s)." + (r.damaged ? " " + r.damaged + " ilegible(s) se conservan sin usar." : "");
    } catch (error) { if (bobbinInfo) bobbinInfo.textContent = error instanceof BobbinStoreError && error.reason === "locked" ? "Bobinas bloqueadas." : "No se pudieron leer las bobinas preparadas."; }
}

/** ONLINE: ask the QA API for the historical context of one bobbin (signed scope proves the by-bobbin grant), seal it locally. Nothing else changes. */
async function prepareBobbin(): Promise<void> {
    if (!session || !bobbinCode) return;
    const pkg = session.packages[Number(select?.value ?? 0)];
    const code = bobbinCode.value.trim();
    if (!pkg || !/^[A-Za-z0-9_.-]{1,48}$/.test(code)) { say("Indique un número de bobina válido."); return; }
    try {
        const me = await currentUser();
        if (me.status !== "ok" || me.user.id.toLowerCase() !== session.identity.ownerId) { say("Preparar una bobina requiere la sesión en línea del mismo operario."); return; }
        const res = await api("POST", "/api/offline/bobbin-context", { device_key: session.identity.deviceKey, machine_code: pkg.envelope.payload.machine_code, bobbin_code: code, signed_scope: session.scope.envelope });
        if (res.status !== 200) { say(res.status === 403 ? "No hay concesión por bobina para este usuario y máquina." : "No se obtuvo el contexto de la bobina (" + res.status + ")."); return; }
        const body = res.json as { snapshot_id?: string; contexts?: unknown[] };
        if (body.snapshot_id !== session.scope.envelope.payload.snapshot_id || !Array.isArray(body.contexts)) { say("Respuesta de contexto no válida: no se guardó nada."); return; }
        if (body.contexts.length === 0) { say("No existe una bobina con ese número en esta máquina."); return; }
        for (const ctx of body.contexts) await storeBobbinContext(session.key, session.identity, body.snapshot_id, ctx);
        bobbinCode.value = "";
        await refreshBobbins();
        say("Contexto de bobina guardado cifrado (" + body.contexts.length + "). Ya puede crear borradores de esa bobina sin conexión.");
    } catch (error) { say(error instanceof BobbinStoreError ? "No se pudo guardar el contexto de la bobina localmente. No se guardó nada incompleto." : "Sin conexión con el servidor QA: no se preparó la bobina."); }
}

async function openDraft(id: string): Promise<void> {
    if (!session) return;
    try {
        const loaded = await loadQualityDraft(session.key, session.identity, id);
        const frozen = loaded.frozenBy !== null ? await loadFrozenForDraft(session.key, session.identity, id) : null;
        const source = frozen ? frozen.draft : loaded.payload;
        const pkg = session.packages.find(p => p.envelope.payload.machine_code === source.machine_code && p.envelope.payload.form_code === source.form_code &&
            p.envelope.payload.form_version === source.form_version);
        if (!pkg) { say("No hay una definición local para este borrador."); return; }
        editing = { id, revision: frozen ? frozen.source_revision : loaded.revision, pkg, readOnly: frozen !== null, bobbin: (source as { bobbin_context?: BobbinContext }).bobbin_context ?? null };
        renderEditor(editing, source.values, frozen ? "CONTENIDO CONGELADO del pendiente local (revisión " + frozen.source_revision + "). Inmutable; no es aprobación industrial." : "Borrador editable (revisión " + loaded.revision + ").");
        say(frozen ? "Contenido congelado del pendiente local cargado." : "Borrador cargado (revisión " + loaded.revision + ").");
    } catch (error) {
        if (isLost(error)) { lockAll(LOST); return; }
        say("Borrador ilegible, alterado o bloqueado: no se muestra contenido no verificado.");
    }
}

async function save(): Promise<void> {
    if (!session || !editing || editing.readOnly) return;
    showIssues([]);
    try {
        const r = await saveQualityDraft(session.key, session.identity, { scope: session.scope, pkg: editing.pkg }, { id: editing.id, values: collect(), expectedRevision: editing.revision, bobbin: editing.bobbin });
        editing = { ...editing, revision: r.revision };
        if (title) title.textContent = describe(editing.pkg) + bobbinLine(editing.bobbin) + " — revisión " + r.revision;
        if (queueButton) queueButton.hidden = false;
        showIssues(r.missingRequired);
        say("Guardado localmente (borrador cifrado, revisión " + r.revision + "): " + (r.complete ? "completo" : "incompleto, faltan " + r.missingRequired.length + " obligatorio(s)") + ". No se envió nada.");
        await refresh();
    } catch (error) {
        if (isLost(error)) { lockAll(LOST); return; }
        if (error instanceof DraftError && error.reason === "invalid") { showIssues(error.issues); say("NO se guardó: corrija los campos marcados."); }
        else if (error instanceof DraftError && error.reason === "conflict") say("NO se guardó: otra pestaña guardó una versión más reciente. Reabra el borrador.");
        else if (error instanceof DraftError && error.reason === "pending_local") say("NO se guardó: este borrador ya es un pendiente local inmutable.");
        else if (error instanceof DraftError && error.reason === "bobbin_required") say("NO se guardó: este formulario es por bobina; prepare y seleccione una bobina.");
        else if (error instanceof DraftError && error.reason === "quota") say("NO se guardó: el almacenamiento del navegador está lleno.");
        else say("NO se guardó el borrador. Nada fue enviado.");
    }
}

async function makePending(): Promise<void> {
    if (!session || !editing || editing.readOnly || editing.revision === null) return;
    try {
        const r = await queueLabDraft(session.key, session.identity, { scope: session.scope, pkg: editing.pkg }, { id: editing.id, expectedRevision: editing.revision });
        const frozen = await loadFrozenForDraft(session.key, session.identity, editing.id);
        editing = { ...editing, readOnly: true, revision: frozen.source_revision };
        renderEditor(editing, frozen.draft.values, "CONTENIDO CONGELADO del pendiente local. Inmutable; no es aprobación industrial.");
        say((r.created ? "Pendiente local creado" : "Ya era un pendiente local") + " — NO sincronizado todavía. Use «Incorporar a la cola de sincronización» para enviarlo en el laboratorio.");
        await refresh();
    } catch (error) {
        if (isLost(error)) { lockAll(LOST); return; }
        const r = error instanceof LabQueueError ? error.reason : "storage";
        if (r === "incomplete") { showIssues((error as LabQueueError).missing.map(key => ({ key, code: "required" }))); say("NO se creó el pendiente: faltan campos obligatorios. El borrador sigue como borrador."); }
        else if (r === "conflict") say("NO se creó el pendiente: otra pestaña cambió este borrador. Reabra el borrador.");
        else say("NO se creó el pendiente (" + r + "). El borrador se conserva intacto.");
    }
}

/** EXPLICIT bridge: the frozen pending becomes a record of the sync-engine TEST queue (same capture_id). Nothing else is connected. */
async function bridgeToSync(draftId: string): Promise<void> {
    if (!session) return;
    try {
        const frozen = await loadFrozenForDraft(session.key, session.identity, draftId);
        const existing = await syncStore.list(session.identity.ownerId.toLowerCase(), session.identity.deviceKey.toLowerCase());
        const b = frozen.draft.bobbin_context;
        const record = await createSyncCapture(session.key, session.identity, syncStore, {
            captureId: frozen.capture_id, payload: frozen.draft.values as Record<string, unknown>, formCode: frozen.draft.form_code, formVersion: frozen.draft.form_version,
            machineCode: frozen.draft.machine_code, scopeSnapshotId: frozen.draft.scope_snapshot_id,
            // machine forms: the signed-scope snapshot is the context; by-bobbin forms: SHA-256(snapshot, bobbin, server digest), the same derivation the receiver recomputes from its database
            contextVersion: b ? await bobbinContextVersion(frozen.draft.scope_snapshot_id, b.bobbin_id, b.context_digest) : frozen.draft.scope_snapshot_id,
            ...(b ? { bobbin: { bobbin_id: b.bobbin_id, context_digest: b.context_digest } } : {}),
            seq: Date.now() * 1000 + existing.length,
        }, nowMs);
        say("Incorporado a la cola de sincronización del laboratorio (" + record.state + "). Aún no se envió: use «Sincronizar ahora».");
        await refresh();
    } catch (error) {
        if (isLost(error)) { lockAll(LOST); return; }
        say("NO se pudo incorporar a la cola de sincronización. El pendiente local se conserva intacto.");
    }
}

const REASON: Record<string, string> = {
    auth_required: "No hay sesión en línea válida: sincronización pausada sin cambiar nada. Inicie sesión de nuevo como el autor original.",
    session_invalid: "No hay sesión en línea válida: sincronización pausada, ningún registro cambió.",
    different_user: "La sesión en línea es de otro usuario: pausada. Ninguna captura se reasigna ni se envía con otra cuenta.",
    busy: "Ya hay una sincronización en curso en esta pestaña.",
};

async function syncOnce(): Promise<void> {
    if (!session || syncing || !ONLINE_OK) return;
    syncing = true; if (syncButton) syncButton.disabled = true;
    const s = session;
    try {
        // Reachability first: with no connection nothing is sent and no record changes (the engine would only add backoff noise).
        const probe = await currentUser();
        if (probe.status === "unreachable") { say("Sin conexión con el servidor QA: no se envió nada. Los pendientes se conservan."); return; }
        const http: HttpCall = ({ method, path, body, signal }) => api(method, path, body, signal);
        const result = await syncNow({
            store: syncStore, transport: createHttpSyncTransport(http),
            // The session is the REAL one: asked to the server every time. Another user's session, an expired one or none pauses the engine without any change.
            session: async () => { const me = await currentUser(); return me.status === "ok" ? { userId: me.user.id.toLowerCase() } : null; },
            openPayload: openSyncPayload(s.key, s.identity), identity: s.identity, tabId, now: nowMs,
            options: { timeoutMs: 8000, baseDelayMs: 5000, maxDelayMs: 120000, leaseMs: 30000, maxAttempts: 6 },
        });
        await refresh();
        const text = result.paused ? REASON[result.paused] ?? "Pausada." :
            "Sincronización terminada: enviadas " + result.sent + ", conciliadas " + result.reconciled + ", en espera " + result.skipped.waiting + ", bloqueadas " + result.skipped.blocked +
            (result.stopped ? ". Se detuvo por: " + result.stopped + " (se reintenta con espera creciente)." : ".") +
            (result.outcomes.length ? " Resultados: " + result.outcomes.map(o => o.capture_id.slice(0, 8) + "→" + o.to + "(" + o.detail + ")").join("; ") : "");
        if (resultLine) resultLine.textContent = text;
        say(result.paused ? REASON[result.paused] ?? "Pausada." : "Sincronización con el receptor QA finalizada. Recepción técnica no es aprobación industrial.");
    } catch {
        say("La sincronización se interrumpió por un error de almacenamiento. Ningún pendiente se perdió; se recupera al reintentar.");
        await refresh();
    } finally { syncing = false; if (syncButton) syncButton.disabled = false; void refreshAuth(); }
}

/** The lab is its own offline shell: it registers the same public service worker the app uses (public assets and lab pages only; it never touches /api/). */
async function registerShell(): Promise<void> {
    try { if ("serviceWorker" in navigator && ONLINE_OK) await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }); } catch { /* offline or blocked: a cached page keeps working */ }
}

async function cacheSelf(): Promise<void> {
    try {
        if (!("caches" in window) || !navigator.onLine) return;
        await (await caches.open("vinto-off045lab-v1")).addAll(["/offline-e2e-lab.html", "/offline-e2e-lab.js"]);
    } catch { /* offline or blocked */ }
}

async function refreshAuth(): Promise<void> {
    if (!authStatus) return;
    const me = await currentUser();
    authStatus.textContent = me.status === "ok" ? "Sesión en línea: " + me.user.username + " (autor autenticado)." : me.status === "anonymous" ? "Sin sesión en línea." : "Sin conexión con el servidor QA.";
    authStatus.dataset.state = me.status;
    if (loginForm) loginForm.hidden = me.status === "ok";
    if (logoutButton) logoutButton.hidden = me.status !== "ok";
    if (prepareForm) prepareForm.hidden = me.status !== "ok";
}

async function doLogin(): Promise<void> {
    if (!loginUser || !loginPass) return;
    const username = loginUser.value.trim(), password = loginPass.value; loginPass.value = "";
    if (!username || !password) { say("Indique usuario y contraseña."); return; }
    try {
        const res = await api("POST", "/api/auth/login", { username, password });
        const result = interpretLogin(res.status, res.json);
        say(result.status === "ok" ? "Sesión iniciada." : result.status === "invalid" ? "Credenciales incorrectas." : result.status === "rejected" ? "Datos de acceso rechazados." : "No se pudo iniciar sesión ahora.");
    } catch { say("Sin conexión con el servidor QA: no se pudo iniciar sesión."); }
    await refreshAuth();
}

async function doLogout(): Promise<void> {
    try { await api("POST", "/api/auth/logout"); } catch { /* the local cookie may remain: /me decides */ }
    await refreshAuth();
    say("Sesión cerrada en línea. Las capturas locales se conservan; el envío requiere iniciar sesión de nuevo.");
}

/** ONLINE enrolment with the same building blocks as /offline-preparacion: local vault → signed scope (key pinned from THIS authenticated response) → signed package. */
async function prepareDevice(): Promise<void> {
    if (!prepareMachine || !preparePass) return;
    const secret = preparePass.value; preparePass.value = "";
    const machine = prepareMachine.value.trim();
    if (!MACHINE_RE.test(machine)) { say("Código de máquina no válido."); return; }
    try {
        const me = await currentUser();
        if (me.status !== "ok") { say("Inicie sesión en línea antes de preparar el dispositivo."); return; }
        const deviceKey = getDeviceKey();
        if (localStorage.getItem(DEVICE_KEY_STORAGE) !== deviceKey) { say("El navegador no pudo guardar la identidad del dispositivo."); return; }
        const identity = { ownerId: me.user.id.toLowerCase(), deviceKey: deviceKey.toLowerCase() };
        let record = await readLocalProfile();
        if (!record) { record = (await createLocalVault(identity, secret)).record; await storeLocalProfile(record); await showUnlock(); }
        else if (record.ownerId !== identity.ownerId || record.deviceKey !== identity.deviceKey) { say("Este navegador ya tiene un perfil de otro usuario: no se reemplaza."); return; }
        const key = await unlockLocalVault(record, secret);
        const scopeRes = await api("POST", "/api/offline/scope", { device_key: deviceKey, machine_codes: [machine] });
        if (scopeRes.status !== 200) { say(scopeRes.status === 403 ? "No hay una concesión de piloto para este usuario y máquina." : "No se obtuvo el alcance firmado (" + scopeRes.status + ")."); return; }
        const envelope = scopeRes.json as { public_key_b64url: string };
        await storeOfflineScope(key, identity, envelope, envelope.public_key_b64url);
        const granted = ((scopeRes.json as { payload?: { form_scopes?: { machine_code: string; form_code: string; operation: string }[] } }).payload?.form_scopes ?? [])
            .filter(x => x.machine_code === machine && FORMS_RE.test(x.form_code) && QUALITY_OPERATIONS.has(x.operation));
        if (granted.length === 0) { say("El alcance firmado no incluye formularios de Calidad para esta máquina."); return; }
        let stored = 0;
        for (const item of granted) {
            const pkgRes = await api("POST", "/api/offline/quality-package", { device_key: deviceKey, machine_code: machine, form_code: item.form_code, signed_scope: envelope });
            if (pkgRes.status !== 200) { say("No se obtuvo la definición firmada de " + item.form_code + " (" + pkgRes.status + "). Ya guardadas: " + stored + "."); return; }
            await storeQualityPackage(key, identity, pkgRes.json);
            stored += 1;
        }
        await showUnlock();
        say("Dispositivo preparado: perfil local, alcance firmado y " + stored + " definición(es) sintética(s) guardados cifrados. Ahora desbloquee con su frase offline.");
    } catch (error) {
        say(error instanceof VaultError && error.reason === "weak_passphrase" ? "Frase local débil: use al menos 16 caracteres." : "No se pudo preparar el dispositivo. No se guardó nada incompleto.");
    }
}

let unlockBound = false;
async function showUnlock(): Promise<void> {
    if (!unlockForm) return;
    let record;
    try { record = await readLocalProfile(); } catch { say("No es posible leer el perfil local."); return; }
    if (!record) { say("No hay perfil local preparado en este navegador: inicie sesión y prepare el dispositivo."); return; }
    let deviceKey: string | null = null;
    try { deviceKey = localStorage.getItem(DEVICE_KEY_STORAGE); } catch { /* fail closed */ }
    if (!deviceKey || deviceKey.toLowerCase() !== record.deviceKey) { say("El perfil no corresponde a este navegador. No se desbloqueará."); return; }
    say("Perfil local encontrado. Ingrese su frase offline y confirme el uso de datos sintéticos.");
    unlockForm.hidden = false;
    if (unlockBound) return;
    unlockBound = true;
    unlockForm.addEventListener("submit", (event: SubmitEvent) => { event.preventDefault(); void unlock(); });
}

async function unlock(): Promise<void> {
    if (!secretInput || !confirmBox || !workspace || !select || !newButton || !unlockForm) return;
    const secret = secretInput.value; secretInput.value = "";
    if (!confirmBox.checked) { say("Confirme que usará únicamente datos sintéticos."); return; }
    try {
        const record = await readLocalProfile();
        if (!record) { say("No hay perfil local."); return; }
        const key = await unlockLocalVault(record, secret);
        const identity = { ownerId: record.ownerId, deviceKey: record.deviceKey };
        const scope = await readOfflineScope(key, identity);
        if (!scope) { say("No hay alcance firmado local."); return; }
        const renewal = await readRenewalStatus(key, identity);
        if (renewal?.status === "revocation_known" || renewal?.status === "unreadable") { say("El alcance local no está vigente o no se puede confirmar. El laboratorio permanece bloqueado."); return; }
        const packages: VerifiedQualityDefinition[] = [];
        for (const item of scope.envelope.payload.form_scopes) {
            if (!QUALITY_OPERATIONS.has(item.operation) || !FORMS_RE.test(item.form_code)) continue;
            const pkg = await readQualityPackage(key, identity, scope, item.machine_code, item.form_code);
            if (pkg && isLabEligible(pkg.envelope.payload.definition)) packages.push(pkg);
        }
        packages.sort((a, b) => a.envelope.payload.form_code.localeCompare(b.envelope.payload.form_code) || a.envelope.payload.machine_code.localeCompare(b.envelope.payload.machine_code));
        session = { key, identity, scope, packages };
        select.replaceChildren();
        packages.forEach((p, i) => { const o = document.createElement("option"); o.value = String(i); o.textContent = describe(p); select.appendChild(o); });
        newButton.disabled = packages.length === 0;
        unlockForm.hidden = true; workspace.hidden = false;
        await refreshBobbins();
        await refresh();
        if (session) say(packages.length === 0 ? "No hay definiciones sintéticas editables." : "Laboratorio desbloqueado (perfil original). Datos sintéticos; nada se envía sin su acción.");
    } catch { say("No fue posible desbloquear o validar. El laboratorio permanece bloqueado."); }
}

async function start(): Promise<void> {
    if (!status || !unlockForm || !secretInput || !confirmBox || !workspace || !select || !newButton || !lockButton || !editor) return;
    void registerShell();
    void cacheSelf();
    if (modeLine) modeLine.textContent = ONLINE_OK ? "API QA del mismo origen (cookie de sesión real, sin cabeceras de identidad)." : "Origen no seguro: la sincronización no está disponible. La captura y los pendientes funcionan sin conexión.";
    if (syncButton) syncButton.disabled = !ONLINE_OK;
    if (!window.isSecureContext) { say("Se requiere un contexto seguro."); return; }
    loginForm?.addEventListener("submit", (event: SubmitEvent) => { event.preventDefault(); void doLogin(); });
    logoutButton?.addEventListener("click", () => { void doLogout(); });
    prepareForm?.addEventListener("submit", (event: SubmitEvent) => { event.preventDefault(); void prepareDevice(); });
    newButton.addEventListener("click", () => {
        if (!session) return;
        const pkg = session.packages[Number(select.value)];
        if (!pkg) return;
        let bobbin: BobbinContext | null = null;
        if (byBobbin(pkg, session.scope)) {
            const wanted = bobbinSelect?.value ?? "";
            bobbin = bobbinsOfMachine.find(b => b.bobbin_id === wanted) ?? null;
            if (!bobbin) { say("Este formulario es por bobina: prepare (en línea) y seleccione una bobina antes de crear el borrador."); return; }
        }
        editing = { id: crypto.randomUUID(), revision: null, pkg, readOnly: false, bobbin };
        renderEditor(editing, {}, "Nuevo borrador (aún sin guardar).");
        say("Nuevo borrador (aún sin guardar).");
    });
    select.addEventListener("change", () => { void refreshBobbins(); });
    bobbinPrepare?.addEventListener("click", () => { void prepareBobbin(); });
    lockButton.addEventListener("click", () => lockAll("Laboratorio bloqueado. La clave se descartó de la memoria."));
    editor.addEventListener("submit", (event: SubmitEvent) => { event.preventDefault(); void save(); });
    queueButton?.addEventListener("click", () => { void makePending(); });
    syncButton?.addEventListener("click", () => { void syncOnce(); });
    clockButton?.addEventListener("click", () => { clockOffset += 60_000; say("Reloj simulado avanzado 60 s (solo afecta a los tiempos de espera del laboratorio)."); });
    await showUnlock();
    await refreshAuth();   // offline: reports "sin conexión" and leaves everything else working
}

void start();
