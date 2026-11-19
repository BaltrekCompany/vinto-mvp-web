/**
 * OFF-04.1 LABORATORY page runtime (bundled only when OFFLINE_DRAFT_LAB=1; absent from default builds).
 * No network access of any kind, no send queue, no sync. DOM is built with textContent only.
 * The decrypting key lives in this closure until "Bloquear"/reload and is never persisted.
 */
import { readLocalProfile } from "./offline-profile-store.ts";
import { unlockLocalVault } from "./offline-vault.ts";
import { readOfflineScope, type VerifiedLocalScope } from "./offline-scope-store.ts";
import { readQualityPackage } from "./offline-quality-store.ts";
import { readRenewalStatus } from "./offline-renewal.ts";
import type { VerifiedQualityDefinition, QualityField } from "./offline-quality-verify.ts";
import { DEVICE_KEY_STORAGE } from "./device";
import { editableFields, isCalculated, isLabEligible, draftMatchesDefinition, type DraftValues } from "./offline-draft-schema.ts";
import { DraftError, listQualityDrafts, loadQualityDraft, saveQualityDraft } from "./offline-draft-store.ts";

const $ = <T>(id: string) => document.getElementById(id) as unknown as T | null;
type Control = { value: string; dataset: DOMStringMap };
const status = $<HTMLParagraphElement>("lab-status");
const unlockForm = $<HTMLFormElement>("lab-unlock-form");
const secretInput = $<HTMLInputElement>("lab-unlock-secret");
const confirmBox = $<HTMLInputElement>("lab-confirm-synthetic");
const workspace = $<HTMLElement>("lab-workspace");
const select = $<HTMLSelectElement>("lab-package-select");
const newButton = $<HTMLButtonElement>("lab-new-draft");
const lockButton = $<HTMLButtonElement>("lab-lock");
const draftList = $<HTMLUListElement>("lab-drafts");
const editor = $<HTMLFormElement>("lab-editor");
const fieldsBox = $<HTMLDivElement>("lab-fields");
const info = $<HTMLParagraphElement>("lab-info");
const title = $<HTMLHeadingElement>("lab-editor-title");
const reloadButton = $<HTMLButtonElement>("lab-reload");

type Session = { key: CryptoKey; identity: { ownerId: string; deviceKey: string }; scope: VerifiedLocalScope; packages: VerifiedQualityDefinition[] };
type Editing = { id: string; revision: number | null; pkg: VerifiedQualityDefinition; readOnly: boolean };
let session: Session | null = null;
let editing: Editing | null = null;

const say = (text: string) => { if (status) status.textContent = text; };
const ISSUE_TEXT: Record<string, string> = {
    required: "obligatorio", type: "valor no válido para el tipo", option: "no es una opción permitida",
    unknown: "campo desconocido", calculated: "campo calculado: no editable", too_long: "demasiado largo",
};

// Best effort: let the public shell serve this page offline after a restart (separate lab cache).
async function cacheSelf(): Promise<void> {
    try {
        if (!("caches" in window) || !navigator.onLine) return;
        const cache = await caches.open("vinto-off04lab-v1");
        await cache.addAll(["/offline-lab.html", "/offline-draft-lab.js"]);
    } catch { /* offline or blocked: the lab simply is not available offline */ }
}

function lockAll(message: string): void {
    session = null; editing = null;
    if (workspace) workspace.hidden = true;
    if (editor) editor.hidden = true;
    if (unlockForm) unlockForm.hidden = false;
    say(message);
}

function describe(pkg: VerifiedQualityDefinition): string {
    const p = pkg.envelope.payload;
    return p.machine_code + " · " + p.definition.form_name + " · " + p.form_code + " (v" + p.form_version + ")";
}

function inputFor(field: QualityField, pkg: VerifiedQualityDefinition, value: string | boolean | undefined, readOnly: boolean): HTMLElement {
    const calculated = isCalculated(field);
    let el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    if (field.options.length > 0 || field.value_type === "boolean") {
        el = document.createElement("select");
        const blank = document.createElement("option"); blank.value = ""; blank.textContent = "—"; el.appendChild(blank);
        const choices = field.value_type === "boolean"
            ? [{ k: "true", l: "Sí" }, { k: "false", l: "No" }]
            : [...field.options].sort((a, b) => a.display_order - b.display_order).map(o => ({ k: o.option_key, l: o.label }));
        for (const c of choices) { const o = document.createElement("option"); o.value = c.k; o.textContent = c.l; el.appendChild(o); }
        el.value = value === undefined ? "" : String(value);
    } else if (field.value_type === "textarea") {
        el = document.createElement("textarea"); el.rows = 3; el.value = typeof value === "string" ? value : "";
    } else {
        el = document.createElement("input");
        el.type = field.value_type === "date" ? "date" : field.value_type === "time" ? "time" : "text";
        if (field.value_type === "decimal") el.inputMode = "decimal";
        if (field.value_type === "integer") el.inputMode = "numeric";
        el.value = typeof value === "string" ? value : "";
    }
    el.id = "f-" + field.key; el.dataset.key = field.key;
    if (calculated) { el.disabled = true; el.dataset.calculated = "1"; el.value = ""; }
    else if (readOnly) el.disabled = true;
    void pkg;
    return el as unknown as HTMLElement;
}

function renderEditor(e: Editing, values: DraftValues, createdLocal: string | null): void {
    if (!editor || !fieldsBox || !info || !title) return;
    const def = e.pkg.envelope.payload.definition;
    title.textContent = describe(e.pkg) + (e.revision === null ? " — nuevo borrador" : " — revisión " + e.revision);
    info.textContent = "Estado: draft · fecha local informativa: " + (createdLocal ?? new Date().toISOString()) +
        " · No sincronizado ni enviado." + (e.readOnly ? " SOLO LECTURA: la definición cambió." : "");
    fieldsBox.replaceChildren();
    for (const field of [...def.fields].sort((a, b) => a.display_order - b.display_order)) {
        const wrap = document.createElement("label");
        const label = document.createElement("span");
        label.textContent = field.label + (field.required && !isCalculated(field) ? " *" : "") +
            (isCalculated(field) ? " (calculado por backend; no editable)" : "") + (field.unit ? " [" + field.unit + "]" : "");
        wrap.appendChild(label);
        wrap.appendChild(inputFor(field, e.pkg, values[field.key], e.readOnly));
        const err = document.createElement("span"); err.className = "err"; err.id = "err-" + field.key; wrap.appendChild(err);
        fieldsBox.appendChild(wrap);
    }
    const save = $<HTMLButtonElement>("lab-save"); if (save) save.disabled = e.readOnly;
    if (reloadButton) reloadButton.hidden = true;
    editor.hidden = false;
}

function collect(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const el of Array.from(fieldsBox?.querySelectorAll("[data-key]") ?? []) as unknown as Control[]) {
        if (el.dataset.calculated === "1") continue;
        const key = el.dataset.key as string;
        const field = editing?.pkg.envelope.payload.definition.fields.find(f => f.key === key);
        if (field?.value_type === "boolean") { if (el.value === "true") out[key] = true; else if (el.value === "false") out[key] = false; }
        else out[key] = el.value;
    }
    return out;
}

async function refreshDrafts(): Promise<void> {
    if (!session || !draftList) return;
    draftList.replaceChildren();
    let items;
    try { items = await listQualityDrafts(session.key, session.identity); }
    catch { say("No se pudo leer el almacenamiento de borradores. No se muestra nada."); return; }
    if (items.length === 0) { const li = document.createElement("li"); li.textContent = "Sin borradores en este navegador."; draftList.appendChild(li); }
    for (const item of items) {
        const li = document.createElement("li");
        if (item.corrupt) { li.textContent = "Borrador " + item.id.slice(0, 8) + " ilegible (" + item.reason + "): no se modifica."; li.dataset.corrupt = "1"; }
        else {
            const open = document.createElement("button"); open.type = "button"; open.className = "open"; open.dataset.draftId = item.id;
            open.textContent = "Abrir " + item.machineCode + " · " + item.formCode + " v" + item.formVersion + " · rev " + item.revision + " · " + item.updatedLocal;
            open.addEventListener("click", () => { void openDraft(item.id); });
            li.appendChild(open);
        }
        draftList.appendChild(li);
    }
}

async function openDraft(id: string): Promise<void> {
    if (!session) return;
    try {
        const loaded = await loadQualityDraft(session.key, session.identity, id);
        const pkg = session.packages.find(p => draftMatchesDefinition(loaded.payload, p.envelope.payload)) ??
            session.packages.find(p => p.envelope.payload.machine_code === loaded.payload.machine_code && p.envelope.payload.form_code === loaded.payload.form_code);
        if (!pkg) { say("No hay una definición local para este borrador; no se puede editar."); return; }
        editing = { id, revision: loaded.revision, pkg, readOnly: !draftMatchesDefinition(loaded.payload, pkg.envelope.payload) };
        renderEditor(editing, loaded.payload.values, loaded.payload.created_local);
        say("Borrador cargado (revisión " + loaded.revision + ")." + (editing.readOnly ? " La definición cambió: solo lectura." : ""));
    } catch (error) {
        say(error instanceof DraftError && error.reason === "locked" ? "La clave local no abre este borrador." : "Borrador ilegible o alterado: no se muestra ni se modifica.");
    }
}

function showIssues(issues: readonly { key: string; code: string }[]): void {
    for (const el of Array.from(fieldsBox?.querySelectorAll<HTMLElement>(".err") ?? [])) el.textContent = "";
    for (const issue of issues) { const el = document.getElementById("err-" + issue.key); if (el) el.textContent = ISSUE_TEXT[issue.code] ?? issue.code; }
}

async function save(): Promise<void> {
    if (!session || !editing || editing.readOnly) return;
    showIssues([]);
    try {
        const result = await saveQualityDraft(session.key, session.identity, { scope: session.scope, pkg: editing.pkg },
            { id: editing.id, values: collect(), expectedRevision: editing.revision });
        editing = { ...editing, revision: result.revision };
        if (title) title.textContent = describe(editing.pkg) + " — revisión " + result.revision;
        showIssues(result.missingRequired);
        say("Borrador guardado cifrado en este navegador (revisión " + result.revision + "). Estado: draft · " +
            (result.complete ? "completo" : "incompleto: faltan " + result.missingRequired.length + " obligatorio(s)") + ". No se envió nada.");
        await refreshDrafts();
    } catch (error) {
        if (!(error instanceof DraftError)) { say("NO se guardó el borrador."); return; }
        if (error.reason === "invalid") { showIssues(error.issues); say("NO se guardó: corrija los campos marcados."); }
        else if (error.reason === "conflict") { say("NO se guardó: otra pestaña guardó una versión más reciente. No se sobrescribió nada; use «Cargar versión guardada»."); if (reloadButton) reloadButton.hidden = false; }
        else if (error.reason === "quota") say("NO se guardó: el almacenamiento del navegador está lleno. Libere espacio y reintente.");
        else if (error.reason === "stale_definition") say("NO se guardó: la definición cambió; este borrador es de solo lectura.");
        else say("NO se guardó el borrador (" + error.reason + "). Nada fue enviado.");
    }
}

async function start(): Promise<void> {
    if (!status || !unlockForm || !secretInput || !confirmBox || !workspace || !select || !newButton || !lockButton || !editor) return;
    void cacheSelf();
    if (!window.isSecureContext) { say("Se requiere un contexto seguro."); return; }
    let record;
    try { record = await readLocalProfile(); } catch { say("No es posible leer el perfil local."); return; }
    if (!record) { say("No hay perfil local preparado en este navegador."); return; }
    let deviceKey: string | null = null;
    try { deviceKey = localStorage.getItem(DEVICE_KEY_STORAGE); } catch { /* fail closed */ }
    if (!deviceKey || deviceKey.toLowerCase() !== record.deviceKey) { say("El perfil no corresponde a este navegador. No se desbloqueará."); return; }
    say("Perfil local encontrado. Ingrese su frase offline y confirme que son datos sintéticos.");
    unlockForm.hidden = false;
    unlockForm.addEventListener("submit", async (event: SubmitEvent) => {
        event.preventDefault();
        const secret = secretInput.value; secretInput.value = "";
        if (!confirmBox.checked) { say("Confirme que usará únicamente datos sintéticos."); return; }
        say("Verificando…");
        try {
            const key = await unlockLocalVault(record, secret);
            const identity = { ownerId: record.ownerId, deviceKey: record.deviceKey };
            const scope = await readOfflineScope(key, identity);
            if (!scope) { say("No hay alcance firmado local."); return; }
            const renewal = await readRenewalStatus(key, identity);
            if (renewal?.status === "revocation_known" || renewal?.status === "unreadable") {
                say("El alcance local no está vigente o su estado no se puede confirmar. El laboratorio permanece bloqueado."); return;
            }
            const packages: VerifiedQualityDefinition[] = [];
            let skipped = 0;
            for (const item of scope.envelope.payload.form_scopes) {
                if (item.operation !== "quality_machine_capture" || !/^VINTO-P1-(18|22|26|27)$/.test(item.form_code)) continue;
                const pkg = await readQualityPackage(key, identity, scope, item.machine_code, item.form_code);
                if (!pkg) continue;
                if (isLabEligible(pkg.envelope.payload.definition)) packages.push(pkg); else skipped++;
            }
            session = { key, identity, scope, packages };
            select.replaceChildren();
            packages.forEach((p, i) => { const o = document.createElement("option"); o.value = String(i); o.textContent = describe(p); select.appendChild(o); });
            newButton.disabled = packages.length === 0;
            unlockForm.hidden = true; workspace.hidden = false;
            await refreshDrafts();
            say(packages.length === 0
                ? "No hay definiciones sintéticas editables" + (skipped ? " (" + skipped + " definición(es) real(es) no se editan en el laboratorio)." : ".")
                : "Laboratorio desbloqueado. Datos sintéticos únicamente; nada se envía.");
        } catch { say("No fue posible desbloquear o validar. El laboratorio permanece bloqueado."); }
    });
    newButton.addEventListener("click", () => {
        if (!session) return;
        const pkg = session.packages[Number(select.value)];
        if (!pkg) return;
        editing = { id: crypto.randomUUID(), revision: null, pkg, readOnly: false };
        renderEditor(editing, {}, null);
        say("Nuevo borrador (aún sin guardar).");
    });
    lockButton.addEventListener("click", () => lockAll("Laboratorio bloqueado. La clave se descartó de la memoria."));
    editor.addEventListener("submit", (event: SubmitEvent) => { event.preventDefault(); void save(); });
    reloadButton?.addEventListener("click", () => { if (editing) void openDraft(editing.id); });
    void editableFields;
}

void start();
