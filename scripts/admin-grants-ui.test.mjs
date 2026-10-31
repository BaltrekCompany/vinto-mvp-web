// node --test scripts/admin-grants-ui.test.mjs
// Interfaz de «Máquinas y formularios» (MF-13-01C.3): renderiza los COMPONENTES reales (React + react-dom/server) en cada estado, sin navegador ni red.
// Los TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio que se borra al terminar. Los hooks/efectos no se ejecutan en el render del
// servidor: la lógica está en lib/vinto/admin-grants.ts y se prueba en scripts/admin-grants.test.mjs. El cuerpo del diálogo se renderiza con ranuras simples (el portal de Radix no se monta en el servidor).
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-admin-grants-ui-test-${process.pid}`);

const aliasPlugin = {
  name: "at-alias", enforce: "pre",
  resolveId(source) {
    if (!source.startsWith("@/")) return null;
    const base = `${root}/${source.slice(2)}`;
    for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (existsSync(candidate)) return candidate;
    return null;
  },
};

async function bundle(entry, name) {
  const output = await build({
    configFile: false, root, logLevel: "error", mode: "production", plugins: [aliasPlugin], oxc: { jsx: { runtime: "automatic" } },
    build: { write: false, ssr: join(root, entry), minify: false, target: "node22", rollupOptions: { output: { format: "es" } } },
  });
  const chunk = (Array.isArray(output) ? output[0] : output).output.find((item) => item.type === "chunk");
  const file = join(workDir, `${name}.mjs`);
  writeFileSync(file, chunk.code);
  return import(pathToFileURL(file).href);
}

let parts, consoleModule, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [parts, consoleModule] = await Promise.all([bundle("components/vinto/admin/admin-grants-parts.tsx", "parts"), bundle("components/vinto/admin/admin-console.tsx", "console")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const html = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));
const noop = () => {};
const count = (text, needle) => text.split(needle).length - 1;
const U1 = "11111111-1111-4111-8111-111111111111", ADMIN = "99999999-9999-4999-8999-999999999999";
let counter = 0;
const gid = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, "0")}`;

const form = (code, o = {}) => ({ code, name: `Nombre ${code}`, area: "production", active: true, effective_version: 2, published: true, capture_policies: ["production_central"], offered: true, enabled_for_capture: true, ...o });
const P101 = form("VINTO-P1-01", { effective_version: 4 }), P103 = form("VINTO-P1-03", { effective_version: 1, capture_policies: [], enabled_for_capture: false }), P106 = form("VINTO-P1-06");
const P110 = form("VINTO-P1-10", { effective_version: 3 }), P131 = form("VINTO-P1-31");
const machine = (code, forms, o = {}) => ({ code, name: code, active: true, forms, ...o });
const sector = (code, machines, o = {}) => ({ code, name: code[0] + code.slice(1).toLowerCase(), active: true, operational: true, machines, ...o });
const FIVE = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"];
const CATALOG = { sectors: [
  sector("BOBINAS", [machine("MP1", [P101, P103, P106]), machine("MP3", [P101, P103, P106, P131])]),
  sector("REBOBINADO", FIVE.map((code) => machine(code, [P110]))),
] };
const FORMS = { forms: [
  { code: "VINTO-P1-01", name: "Nombre VINTO-P1-01", area: "production", active: true, published: true, effective_version: 4, capture_policies: ["production_central"], enabled_for_capture: true,
    machines: [{ code: "MP1", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }, { code: "MP3", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }] },
  { code: "VINTO-P1-31", name: "Consumo de químicos", area: "production", active: true, published: true, effective_version: 2, capture_policies: ["production_central"], enabled_for_capture: true, machines: [{ code: "MP3", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }] },
  { code: "VINTO-P1-99", name: "Borrador", area: "production", active: true, published: false, effective_version: null, capture_policies: [], enabled_for_capture: false, machines: [] },
] };
const status = (o = {}) => ({ published_version: 2, offered: true, enabled_for_capture: true, capture_policies: ["production_central"], ...o });
const person = (name = "Admin DEV") => ({ id: ADMIN, display_name: name });
const row = (machineCode, formCode, o = {}) => ({ id: gid(), state: "active", machine: { code: machineCode, name: machineCode, sector_code: "BOBINAS" }, form: { code: formCode, name: `Nombre ${formCode}`, area: "production" },
  granted_at: "2026-10-31T04:20:59.123456+00:00", granted_by: person(), revoked_at: null, revoked_by: null, catalog: status(), ...o });
const revokedRow = (machineCode, formCode, o = {}) => row(machineCode, formCode, { state: "revoked", revoked_at: "2026-10-31T05:00:00+00:00", revoked_by: person("Otro Admin"), ...o });
const grants = (list, o = {}) => ({ user_id: U1, total: list.length, truncated: false, grants: list, ...o });
const detail = (o = {}) => ({ id: U1, username: "dev.operacion", display_name: "Operación DEV", active: true, profiles: [{ code: "OPERACION", name: "Operación" }], permissions: [], sectors: [{ code: "BOBINAS", name: "Bobinas", active: true, operational: true }], ...o });
const ready = (data, refreshing = false) => ({ status: "ready", data, refreshing });
const err = (kind) => ({ status: "error", kind, refreshing: false });
const USER = { id: U1, username: "dev.operacion", display_name: "Operación DEV", active: true, profiles: ["OPERACION"], sectors: [] };
const panel = (o = {}) => ({ detail: ready(detail()), catalog: ready(CATALOG), forms: ready(FORMS), grants: ready(grants([row("MP3", "VINTO-P1-01")])), history: ready(grants([revokedRow("MP1", "VINTO-P1-01"), row("MP3", "VINTO-P1-01")])),
  machineCode: null, onSelectMachine: noop, block: null, uncertain: false, feedback: null, onOpen: noop, onRetryDetail: noop, onRetryCatalog: noop, onRetryForms: noop, onRetryGrants: noop, onRetryHistory: noop, ...o });
const section = (o) => html(parts.AdminGrantsSection, { user: USER, ...panel(o) });
const button = (text, label) => (text.match(new RegExp(`<button[^>]*aria-label="${label}"[^>]*>`)) ?? [""])[0];
const has = (text, label) => button(text, label) !== "";
const isDisabled = (text, label) => /\sdisabled(=""|\s|>)/.test(button(text, label));
const actions = (text) => [...text.matchAll(/<button[^>]*aria-label="((?:Conceder|Revocar) [A-Z0-9-]+ en [A-Z0-9_]+)"[^>]*>/g)].map((m) => ({ label: m[1], disabled: /\sdisabled(=""|\s|>)/.test(m[0]) }));
const rowOf = (text, code) => (text.match(new RegExp(`<li[^>]*data-form="${code}".*?</li>`, "s")) ?? [""])[0];

test("loading and error states of each read: skeleton while loading, a specific message with retry on error; no machines until the catalogue is ready", () => {
  const loading = section({ catalog: { status: "loading" }, grants: { status: "loading" }, detail: { status: "loading" }, history: { status: "loading" } });
  for (const expected of ["Consultando el usuario…", "Consultando el catálogo de máquinas y formularios…", "Consultando las concesiones…", "Consultando el historial…"]) assert.ok(loading.includes(expected), expected);
  assert.ok(!loading.includes("Seleccionar máquina") && actions(loading).length === 0, "sin catálogo no hay máquinas ni acciones");
  const errored = section({ catalog: err("unavailable"), grants: err("unavailable"), history: err("unavailable") });
  assert.ok(errored.includes("No se pudo cargar el catálogo de máquinas") && errored.includes("No se pudieron cargar las concesiones") && errored.includes("No se pudo cargar el historial"));
  assert.equal(count(errored, "Reintentar"), 3, "cada lectura fallida ofrece reintentar");
  assert.ok(errored.includes("No se pudo conectar con el servidor"));
});

test("ready: machines are grouped by sector with how many forms each offers and how many the user holds; nothing is selected by default", () => {
  const text = section();
  assert.ok(text.includes("Máquinas y formularios") && text.includes('aria-label="Máquinas por sector"'));
  for (const expected of ["Bobinas", "Rebobinado", ...["MP1", "MP3", ...FIVE].map((code) => `aria-label="Seleccionar máquina ${code}"`)]) assert.ok(text.includes(expected), expected);
  assert.ok(text.includes("3 ofrecidos · 0 concedidos") && text.includes("4 ofrecidos · 1 concedidos"), "contadores por máquina: solo MP3 tiene una concesión");
  assert.ok(text.includes("Selecciona una máquina para ver sus formularios"));
  assert.equal(count(text, 'aria-pressed="true"'), 0);
  assert.equal(actions(text).length, 0, "sin máquina seleccionada no hay acciones");
  assert.equal(count(section({ machineCode: "MP1" }), 'aria-pressed="true"'), 1);
});

test("P1-01 is independent on MP1 and MP3: the same form is grantable on MP1 and revocable on MP3", () => {
  const mp1 = section({ machineCode: "MP1" }), mp3 = section({ machineCode: "MP3" });
  assert.deepEqual(actions(mp1).filter((a) => a.label.includes("VINTO-P1-01")).map((a) => a.label), ["Conceder VINTO-P1-01 en MP1"]);
  assert.deepEqual(actions(mp3).filter((a) => a.label.includes("VINTO-P1-01")).map((a) => a.label), ["Revocar VINTO-P1-01 en MP3"]);
  assert.ok(rowOf(mp1, "VINTO-P1-01").includes("No concedido") && rowOf(mp3, "VINTO-P1-01").includes("Concedido"));
  assert.ok(rowOf(mp1, "VINTO-P1-01").includes("Publicado v4"));
  assert.ok(mp1.includes('aria-label="Formularios de MP1"') && !mp1.includes('aria-label="Formularios de MP3"'), "se muestra solo la máquina seleccionada");
});

test("P1-10 appears on each of the five rebobinadoras when the catalogue offers it, P1-31 only on MP3, and unoffered published forms are listed apart and cannot be granted", () => {
  for (const code of FIVE) {
    const text = section({ machineCode: code });
    assert.ok(rowOf(text, "VINTO-P1-10").includes("Publicado v3"), code);
    assert.ok(has(text, `Conceder VINTO-P1-10 en ${code}`), code);
  }
  const mp1 = section({ machineCode: "MP1" }), mp3 = section({ machineCode: "MP3" });
  assert.equal(rowOf(mp1, "VINTO-P1-31"), "", "P1-31 no se ofrece en MP1");
  assert.ok(rowOf(mp3, "VINTO-P1-31").includes("Publicado v2"));
  assert.ok(mp1.includes("No ofrecidos a esta máquina (2)") && mp1.includes("Consumo de químicos") && mp1.includes("su versión vigente no lo vincula a esta máquina") && mp1.includes("Sin versión publicada."));
  assert.ok(!has(mp1, "Conceder VINTO-P1-31 en MP1") && !has(mp1, "Conceder VINTO-P1-99 en MP1"), "un par no ofrecido nunca se puede conceder");
  assert.ok(mp3.includes("No ofrecidos a esta máquina (1)"), "en MP3 solo queda el borrador sin publicar");
});

test("published, offered, enabled for capture and granted are shown as separate facts; a form with no central policy says it may use another route; nothing is called effective access", () => {
  const text = section({ machineCode: "MP1", grants: ready(grants([row("MP1", "VINTO-P1-06")])) });
  const p106 = rowOf(text, "VINTO-P1-06"), p103 = rowOf(text, "VINTO-P1-03");
  for (const expected of ["Publicado v2", "Ofrecido a la máquina", "Habilitado: Captura central de producción", ">Concedido<"]) assert.ok(p106.includes(expected), expected);
  for (const expected of ["Publicado v1", "Ofrecido a la máquina", "Sin política de captura central", "No concedido", "no significa que el formulario no exista", "otra ruta especializada"]) assert.ok(p103.includes(expected), expected);
  assert.ok(has(text, "Conceder VINTO-P1-03 en MP1"), "sin política de captura central igualmente se puede conceder");
  assert.ok(!/efectiv/i.test(p106 + p103), "ninguna fila habla de acceso efectivo");
  assert.ok(text.includes("todavía no se aplican a las capturas") && text.includes('data-notice="not-effective"'));
});

test("an inert grant (pair no longer offered) is marked inert, can be revoked and cannot be granted again", () => {
  const orphan = row("MP1", "VINTO-P1-05", { form: { code: "VINTO-P1-05", name: "Tubetes", area: "production" }, catalog: status({ offered: false, enabled_for_capture: false }) });
  const text = section({ machineCode: "MP1", grants: ready(grants([orphan])) });
  const item = rowOf(text, "VINTO-P1-05");
  for (const expected of ["Concedido · inerte", "No ofrecido hoy", "Concesión inerte: el catálogo vigente ya no ofrece este formulario a la máquina."]) assert.ok(item.includes(expected), expected);
  assert.ok(has(text, "Revocar VINTO-P1-05 en MP1") && !isDisabled(text, "Revocar VINTO-P1-05 en MP1"));
  assert.ok(!has(text, "Conceder VINTO-P1-05 en MP1"));
});

test("warnings: the user lacks the sector (not granted automatically), the sector is not operational, the user is inactive; the grant row says why it is inert", () => {
  const noSector = section({ machineCode: "MP1", detail: ready(detail({ sectors: [] })), grants: ready(grants([row("MP1", "VINTO-P1-01")])) });
  assert.ok(noSector.includes("El usuario no tiene concedido el sector de esta máquina") && noSector.includes("NO se concede automáticamente"));
  assert.ok(rowOf(noSector, "VINTO-P1-01").includes("el usuario no tiene concedido el sector de la máquina") && rowOf(noSector, "VINTO-P1-01").includes("Concedido · inerte"));
  assert.ok(has(noSector, "Conceder VINTO-P1-03 en MP1"), "se puede conceder igualmente: el sector no se concede solo");
  const inactive = section({ machineCode: "MP1", detail: ready(detail({ active: false })), grants: ready(grants([row("MP1", "VINTO-P1-01")])) });
  assert.ok(inactive.includes("El usuario está inactivo: las concesiones quedan inertes.") && rowOf(inactive, "VINTO-P1-01").includes("el usuario está inactivo"));
  const unready = { ...CATALOG, sectors: CATALOG.sectors.map((s) => (s.code === "REBOBINADO" ? { ...s, operational: false, machines: s.machines.map((m) => ({ ...m, forms: m.forms.map((f) => ({ ...f, enabled_for_capture: false })) })) } : s)) };
  const notOperational = section({ machineCode: "COPASA", catalog: ready(unready), detail: ready(detail({ sectors: [{ code: "REBOBINADO", name: "Rebobinado", active: true, operational: false }] })) });
  assert.ok(notOperational.includes("El sector REBOBINADO no está operativo: las concesiones de sus máquinas quedan inertes."));
});

test("actions are locked on a 403/unauthorised origin, on an uncertain result and while re-reading; unlocked, every offered or held pair has its action", () => {
  const open = actions(section({ machineCode: "MP3" }));
  assert.ok(open.length >= 4 && open.every((a) => !a.disabled), "sin bloqueo las acciones están habilitadas");
  for (const block of ["forbidden", "origin"]) {
    const text = section({ machineCode: "MP3", block });
    assert.ok(actions(text).length > 0 && actions(text).every((a) => a.disabled), `${block}: todas deshabilitadas`);
    assert.ok(text.includes(block === "forbidden" ? "Sin permiso" : "Origen no autorizado"));
  }
  const uncertain = section({ machineCode: "MP3", uncertain: true });
  assert.ok(actions(uncertain).every((a) => a.disabled) && uncertain.includes("No se pudo confirmar el último cambio") && uncertain.includes("Consultar de nuevo"));
  assert.ok(uncertain.includes("no se asume que el cambio se aplicó ni que no se aplicó"));
  const rereading = section({ machineCode: "MP3", grants: ready(grants([row("MP3", "VINTO-P1-01")]), true) });
  assert.ok(actions(rereading).every((a) => a.disabled), "mientras se relee tras un cambio no se permite otra acción");
  const loadingDetail = section({ machineCode: "MP3", detail: { status: "loading" } });
  assert.ok(actions(loadingDetail).every((a) => a.disabled), "sin el detalle del usuario no se conoce la inercia: acciones bloqueadas");
});

test("the last result is shown as a status line, and a form catalogue failure does not block the rest", () => {
  const text = section({ machineCode: "MP3", feedback: { tone: "ok", text: "Acceso concedido a Operación DEV: VINTO-P1-02 en MP3." } });
  assert.ok(text.includes('role="status"') && text.includes("Acceso concedido a Operación DEV: VINTO-P1-02 en MP3."));
  const noForms = section({ machineCode: "MP3", forms: err("unavailable") });
  assert.ok(noForms.includes("No se pudo consultar el catálogo de formularios") && has(noForms, "Conceder VINTO-P1-02 en MP3") === false);
  assert.ok(actions(noForms).some((a) => !a.disabled), "las demás acciones siguen disponibles");
});

test("history: machine, form, grant date and administrator, revocation date and administrator, state; truncation is announced; empty and error states", () => {
  const text = section();
  const history = text.slice(text.indexOf('aria-label="Historial de concesiones"'));
  for (const expected of ["Historial de concesiones y revocaciones", "Máquina", "Formulario", "Concedida", "Concedió", "Revocada", "Revocó", "MP1", "MP3", "Revocada</span>", "Activa", "2026-10-31 04:20 UTC", "2026-10-31 05:00 UTC", "Otro Admin", "Admin DEV"]) assert.ok(history.includes(expected), expected);
  assert.ok(!history.includes("<button"), "el historial es de solo lectura: ni borrar ni editar");
  const truncated = section({ history: ready(grants([row("MP3", "VINTO-P1-01")], { total: 420, truncated: true })) });
  assert.ok(truncated.includes("Se muestran las 1 concesiones más recientes de 420") && truncated.includes("no se modifican ni se borran"));
  assert.ok(section({ history: ready(grants([])) }).includes("nunca tuvo concesiones de formularios por máquina"));
  assert.ok(section({ history: err("unavailable") }).includes("No se pudo cargar el historial"));
});

const target = (o = {}) => ({ operation: "grant", userId: U1, userLabel: "Operación DEV", machineCode: "MP1", machineName: "MP1", formCode: "VINTO-P1-01", formName: "Parámetros", offered: true, inert: [], sectorGranted: true, ...o });
const changeOf = (o = {}) => ({ user_id: U1, machine_code: "MP1", form_code: "VINTO-P1-01", operation: "grant", changed: true, active: true, request_id: "admin-machine-form-grant:abc", grant: row("MP1", "VINTO-P1-01"),
  catalog: status(), context: { user_active: true, sector_code: "BOBINAS", sector_granted: true, sector_operational: true }, ...o });
const dialog = (state) => html(parts.GrantDialogBody, { state, onConfirm: noop, onClose: noop, slots: parts.PLAIN_SLOTS });

test("dialog: confirming names user, machine, form and operation, offers Cancelar and the confirm action; submitting disables both and says so", () => {
  const confirming = dialog({ step: "confirming", target: target({ sectorGranted: false, inert: ["sector_missing"] }) });
  for (const expected of ["Conceder acceso a un formulario", "<dt", "Usuario", "Operación DEV", "Máquina", "MP1", "Formulario", "VINTO-P1-01 · Parámetros", "Conceder", "Conceder acceso", "Cancelar", "NO se concede automáticamente", "Concesión inerte", "todavía no se aplican a las capturas"]) assert.ok(confirming.includes(expected), expected);
  assert.ok(!/<button[^>]*\sdisabled=""/.test(confirming), "ningún botón deshabilitado al confirmar");
  const revoking = dialog({ step: "confirming", target: target({ operation: "revoke" }) });
  assert.ok(revoking.includes("Revocar acceso a un formulario") && revoking.includes("Revocar acceso") && revoking.includes("conserva el historial") && revoking.includes("bg-red-700"));
  const submitting = dialog({ step: "submitting", target: target(), token: 1 });
  assert.equal([...submitting.matchAll(/\sdisabled=""/g)].length, 2, "Cancelar y Conceder deshabilitados: sin envíos duplicados ni cierre");
  assert.ok(submitting.includes("Aplicando…"));
  assert.equal(dialog({ step: "closed" }), "", "cerrado no pinta nada");
});

test("dialog: results say applied or unchanged (idempotence), show the audit id, warn about inertness, and each failure explains itself", () => {
  const done = dialog({ step: "done", target: target(), change: changeOf() });
  for (const expected of ["Cambio aplicado", "Acceso concedido a Operación DEV: VINTO-P1-01 en MP1", "Detalle técnico", "admin-machine-form-grant:abc", "Cerrar"]) assert.ok(done.includes(expected), expected);
  const unchanged = dialog({ step: "done", target: target(), change: changeOf({ changed: false, request_id: null }) });
  assert.ok(unchanged.includes("Sin cambios") && unchanged.includes("ya tenía concedido VINTO-P1-01 en MP1. No se modificó nada.") && !unchanged.includes("Detalle técnico"));
  const inert = dialog({ step: "done", target: target(), change: changeOf({ context: { user_active: false, sector_code: "BOBINAS", sector_granted: true, sector_operational: true } }) });
  assert.ok(inert.includes("Concesión inerte: el usuario está inactivo"));
  const revoked = dialog({ step: "done", target: target({ operation: "revoke" }), change: changeOf({ operation: "revoke", active: false, grant: revokedRow("MP1", "VINTO-P1-01") }) });
  assert.ok(revoked.includes("Acceso revocado a Operación DEV") && revoked.includes("se conserva en el historial"));
  const failed = (kind) => dialog({ step: "failed", target: target(), failure: { ok: false, kind, status: 0 } });
  assert.ok(failed("pair_not_offered").includes("El par no se ofrece") && failed("pair_not_offered").includes("No se concedió nada") && failed("pair_not_offered").includes("se vuelve a consultar el catálogo"));
  assert.ok(failed("unavailable").includes("No se pudo confirmar el cambio") && failed("unavailable").includes("El resultado es incierto"));
  assert.ok(failed("forbidden").includes("Sin permiso") && failed("origin").includes("Origen no autorizado"));
  assert.ok(failed("user_not_found").includes("El usuario ya no existe") && failed("machine_not_found").includes("La máquina ya no existe") && failed("form_not_found").includes("El formulario ya no existe"));
  assert.ok(failed("invalid").includes("La solicitud no es válida") && failed("unsupported").includes("formato de la solicitud"));
});

// ---- integración con la consola actual ----

const SECTOR = { code: "BOBINAS", name: "Bobinas", active: true, operational: true };
const viewProps = (o = {}) => ({ user: { id: ADMIN, username: "dev.data", display_name: "Data DEV", profiles: ["DATA_BALTREK"], permissions: ["user.manage"], must_change: false },
  users: ready([{ id: U1, username: "dev.operacion", display_name: "Operación DEV", active: true, profiles: ["OPERACION"], sectors: [SECTOR] }]), catalog: ready([SECTOR]),
  detail: ready({ user_id: U1, username: "dev.operacion", active: true, sectors: [SECTOR] }), query: "", onQuery: noop, selectedId: U1, onSelect: noop, block: null, change: { step: "closed" },
  onOpen: noop, onConfirm: noop, onClose: noop, onRetryUsers: noop, onRetryCatalog: noop, onRetryDetail: noop, onLogout: noop, ...o });

test("the existing console keeps the sector administration intact and adds the new section below, clearly separated; without the panel nothing changes", () => {
  const without = html(consoleModule.AdminConsoleView, viewProps());
  assert.ok(without.includes("Sectores concedidos") && without.includes('aria-label="Conceder acceso a Rebobinado"') === false);
  assert.ok(!without.includes("Máquinas y formularios"), "sin el panel, la consola es la de siempre");
  const withPanel = html(consoleModule.AdminConsoleView, viewProps({ grantsPanel: panel({ machineCode: "MP1" }), grantDialog: { state: { step: "closed" }, onConfirm: noop, onClose: noop } }));
  assert.ok(withPanel.includes("Sectores concedidos") && withPanel.includes("Máquinas y formularios"), "sección A (sectores) y sección B (máquinas y formularios)");
  assert.ok(withPanel.indexOf("Sectores concedidos") < withPanel.indexOf("Máquinas y formularios"));
  assert.ok(withPanel.includes('aria-label="Revocar acceso a Bobinas"'), "las acciones de sector siguen ahí");
  assert.ok(has(withPanel, "Conceder VINTO-P1-01 en MP1"));
  const unselected = html(consoleModule.AdminConsoleView, viewProps({ selectedId: null, grantsPanel: panel() }));
  assert.ok(!unselected.includes('aria-label="Máquinas y formularios"'), "sin usuario seleccionado no hay sección");
});

test("a 403 on any new read blocks BOTH sections' actions and talks about permission, never about the session", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ block: "forbidden", grantsPanel: panel({ block: "forbidden", machineCode: "MP3" }) }));
  assert.ok(text.includes("Sin permiso") && !/sesión ya no es válida/.test(text));
  const sectorButtons = [...text.matchAll(/<button[^>]*aria-label="((?:Conceder|Revocar) acceso a [^"]+)"[^>]*>/g)].map((m) => /\sdisabled(=""|\s|>)/.test(m[0]));
  assert.ok(sectorButtons.length > 0 && sectorButtons.every(Boolean), "las acciones de sector quedan bloqueadas");
  assert.ok(actions(text).length > 0 && actions(text).every((a) => a.disabled), "y las de máquina y formulario también");
});

test("the section is never mounted by the page without the user.manage permission (the page decides before the console exists)", () => {
  const page = html(consoleModule.AdminConsole, { user: { id: ADMIN, username: "dev.data", display_name: "Data DEV", profiles: ["DATA_BALTREK"], permissions: ["user.manage"], must_change: false }, onLogout: noop, onSessionLost: noop });
  assert.ok(page.includes("Cargando usuarios…") && !page.includes("Máquinas y formularios"), "sin usuario seleccionado no se pide ni se pinta nada de concesiones");
});
