// node --test scripts/admin-ui.test.mjs
// Interfaz administrativa (M1-C2-b2): renderiza los COMPONENTES reales (React + react-dom/server) en cada estado de la pantalla, sin navegador ni red.
// Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio (para resolver react desde node_modules) que se borra al terminar.
// Los hooks/efectos no se ejecutan en el render del servidor: su lógica está en lib/vinto/admin.ts y se prueba en scripts/admin.test.mjs.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-admin-ui-test-${process.pid}`);

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

let parts, access, technical, consoleModule, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [parts, access, technical, consoleModule] = await Promise.all([
    bundle("components/vinto/admin/admin-parts.tsx", "parts"), bundle("components/vinto/admin/admin-access.tsx", "access"),
    bundle("components/vinto/technical-view.tsx", "technical"), bundle("components/vinto/admin/admin-console.tsx", "console"),
  ]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const html = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));
const BOBINAS = { code: "BOBINAS", name: "Bobinas", active: true, operational: true };
const REBOBINADO = { code: "REBOBINADO", name: "Rebobinado", active: true, operational: false };
const CONVERSION = { code: "CONVERSION", name: "Conversión", active: false, operational: false };
const ID_A = "11111111-1111-4111-8111-111111111111", ID_B = "22222222-2222-4222-8222-222222222222";
const user = (o = {}) => ({ id: ID_A, username: "dev.jefatura", display_name: "Jefatura DEV", active: true, profiles: ["JEFATURA"], sectors: [BOBINAS], ...o });
const ready = (data, refreshing = false) => ({ status: "ready", data, refreshing });
const detailOf = (sectors) => ready({ user_id: ID_A, username: "dev.jefatura", active: true, sectors });
const noop = () => {};
const count = (text, needle) => text.split(needle).length - 1;
const button = (text, label) => (text.match(new RegExp(`<button[^>]*aria-label="${label}"[^>]*>`)) ?? [""])[0]; // the opening tag of the button with that accessible name
const isDisabled = (text, label) => /\sdisabled(=""|\s|>)/.test(button(text, label));
const listProps = (o = {}) => ({ users: [user()], retrieved: 1, query: "", onQuery: noop, selectedId: null, onSelect: noop, limited: false, disabled: false, ...o });
const detailProps = (o = {}) => ({ user: user(), detail: detailOf([BOBINAS]), catalog: ready([BOBINAS, REBOBINADO, CONVERSION]), block: null, onGrant: noop, onRevoke: noop, onRetryDetail: noop, onRetryCatalog: noop, ...o });

test("the user list shows username, name, state, profiles, granted sectors and an explicit Administrar action; nothing changes by selecting a row", () => {
  const text = html(parts.AdminUserList, listProps({ users: [user(), user({ id: ID_B, username: "dev.data", display_name: "Data DEV", active: false, profiles: ["DATA_BALTREK"], sectors: [] })], retrieved: 2, selectedId: ID_A }));
  for (const expected of ["dev.jefatura", "Jefatura DEV", "Jefatura", "dev.data", "Data DEV", "Data Baltrek", "Inactivo", "Sin concesiones", ">BOBINAS<"]) assert.ok(text.includes(expected), expected);
  assert.equal(count(text, 'aria-label="Administrar dev.jefatura"'), 2, "desktop table row and mobile card, each with an explicit action");
  assert.ok(text.includes('aria-selected="true"'));
  assert.ok(text.includes("md:hidden") && text.includes("hidden md:block"), "table on desktop, cards on mobile");
  assert.ok(!/Conceder|Revocar/.test(text), "granting or revoking is only possible from the detail panel, after a confirmation");
});

test("sector chips tell granted-and-operational, inert (active but not operational) and inactive apart", () => {
  const text = html(parts.AdminUserList, listProps({ users: [user({ sectors: [BOBINAS, REBOBINADO, CONVERSION] })] }));
  assert.ok(/bg-emerald-50[^>]*title="Bobinas: operativo">BOBINAS/.test(text));
  assert.ok(/bg-amber-50[^>]*title="Rebobinado: no operativo \(inerte\)">REBOBINADO/.test(text));
  assert.ok(/bg-slate-100[^>]*title="Conversión: inactivo">CONVERSION/.test(text));
});

test("list states: no users, no match (search stays local), result limited by the API maximum, and actions disabled when access is blocked", () => {
  assert.ok(html(parts.AdminUserList, listProps({ users: [], retrieved: 0 })).includes("No hay usuarios para mostrar."));
  const none = html(parts.AdminUserList, listProps({ users: [], retrieved: 3, query: "zzz" }));
  assert.ok(none.includes("Ningún usuario recuperado coincide con «zzz»."));
  assert.ok(none.includes("solo sobre los 3 usuarios recuperados"), "the search never claims to look beyond the retrieved users");
  const limited = html(parts.AdminUserList, listProps({ limited: true, retrieved: 500 }));
  assert.ok(limited.includes("se alcanzó el máximo de 500 de la API") && limited.includes("podría haber usuarios que no se muestran"));
  assert.ok(!html(parts.AdminUserList, listProps()).includes("se alcanzó el máximo"));
  const blocked = html(parts.AdminUserList, listProps({ disabled: true }));
  assert.equal(count(blocked, "disabled"), count(html(parts.AdminUserList, listProps()), "disabled") + 2, "both Administrar buttons are disabled");
});

test("summary: counts what was retrieved, flags a limited result and shows dashes instead of inventing numbers", () => {
  const text = html(parts.AdminSummaryCards, { summary: { users: 500, activeUsers: 480, grants: 510, operationalSectors: 1, limited: true }, catalogSize: 3 });
  for (const expected of ["500", "480", "510", "Posible límite", "De 3 en el catálogo central"]) assert.ok(text.includes(expected), expected);
  const empty = html(parts.AdminSummaryCards, { summary: null, catalogSize: null });
  assert.equal(count(empty, ">—<"), 4);
  assert.ok(empty.includes("Catálogo central no disponible"));
});

test("detail without a selection only invites to select a user", () => {
  const text = html(parts.AdminUserDetail, detailProps({ user: null }));
  assert.ok(text.includes("Selecciona un usuario"));
  assert.ok(!/Conceder|Revocar/.test(text));
});

test("detail: granted sectors can be revoked (even inactive ones); only active, not yet granted sectors can be granted; inactive ones are listed apart", () => {
  const text = html(parts.AdminUserDetail, detailProps({ detail: detailOf([BOBINAS, CONVERSION]) }));
  assert.ok(text.includes('aria-label="Revocar acceso a Bobinas"'));
  assert.ok(text.includes('aria-label="Revocar acceso a Conversión"'), "an old grant on an inactive sector can be removed");
  assert.ok(text.includes('aria-label="Conceder acceso a Rebobinado"'));
  assert.ok(!text.includes('aria-label="Conceder acceso a Bobinas"'), "already granted: not offered again");
  assert.ok(!text.includes('aria-label="Conceder acceso a Conversión"'), "inactive: never offered");
  assert.ok(!text.includes("Inactivos (no admiten nuevas concesiones)"), "an inactive sector the user already holds is shown as granted, not as unavailable");
  assert.ok(html(parts.AdminUserDetail, detailProps({ detail: detailOf([BOBINAS]) })).includes("Inactivos (no admiten nuevas concesiones): Conversión (CONVERSION)"));
  assert.ok(text.includes("Activo") && text.includes("Operativo") && text.includes("No operativo") && text.includes("Inactivo"), "granted, active and operational are shown separately");
  assert.ok(text.includes("no da acceso a nada hasta que el sector se habilite"), "an inert sector is explained");
  assert.ok(text.includes("no se editan desde esta pantalla"), "profiles, permissions and operational state are not editable here");
});

test("detail states: loading, error with retry, no grants, nothing left to grant, empty catalogue and blocked access", () => {
  const loading = html(parts.AdminUserDetail, detailProps({ detail: { status: "loading" } }));
  assert.ok(loading.includes("Consultando las concesiones…") && !/Conceder|Revocar/.test(loading.replace(/Sectores (concedidos|disponibles)/g, "")), "no action is offered before the current grants are known");
  const failed = html(parts.AdminUserDetail, detailProps({ detail: { status: "error", kind: "unavailable", refreshing: false } }));
  assert.ok(failed.includes("No se pudieron cargar las concesiones") && failed.includes("Reintentar"));
  assert.ok(html(parts.AdminUserDetail, detailProps({ detail: detailOf([]) })).includes("Sin concesiones: este usuario no accede a ningún sector."));
  assert.ok(html(parts.AdminUserDetail, detailProps({ detail: detailOf([BOBINAS, REBOBINADO]) })).includes("Sin sectores disponibles para conceder"));
  assert.ok(html(parts.AdminUserDetail, detailProps({ catalog: ready([]) })).includes("Sin sectores disponibles: el catálogo central no tiene sectores."));
  const catalogDown = html(parts.AdminUserDetail, detailProps({ catalog: { status: "error", kind: "unavailable", refreshing: false } }));
  assert.ok(catalogDown.includes("No se pudo cargar el catálogo de sectores") && !catalogDown.includes('aria-label="Conceder'), "sectors are never invented when the catalogue is missing");
  const refreshing = html(parts.AdminUserDetail, detailProps({ detail: ready({ user_id: ID_A, username: "u", active: true, sectors: [BOBINAS] }, true) }));
  assert.ok(isDisabled(refreshing, "Revocar acceso a Bobinas"), "no new operation while the grants are being re-read");
  assert.ok(!isDisabled(html(parts.AdminUserDetail, detailProps()), "Revocar acceso a Bobinas"), "and it is enabled once the grants are known");
  const blocked = html(parts.AdminUserDetail, detailProps({ block: "forbidden" }));
  assert.ok(blocked.includes("Sin permiso") && blocked.includes("No tienes permiso para administrar usuarios y sectores."));
  assert.ok(isDisabled(blocked, "Conceder acceso a Rebobinado") && isDisabled(blocked, "Revocar acceso a Bobinas"));
  assert.ok(!isDisabled(html(parts.AdminUserDetail, detailProps()), "Conceder acceso a Rebobinado"));
});

const NOW_USER = { id: ID_A, username: "dev.data", display_name: "Data DEV", profiles: ["DATA_BALTREK"], permissions: ["user.manage", "catalog.read"], must_change: false };
const viewProps = (o = {}) => {
  const base = { user: NOW_USER, users: ready([user(), user({ id: ID_B, username: "dev.data", display_name: "Data DEV", profiles: ["DATA_BALTREK"], sectors: [] })]), catalog: ready([BOBINAS, REBOBINADO, CONVERSION]), detail: detailOf([BOBINAS]),
    query: "", onQuery: noop, selectedId: ID_A, onSelect: noop, change: { step: "closed" }, onOpen: noop, onConfirm: noop, onClose: noop, onRetryUsers: noop, onRetryCatalog: noop, onRetryDetail: noop, onLogout: noop, block: null, ...o };
  return base;
};
const actionsOf = (text) => [...text.matchAll(/<button[^>]*aria-label="((?:Conceder|Revocar) acceso a [^"]+)"[^>]*>/g)].map((m) => ({ label: m[1], disabled: /\sdisabled(=""|\s|>)/.test(m[0]) }));
const err = (kind) => ({ status: "error", kind, refreshing: false });

test("D) users list answers 403: the console says there is no permission, offers no list and no action, and never talks about the session", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ users: err("forbidden"), block: "forbidden", detail: { status: "idle" } }));
  assert.ok(text.includes("Sin permiso") && text.includes("No tienes permiso para administrar usuarios y sectores."));
  assert.deepEqual(actionsOf(text), []);
  assert.ok(!/Administrar dev|Reintentar/.test(text), "no list and no retry for a permission problem");
  assert.ok(!/sesión ya no es válida|Ingresa de nuevo/.test(text));
});

test("E) the catalogue answers 403 while users and detail are loaded: every action is blocked", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ catalog: err("forbidden"), block: "forbidden" }));
  assert.ok(text.includes("Sin permiso"));
  const actions = actionsOf(text);
  assert.ok(actions.length >= 1 && actions.every((a) => a.disabled), JSON.stringify(actions));
  assert.ok(/aria-label="Administrar dev\.jefatura"[^>]*>|disabled=""[^>]*aria-label="Administrar dev\.jefatura"/.test(text));
});

test("F) the user detail answers 403: the actions are blocked and the message is about permission", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ detail: err("forbidden"), block: "forbidden" }));
  assert.ok(text.includes("Sin permiso") && !/sesión ya no es válida/.test(text));
  assert.ok(actionsOf(text).every((a) => a.disabled));
  assert.ok(text.includes("No se pudieron cargar las concesiones"));
});

test("G) an unauthorised origin blocks the actions with ITS OWN message, not the missing-permission one", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ block: "origin" }));
  assert.ok(text.includes("Origen no autorizado") && text.includes("Esta dirección no está autorizada para administrar"));
  assert.ok(!text.includes("Sin permiso") && !text.includes("No tienes permiso para administrar"), "the real cause is the origin, not a permission");
  assert.ok(!/sesión ya no es válida/.test(text));
  const actions = actionsOf(text);
  assert.ok(actions.length >= 1 && actions.every((a) => a.disabled));
});

test("without a block, the same console offers the actions (so the blocked cases above are real, not vacuous)", () => {
  const actions = actionsOf(html(consoleModule.AdminConsoleView, viewProps({ block: null })));
  assert.ok(actions.length >= 2 && actions.every((a) => !a.disabled));
  assert.ok(!html(consoleModule.AdminConsoleView, viewProps({ block: null })).includes("Sin permiso"));
});

test("a failed read that is NOT a permission problem keeps the retry and does not block", () => {
  const text = html(consoleModule.AdminConsoleView, viewProps({ users: err("unavailable"), block: null, detail: { status: "idle" } }));
  assert.ok(text.includes("No se pudieron cargar los usuarios") && text.includes("Reintentar") && !text.includes("Sin permiso"));
});

test("a forbidden answer is shown as missing permission, not as an expired session", () => {
  const text = html(parts.AdminNotice, { title: "Sin permiso", text: "No tienes permiso para administrar usuarios y sectores." });
  assert.ok(text.includes("Sin permiso") && !/sesión/i.test(text));
});

test("access denied screen: authorization message with a way back and a logout", () => {
  const text = html(access.AdminDenied, { onBack: noop, onLogout: noop });
  for (const expected of ["Acceso no autorizado", "Volver al inicio", "Cerrar sesión"]) assert.ok(text.includes(expected), expected);
  assert.ok(!/Conceder|Revocar|Administrar/.test(text));
});

test("the console, rendered for a session, shows only the loading state and requests nothing on its own render", () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (...args) => { calls.push(args); throw new Error("no network in a render test"); };
  try {
    const text = html(consoleModule.AdminConsole, { user: { id: ID_A, username: "dev.data", display_name: "Data DEV", profiles: ["DATA_BALTREK"], permissions: ["user.manage", "catalog.read"], must_change: false }, onLogout: noop, onSessionLost: noop });
    for (const expected of ["Administración de usuarios", "Data DEV", "Data Baltrek", "Cargando usuarios…", 'aria-label="Cerrar sesión"', 'href="/"']) assert.ok(text.includes(expected), expected);
    assert.ok(!/Conceder|Revocar|Administrar dev/.test(text), "no list and no action before the central data arrives");
    assert.ok(text.includes("Concede o revoca el acceso"), "the page explains profile (what) versus grant (where)");
    assert.deepEqual(calls, [], "rendering performs no request; effects run only in the browser");
  } finally { globalThis.fetch = original; }
});

test("technical view: the link to /admin appears only with the user.manage permission, regardless of the profile name", () => {
  const base = { id: ID_A, username: "x", display_name: "Persona", must_change: false };
  const withLink = (o) => html(technical.TechnicalView, { user: { ...base, ...o }, onLogout: noop }).includes('href="/admin"');
  assert.equal(withLink({ profiles: ["DATA_BALTREK"], permissions: ["catalog.read", "catalog.manage", "user.manage"] }), true);
  assert.equal(withLink({ profiles: ["DATA_BALTREK"], permissions: ["catalog.read", "catalog.manage"] }), false, "the DATA_BALTREK name alone is not enough");
  assert.equal(withLink({ profiles: [], permissions: [] }), false);
  assert.equal(withLink({ profiles: ["JEFATURA"], permissions: ["work_order.manage", "user.manage"] }), true, "user.manage next to an operational profile still reaches the administration");
  const operational = html(technical.TechnicalView, { user: { ...base, profiles: ["OPERACION"], permissions: ["production.capture"] }, onLogout: noop });
  assert.ok(operational.includes("Sin perfil operativo") && !operational.includes("/admin"));
});
