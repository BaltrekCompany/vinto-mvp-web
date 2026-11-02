// node --test scripts/admin-grants.test.mjs
// Administración de concesiones MÁQUINA-FORMULARIO (MF-13-01C.3): contratos y validadores de los 7 endpoints, cliente HTTP (mismo requester que sectores), fallos, reglas de presentación
// (publicado / ofrecido / habilitado / concedido / inerte), máquina de estados y controlador de la operación (confirmación, doble envío, usuario cambiado durante la petición),
// resultado incierto y salvaguardas del código fuente. Funciones puras: sin red ni DOM.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createAdminClient, deriveResource, failureKind, FAILURE_MESSAGES } from "../lib/vinto/admin.ts";
import {
  GRANT_CLOSED, HISTORY_LIMIT, NOT_EFFECTIVE_NOTICE, NO_POLICY_NOTE, SECTOR_NOT_GRANTED_NOTICE, actionsLocked, contextInert, createGrantChangeController, createGrantsClient, findMachine, formRows,
  formatWhen, grantChangeReducer, grantConfirmationText, grantResultText, historyNotice, historyRows, inertReasons, inertText, isReread, machineGroups, markUncertain, nextUncertainty,
  notOfferedForms, parseFormsCatalog, parseGrantChange, parseGrantRow, parseMachineCatalog, parseUserDetail, parseUserGrants, policyLabel, refreshPlan, visibleFeedback,
} from "../lib/vinto/admin-grants.ts";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const U1 = "11111111-1111-4111-8111-111111111111", U2 = "22222222-2222-4222-8222-222222222222", ADMIN = "99999999-9999-4999-8999-999999999999";
let counter = 0;
const gid = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, "0")}`;

// ---- fixtures: las máquinas y formularios son del CATÁLOGO simulado de la API (en el código de la aplicación no hay ninguna lista) ----
const form = (code, o = {}) => ({ code, name: `Nombre ${code}`, area: "production", active: true, effective_version: 2, published: true, capture_policies: ["production_central"], offered: true, enabled_for_capture: true, ...o });
const P101 = form("VINTO-P1-01", { effective_version: 4 }), P102 = form("VINTO-P1-02", { effective_version: 1 }), P106 = form("VINTO-P1-06");
const P103 = form("VINTO-P1-03", { effective_version: 1, capture_policies: [], enabled_for_capture: false }), P110 = form("VINTO-P1-10", { effective_version: 3 }), P131 = form("VINTO-P1-31");
const P118 = form("VINTO-P1-18", { area: "quality", capture_policies: ["quality_by_machine"] });
const machine = (code, forms, o = {}) => ({ code, name: code, active: true, forms, ...o });
const sector = (code, machines, o = {}) => ({ code, name: code[0] + code.slice(1).toLowerCase(), active: true, operational: true, machines, ...o });
const FIVE = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"];
const CATALOG = {
  sectors: [
    sector("BOBINAS", [machine("MP1", [P101, P102, P103, P106, P118]), machine("MP3", [P101, P102, P103, P106, P118, P131])]),
    sector("REBOBINADO", FIVE.map((code) => machine(code, [P110]))),
    sector("CONVERSION", [machine("GAMBINI", [form("VINTO-P1-16", { effective_version: 3 })])], { operational: false }),
  ],
};
// CONVERSION del fixture no es operativo: ningún formulario suyo puede estar habilitado para captura.
CATALOG.sectors[2].machines[0].forms[0].enabled_for_capture = false;
const status = (o = {}) => ({ published_version: 2, offered: true, enabled_for_capture: true, capture_policies: ["production_central"], ...o });
const row = (machineCode, formCode, o = {}) => ({
  id: gid(), state: "active", machine: { code: machineCode, name: machineCode, sector_code: "BOBINAS" }, form: { code: formCode, name: `Nombre ${formCode}`, area: "production" },
  granted_at: "2026-10-31T04:20:59.123456+00:00", granted_by: { id: ADMIN, display_name: "Admin DEV" }, revoked_at: null, revoked_by: null, catalog: status(), ...o,
});
const revokedRow = (machineCode, formCode, o = {}) => row(machineCode, formCode, { state: "revoked", revoked_at: "2026-10-31T05:00:00+00:00", revoked_by: { id: ADMIN, display_name: "Admin DEV" }, ...o });
const grants = (list, o = {}) => ({ user_id: U1, total: list.length, truncated: false, grants: list, ...o });
const context = (o = {}) => ({ user_active: true, sector_code: "BOBINAS", sector_granted: true, sector_operational: true, ...o });
const changeOf = (o = {}) => ({ user_id: U1, machine_code: "MP1", form_code: "VINTO-P1-01", operation: "grant", changed: true, active: true, request_id: "admin-machine-form-grant:abc",
  grant: row("MP1", "VINTO-P1-01"), catalog: status({ published_version: 4 }), context: context(), ...o });
const detail = (o = {}) => ({ id: U1, username: "dev.operacion", display_name: "Operación DEV", active: true, profiles: [{ code: "OPERACION", name: "Operación" }], permissions: ["assignment.read"],
  sectors: [{ code: "BOBINAS", name: "Bobinas", active: true, operational: true }], ...o });
const formsCatalog = () => ({ forms: [
  { code: "VINTO-P1-01", name: "N", area: "production", active: true, published: true, effective_version: 4, capture_policies: ["production_central"], enabled_for_capture: true,
    machines: [{ code: "MP1", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }, { code: "MP3", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }] },
  { code: "VINTO-P1-31", name: "Consumo de químicos", area: "production", active: true, published: true, effective_version: 2, capture_policies: ["production_central"], enabled_for_capture: true,
    machines: [{ code: "MP3", sector_code: "BOBINAS", active: true, offered: true, enabled_for_capture: true }] },
  { code: "VINTO-P1-99", name: "Borrador", area: "production", active: true, published: false, effective_version: null, capture_policies: [], enabled_for_capture: false, machines: [] },
] });

const reply = (status_, body) => ({ ok: status_ >= 200 && status_ < 300, status: status_, json: async () => { if (body === undefined) throw new SyntaxError("sin cuerpo"); return body; } });
const recorder = (responder) => { const calls = []; const fetchImpl = async (url, init) => { calls.push({ url, init }); return responder(url, init, calls.length); }; return { fetchImpl, calls }; };
const clientWith = (responder) => { const rec = recorder(responder); return { client: createGrantsClient(() => "http://api.test", rec.fetchImpl), calls: rec.calls }; };
const failureOf = async (promise) => { const result = await promise; assert.equal(result.ok, false); return result; };
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const target = (o = {}) => ({ operation: "grant", userId: U1, userLabel: "Operación DEV", machineCode: "MP1", machineName: "MP1", formCode: "VINTO-P1-01", formName: "Nombre", offered: true, inert: [], sectorGranted: true, ...o });

// ---- 1. contratos y validadores ----

test("machine catalogue: a valid catalogue parses, with P1-01 listed on MP1 and MP3 separately and P1-10 on the five rebobinadoras", () => {
  const parsed = parseMachineCatalog(structuredClone(CATALOG));
  assert.ok(parsed);
  const machines = Object.fromEntries(parsed.sectors.flatMap((s) => s.machines).map((m) => [m.code, m.forms.map((f) => f.code)]));
  assert.ok(machines.MP1.includes("VINTO-P1-01") && machines.MP3.includes("VINTO-P1-01"));
  for (const code of FIVE) assert.deepEqual(machines[code], ["VINTO-P1-10"], code);
  assert.ok(!machines.MP1.includes("VINTO-P1-31") && machines.MP3.includes("VINTO-P1-31"), "P1-31 solo en MP3");
});

test("machine catalogue: every inconsistent answer is rejected (never shown half-way)", () => {
  const bad = (mutate) => { const c = structuredClone(CATALOG); mutate(c); return parseMachineCatalog(c); };
  assert.equal(parseMachineCatalog(null), null);
  assert.equal(parseMachineCatalog({}), null);
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].enabled_for_capture = true; c.sectors[0].machines[0].forms[0].offered = false; }), null, "habilitado sin ofrecido");
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].capture_policies = []; }), null, "habilitado sin ninguna política");
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].active = false; }), null, "ofrecido con el formulario inactivo");
  assert.equal(bad((c) => { c.sectors[0].machines[0].active = false; }), null, "una máquina inactiva no ofrece nada");
  assert.equal(bad((c) => { c.sectors[0].active = false; c.sectors[0].operational = false; }), null, "un sector inactivo no ofrece nada");
  assert.equal(bad((c) => { c.sectors[2].machines[0].forms[0].enabled_for_capture = true; }), null, "habilitado para captura en un sector no operativo");
  assert.equal(bad((c) => { c.sectors[1].operational = true; c.sectors[1].active = false; }), null, "operativo pero inactivo");
  assert.equal(bad((c) => { c.sectors[1].machines[0].code = "MP1"; }), null, "un código de máquina en dos sectores");
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms.push(c.sectors[0].machines[0].forms[0]); }), null, "formulario repetido en una máquina");
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].published = false; }), null);
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].effective_version = 0; }), null);
  assert.equal(bad((c) => { c.sectors[0].machines[0].forms[0].capture_policies = ["production_central", "production_central"]; }), null);
  assert.equal(bad((c) => { c.sectors[0].machines[0].code = "mp1"; }), null, "forma de código inválida");
});

test("forms catalogue: published <=> effective version, no links without a published version, enabled = enabled somewhere", () => {
  assert.ok(parseFormsCatalog(formsCatalog()));
  const bad = (mutate) => { const c = formsCatalog(); mutate(c); return parseFormsCatalog(c); };
  assert.equal(bad((c) => { c.forms[2].published = true; }), null, "publicado sin versión");
  assert.equal(bad((c) => { c.forms[0].effective_version = null; }), null, "versión nula con published true");
  assert.equal(bad((c) => { c.forms[2].machines = [c.forms[0].machines[0]]; }), null, "vínculos sin versión publicada");
  assert.equal(bad((c) => { c.forms[0].enabled_for_capture = false; }), null, "habilitado en alguna máquina pero el formulario dice que no");
  assert.equal(bad((c) => { c.forms[0].machines[0].offered = false; }), null, "habilitado sin ofrecido");
  assert.equal(bad((c) => { c.forms.push(c.forms[0]); }), null, "formulario repetido");
  assert.equal(parseFormsCatalog({ forms: "x" }), null);
});

test("user detail: shape is enforced and extra fields (including anything secret-looking) are dropped", () => {
  const parsed = parseUserDetail({ ...detail(), password_hash: "x", token: "y" });
  assert.deepEqual(Object.keys(parsed).sort(), ["active", "display_name", "id", "permissions", "profiles", "sectors", "username"]);
  assert.equal(parseUserDetail({ ...detail(), id: "no-uuid" }), null);
  assert.equal(parseUserDetail({ ...detail(), profiles: [{ code: "A", name: "a" }, { code: "A", name: "b" }] }), null);
  assert.equal(parseUserDetail({ ...detail(), sectors: [{ code: "BOBINAS", name: "B", active: false, operational: true }] }), null);
  assert.equal(parseUserDetail({ ...detail(), permissions: [1] }), null);
  assert.equal(parseUserDetail({ ...detail(), username: undefined }), null);
});

test("grants and history: active rows carry no revocation, revoked rows are dated and attributed, `truncated` is consistent with `total`", () => {
  assert.ok(parseGrantRow(row("MP1", "VINTO-P1-01")));
  assert.ok(parseGrantRow(revokedRow("MP1", "VINTO-P1-01")));
  assert.equal(parseGrantRow(row("MP1", "VINTO-P1-01", { revoked_at: "2026-10-31T05:00:00+00:00" })), null, "activa con fecha de revocación");
  assert.equal(parseGrantRow(revokedRow("MP1", "VINTO-P1-01", { revoked_by: null })), null, "revocada sin responsable");
  assert.equal(parseGrantRow(revokedRow("MP1", "VINTO-P1-01", { revoked_at: null })), null, "revocada sin fecha");
  assert.equal(parseGrantRow(row("MP1", "VINTO-P1-01", { granted_at: "ayer" })), null);
  assert.equal(parseGrantRow(row("MP1", "VINTO-P1-01", { catalog: status({ enabled_for_capture: true, offered: false }) })), null, "habilitado sin ofrecido");
  assert.equal(parseGrantRow(row("mp1", "VINTO-P1-01")), null);
  assert.ok(parseGrantRow(row("MP1", "VINTO-P1-05", { catalog: status({ offered: false, enabled_for_capture: false, published_version: 2 }) })), "una concesión inerte (par ya no ofrecido) es válida");
  assert.ok(parseUserGrants(grants([row("MP1", "VINTO-P1-01")])));
  assert.ok(parseUserGrants(grants([row("MP1", "VINTO-P1-01")], { total: 5, truncated: true })));
  assert.equal(parseUserGrants(grants([row("MP1", "VINTO-P1-01")], { total: 5, truncated: false })), null, "faltan filas sin truncated");
  assert.equal(parseUserGrants(grants([row("MP1", "VINTO-P1-01")], { total: 1, truncated: true })), null, "truncated sin filas de más");
  const dup = row("MP1", "VINTO-P1-01");
  assert.equal(parseUserGrants(grants([dup, dup])), null, "id repetido");
});

test("grant change: audit id only when something changed, final state corresponds to the operation and the row belongs to the requested pair", () => {
  assert.ok(parseGrantChange(changeOf()));
  assert.ok(parseGrantChange(changeOf({ operation: "grant", changed: false, request_id: null })), "idempotente");
  assert.ok(parseGrantChange(changeOf({ operation: "revoke", changed: true, active: false, grant: revokedRow("MP1", "VINTO-P1-01") })));
  assert.ok(parseGrantChange(changeOf({ operation: "revoke", changed: false, request_id: null, active: false, grant: null })), "revocar lo que nunca existió");
  assert.equal(parseGrantChange(changeOf({ changed: true, request_id: null })), null);
  assert.equal(parseGrantChange(changeOf({ changed: false, request_id: "x" })), null);
  assert.equal(parseGrantChange(changeOf({ operation: "revoke", active: true })), null, "revocar y quedar activa");
  assert.equal(parseGrantChange(changeOf({ active: false })), null, "conceder y quedar inactiva");
  assert.equal(parseGrantChange(changeOf({ grant: row("MP3", "VINTO-P1-01") })), null, "fila de otra máquina");
  assert.equal(parseGrantChange(changeOf({ grant: revokedRow("MP1", "VINTO-P1-01") })), null, "activa según el estado pero la fila está revocada");
  assert.equal(parseGrantChange(changeOf({ grant: null })), null, "activa sin fila");
  assert.equal(parseGrantChange(changeOf({ grant: { id: "x" } })), null, "fila inválida no se confunde con «nunca existió»");
  assert.equal(parseGrantChange(changeOf({ context: { user_active: true } })), null);
  assert.equal(parseGrantChange(changeOf({ operation: "other" })), null);
});

// ---- 2. cliente HTTP (mismo requester que sectores: cookie, sin caché, sin Origin) ----

test("reads: GET with the session cookie, no cache, no body, no Origin and no identity headers; the history asks for its limit", async () => {
  const { client, calls } = clientWith((url) => reply(200, url.endsWith("/catalog") ? CATALOG : url.endsWith("/catalog/forms") ? formsCatalog()
    : url.includes("/grants/history") ? grants([revokedRow("MP1", "VINTO-P1-01")]) : url.endsWith("/grants") ? grants([row("MP1", "VINTO-P1-01")]) : detail()));
  assert.ok((await client.getMachineCatalog()).ok);
  assert.ok((await client.getFormsCatalog()).ok);
  assert.ok((await client.getUserDetail(U1)).ok);
  assert.ok((await client.getUserGrants(U1)).ok);
  assert.ok((await client.getUserGrantsHistory(U1)).ok);
  assert.deepEqual(calls.map((c) => c.url), ["http://api.test/api/admin/catalog", "http://api.test/api/admin/catalog/forms", `http://api.test/api/admin/users/${U1}`,
    `http://api.test/api/admin/users/${U1}/grants`, `http://api.test/api/admin/users/${U1}/grants/history?limit=${HISTORY_LIMIT}`]);
  for (const { init } of calls) {
    assert.equal(init.method, "GET");
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    assert.equal(init.body, undefined);
    assert.equal(init.headers, undefined, "ni Origin ni cabeceras de identidad");
  }
});

test("changes: POST JSON with ONLY machine_code and form_code; actor, user, request id, permissions and profiles never travel in the body", async () => {
  for (const operation of ["grant", "revoke"]) {
    const { client, calls } = clientWith(() => reply(200, changeOf({ operation, active: operation === "grant", changed: true, grant: operation === "grant" ? row("MP1", "VINTO-P1-01") : revokedRow("MP1", "VINTO-P1-01") })));
    const result = await client.changeGrant(operation, U1, "MP1", "VINTO-P1-01");
    assert.equal(result.ok, true, operation);
    const [{ url, init }] = calls;
    assert.equal(url, `http://api.test/api/admin/users/${U1}/grants/${operation}`);
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), { machine_code: "MP1", form_code: "VINTO-P1-01" });
    assert.deepEqual(init.headers, { "Content-Type": "application/json" });
    assert.equal(init.credentials, "include");
    for (const forbidden of ["actor", "revoked_by", "request_id", "permission", "profile", "user_id"]) assert.ok(!init.body.includes(forbidden), forbidden);
  }
});

test("statuses are told apart: 401 session, 403 permission (not session) vs origin, 404 user/machine/form, 409 pair not offered, 415, 422 and 503/network", async () => {
  const cases = [[401, undefined, "session"], [403, "FORBIDDEN", "forbidden"], [403, "ORIGIN_NOT_ALLOWED", "origin"], [404, "USER_NOT_FOUND", "user_not_found"], [404, "MACHINE_NOT_FOUND", "machine_not_found"],
    [404, "FORM_NOT_FOUND", "form_not_found"], [404, undefined, "not_found"], [409, "PAIR_NOT_OFFERED", "pair_not_offered"], [409, "OTHER", "invalid"], [415, "UNSUPPORTED_MEDIA_TYPE", "unsupported"],
    [422, undefined, "invalid"], [503, undefined, "unavailable"], [500, undefined, "unavailable"]];
  for (const [httpStatus, code, kind] of cases) {
    const { client } = clientWith(() => reply(httpStatus, code ? { detail: "texto del servidor que no se muestra", code } : { detail: "x" }));
    const result = await failureOf(client.changeGrant("grant", U1, "MP1", "VINTO-P1-01"));
    assert.deepEqual([result.kind, result.status], [kind, httpStatus], `${httpStatus} ${code}`);
    assert.equal(failureKind(httpStatus, code), kind);
    assert.ok(FAILURE_MESSAGES[kind], `hay mensaje para ${kind}`);
  }
  const network = createGrantsClient(() => "http://api.test", async () => { throw new TypeError("fallo de red"); });
  assert.deepEqual((await failureOf(network.changeGrant("grant", U1, "MP1", "VINTO-P1-01"))).kind, "unavailable");
  assert.deepEqual((await failureOf(network.getUserGrants(U1))).kind, "unavailable");
});

test("invalid or mismatching responses are never treated as success, and malformed identifiers send nothing", async () => {
  const mismatches = [changeOf({ machine_code: "MP3", grant: row("MP3", "VINTO-P1-01") }), changeOf({ form_code: "VINTO-P1-02", grant: row("MP1", "VINTO-P1-02") }),
    changeOf({ user_id: U2 }), changeOf({ operation: "revoke", active: false, grant: revokedRow("MP1", "VINTO-P1-01") })];
  for (const body of mismatches) {
    const { client } = clientWith(() => reply(200, body));
    const result = await failureOf(client.changeGrant("grant", U1, "MP1", "VINTO-P1-01"));
    assert.equal(result.kind, "unavailable");
  }
  assert.equal((await failureOf(clientWith(() => reply(200, { grants: [] })).client.getUserGrants(U1))).kind, "unavailable");
  assert.equal((await failureOf(clientWith(() => reply(200, grants([]), U2)).client.getUserGrants(U2))).kind, "unavailable", "las concesiones de otro usuario no se aceptan");
  const { client, calls } = clientWith(() => reply(200, {}));
  for (const attempt of [client.getUserDetail("no-uuid"), client.getUserGrants("x"), client.getUserGrantsHistory("1"), client.changeGrant("grant", "x", "MP1", "VINTO-P1-01"),
    client.changeGrant("grant", U1, "mp1", "VINTO-P1-01"), client.changeGrant("grant", U1, "MP1", "vinto-p1-01"), client.changeGrant("revoke", U1, "", "VINTO-P1-01")]) {
    assert.equal((await failureOf(attempt)).kind, "invalid");
  }
  assert.equal(calls.length, 0);
});

test("the grants client reuses the administrative requester of the sector client (same fetch contract)", async () => {
  const seen = [];
  const fetchImpl = async (url, init) => { seen.push(init); return reply(200, []); };
  await createAdminClient(() => "http://api.test", fetchImpl).listSectors();
  await createGrantsClient(() => "http://api.test", async (url, init) => { seen.push(init); return reply(200, CATALOG); }).getMachineCatalog();
  assert.deepEqual([seen[0].credentials, seen[0].cache, seen[0].method], [seen[1].credentials, seen[1].cache, seen[1].method]);
});

// ---- 3. reglas de presentación ----

const OPERATOR = { active: true, sectors: [{ code: "BOBINAS" }] };
const rowsOf = (machineCode, active, user = OPERATOR) => {
  const found = findMachine(CATALOG, machineCode);
  return formRows(found.machine, found.sector, active, user);
};

test("P1-01 is independent on MP1 and MP3: a grant on MP3 never appears, nor counts, on MP1", () => {
  const mp3 = row("MP3", "VINTO-P1-01", { machine: { code: "MP3", name: "MP3", sector_code: "BOBINAS" } });
  const on = (code) => rowsOf(code, [mp3]).find((r) => r.code === "VINTO-P1-01");
  assert.equal(on("MP1").grant, null);
  assert.equal(on("MP1").canGrant, true);
  assert.equal(on("MP1").canRevoke, false);
  assert.equal(on("MP3").grant.id, mp3.id);
  assert.equal(on("MP3").canGrant, false);
  assert.equal(on("MP3").canRevoke, true);
  const groups = machineGroups(CATALOG, [mp3]);
  assert.deepEqual(groups.flatMap((g) => g.machines).filter((m) => m.granted > 0).map((m) => m.code), ["MP3"]);
});

test("the five distinctions: published, offered, enabled for capture and granted are told apart, and no row claims effective operational access", () => {
  const rows = rowsOf("MP1", [row("MP1", "VINTO-P1-06")]);
  const by = Object.fromEntries(rows.map((r) => [r.code, r]));
  const text = (r) => r.badges.map((b) => b.text).join(" | ");
  assert.match(text(by["VINTO-P1-06"]), /Publicado v2 \| Ofrecido a la máquina \| Habilitado: Captura central de producción \| Concedido$/);
  assert.match(text(by["VINTO-P1-03"]), /Publicado v1 \| Ofrecido a la máquina \| Sin política de captura central \| No concedido$/, "publicado y ofrecido, pero sin política central");
  assert.equal(by["VINTO-P1-03"].canGrant, true, "se puede conceder aunque no tenga política de captura");
  assert.match(text(by["VINTO-P1-18"]), /Habilitado: Control de Calidad por máquina/);
  for (const r of rows) assert.doesNotMatch(text(r), /efectiv/i, "ningún distintivo habla de acceso efectivo");
  assert.match(NO_POLICY_NOTE, /no significa que el formulario no exista/);
  assert.match(NO_POLICY_NOTE, /otra ruta especializada/);
  assert.match(NOT_EFFECTIVE_NOTICE, /determinan qué formularios ve el usuario/);
  assert.match(NOT_EFFECTIVE_NOTICE, /modo «enforce»/); // MF-13-02: elegibilidad (interfaz) ≠ rechazo de capturas (modo de la compuerta)
  assert.equal(policyLabel("quality_by_bobbin"), "Control de Calidad por bobina");
  assert.equal(policyLabel("future_policy"), "future_policy", "una política desconocida se muestra tal cual");
});

test("a grant whose pair is no longer offered is INERT and still revocable, but a pair that is not offered can never be granted", () => {
  const orphan = row("MP1", "VINTO-P1-05", { form: { code: "VINTO-P1-05", name: "Tubetes", area: "production" }, catalog: status({ offered: false, enabled_for_capture: false, published_version: 2 }) });
  const rows = rowsOf("MP1", [orphan]);
  const inert = rows.find((r) => r.code === "VINTO-P1-05");
  assert.equal(inert.fromCatalog, false, "no está en el catálogo de la máquina, pero se muestra");
  assert.deepEqual([inert.canRevoke, inert.canGrant, inert.inert], [true, false, ["pair_not_offered"]]);
  assert.match(inert.badges.map((b) => b.text).join("|"), /Concedido · inerte/);
  const hidden = formRows(machine("MPX", [form("VINTO-P1-77", { offered: false, enabled_for_capture: false, active: true })]), { code: "BOBINAS", active: true, operational: true }, [], OPERATOR);
  assert.deepEqual([hidden[0].canGrant, hidden[0].canRevoke], [false, false]);
  assert.match(hidden[0].grantBlockedReason, /no ofrece este formulario/);
});

test("inert reasons: inactive user, missing sector, non-operational sector or pair not offered; nothing is granted automatically", () => {
  const sec = { code: "BOBINAS", active: true, operational: true };
  assert.deepEqual(inertReasons({ userActive: true, grantedSectors: [{ code: "BOBINAS" }], sector: sec, offered: true }), []);
  assert.deepEqual(inertReasons({ userActive: false, grantedSectors: [{ code: "BOBINAS" }], sector: sec, offered: true }), ["user_inactive"]);
  assert.deepEqual(inertReasons({ userActive: true, grantedSectors: [], sector: sec, offered: true }), ["sector_missing"]);
  assert.deepEqual(inertReasons({ userActive: true, grantedSectors: [{ code: "BOBINAS" }], sector: { ...sec, operational: false }, offered: true }), ["sector_not_operational"]);
  assert.deepEqual(inertReasons({ userActive: true, grantedSectors: [{ code: "BOBINAS" }], sector: sec, offered: false }), ["pair_not_offered"]);
  assert.deepEqual(inertReasons({ userActive: true, grantedSectors: [], sector: null, offered: true }), ["sector_missing", "sector_not_operational"]);
  assert.match(inertText(["user_inactive", "sector_missing"]), /^Concesión inerte: el usuario está inactivo; el usuario no tiene concedido el sector de la máquina\.$/);
  assert.equal(inertText([]), "");
  assert.match(SECTOR_NOT_GRANTED_NOTICE, /NO se concede automáticamente/);
  const noSector = rowsOf("MP1", [row("MP1", "VINTO-P1-01")], { active: true, sectors: [] });
  assert.deepEqual(noSector.find((r) => r.code === "VINTO-P1-01").inert, ["sector_missing"]);
  const inactive = rowsOf("MP1", [row("MP1", "VINTO-P1-01")], { active: false, sectors: [{ code: "BOBINAS" }] });
  assert.deepEqual(inactive.find((r) => r.code === "VINTO-P1-01").inert, ["user_inactive"]);
  assert.deepEqual(contextInert(changeOf({ context: context({ user_active: false, sector_granted: false, sector_operational: false }), catalog: status({ offered: false, enabled_for_capture: false }) })),
    ["user_inactive", "sector_missing", "sector_not_operational", "pair_not_offered"]);
});

test("not-offered forms are listed apart (published but not linked to the machine, or unpublished) and P1-31 is not offered on MP1", () => {
  const hidden = notOfferedForms(parseFormsCatalog(formsCatalog()).forms, "MP1");
  assert.deepEqual(hidden.map((f) => f.code), ["VINTO-P1-31", "VINTO-P1-99"]);
  assert.match(hidden[0].reason, /Publicado \(v2\), pero su versión vigente no lo vincula a esta máquina/);
  assert.equal(hidden[1].reason, "Sin versión publicada.");
  assert.deepEqual(notOfferedForms(parseFormsCatalog(formsCatalog()).forms, "MP3").map((f) => f.code), ["VINTO-P1-99"], "en MP3 sí se ofrece");
});

test("history rows show machine, form, dates and who granted and revoked; truncated results say so; dates are UTC and stable", () => {
  const rows = historyRows([revokedRow("MP1", "VINTO-P1-01"), row("MP3", "VINTO-P1-01")]);
  assert.deepEqual(rows.map((r) => [r.machine, r.state, r.grantedBy, r.revokedBy, r.revokedAt]), [["MP1", "Revocada", "Admin DEV", "Admin DEV", "2026-10-31 05:00 UTC"], ["MP3", "Activa", "Admin DEV", "—", "—"]]);
  assert.equal(rows[0].grantedAt, "2026-10-31 04:20 UTC");
  assert.equal(rows[0].form, "VINTO-P1-01 · Nombre VINTO-P1-01");
  assert.equal(formatWhen(null), "—");
  assert.equal(formatWhen("no-es-fecha"), "—");
  assert.equal(historyNotice(grants([row("MP1", "VINTO-P1-01")])), null);
  assert.match(historyNotice(grants([row("MP1", "VINTO-P1-01")], { total: 250, truncated: true })), /Se muestran las 1 concesiones más recientes de 250/);
});

// ---- 4. máquina de estados y controlador ----

test("reducer: nothing is submitted without opening and confirming; a second submit, a late response and a close while sending do nothing; an unoffered pair cannot be opened for granting", () => {
  assert.equal(grantChangeReducer(GRANT_CLOSED, { type: "submit", token: 1 }), GRANT_CLOSED);
  const confirming = grantChangeReducer(GRANT_CLOSED, { type: "open", target: target() });
  assert.equal(confirming.step, "confirming");
  const submitting = grantChangeReducer(confirming, { type: "submit", token: 1 });
  assert.equal(submitting.step, "submitting");
  assert.equal(grantChangeReducer(submitting, { type: "submit", token: 2 }), submitting, "el segundo envío no hace nada");
  assert.equal(grantChangeReducer(submitting, { type: "close" }), submitting, "no se cierra mientras se envía");
  assert.equal(grantChangeReducer(submitting, { type: "open", target: target({ machineCode: "MP3" }) }), submitting, "ni se abre otro");
  assert.equal(grantChangeReducer(submitting, { type: "resolved", token: 99, result: { ok: true, data: changeOf(), status: 200 } }), submitting, "respuesta de otro envío");
  assert.equal(grantChangeReducer(submitting, { type: "resolved", token: 1, result: { ok: true, data: changeOf(), status: 200 } }).step, "done");
  assert.equal(grantChangeReducer(submitting, { type: "resolved", token: 1, result: { ok: false, kind: "pair_not_offered", status: 409 } }).step, "failed");
  assert.equal(grantChangeReducer(confirming, { type: "close" }).step, "closed", "cancelar antes de enviar");
  assert.equal(grantChangeReducer(GRANT_CLOSED, { type: "open", target: target({ offered: false }) }), GRANT_CLOSED, "jamás se ofrece conceder un par no ofrecido");
  assert.equal(grantChangeReducer(GRANT_CLOSED, { type: "open", target: target({ offered: false, operation: "revoke" }) }).step, "confirming", "pero una concesión inerte sí se puede revocar");
});

const harness = (responder) => {
  const sent = [], states = [], settled = [];
  const client = { changeGrant: async (...args) => { sent.push(args.slice(0, 4)); return responder(...args); } };
  const controller = createGrantChangeController(client, (state) => states.push(state.step), (result, tgt) => settled.push({ result, tgt }));
  return { controller, sent, states, settled };
};
const ok = (o = {}) => ({ ok: true, data: changeOf(o), status: 200 });

test("controller: opening or cancelling the dialog sends nothing; confirming sends exactly once with the target fixed at opening", async () => {
  const { controller, sent, states, settled } = harness(async () => ok());
  controller.open(target());
  controller.close();
  assert.equal(sent.length, 0, "abrir y cancelar no envía nada");
  controller.open(target({ machineCode: "MP3", formCode: "VINTO-P1-02", userId: U2 }));
  await controller.confirm();
  assert.deepEqual(sent, [["grant", U2, "MP3", "VINTO-P1-02"]], "el objetivo es el capturado al abrir: ni otra máquina ni otro usuario");
  assert.deepEqual(states, ["confirming", "closed", "confirming", "submitting", "done"]);
  assert.equal(settled.length, 1, "se notifica una vez para releer el estado desde la API");
  assert.equal(settled[0].tgt.machineCode, "MP3");
});

test("controller: a double click is one request and the dialog cannot be re-confirmed while in flight", async () => {
  const gate = deferred();
  const { controller, sent } = harness(() => gate.promise);
  controller.open(target());
  const first = controller.confirm();
  const second = controller.confirm();
  controller.close();
  assert.equal(sent.length, 1);
  assert.equal(controller.state.step, "submitting");
  gate.resolve(ok());
  await Promise.all([first, second]);
  assert.equal(sent.length, 1);
  assert.equal(controller.state.step, "done");
});

test("controller: idempotence is reflected (unchanged result) and each failure is reported, with a network failure treated as UNCERTAIN", async () => {
  const unchanged = harness(async () => ok({ changed: false, request_id: null, operation: "grant", grant: row("MP1", "VINTO-P1-01") }));
  unchanged.controller.open(target());
  await unchanged.controller.confirm();
  assert.equal(unchanged.controller.state.change.changed, false);
  assert.match(grantResultText(unchanged.controller.state.change, "Operación DEV", "MP1", "VINTO-P1-01").text, /ya tenía concedido VINTO-P1-01 en MP1\. No se modificó nada/);
  for (const [kind, httpStatus] of [["session", 401], ["forbidden", 403], ["origin", 403], ["machine_not_found", 404], ["pair_not_offered", 409], ["invalid", 422], ["unsupported", 415], ["unavailable", 503]]) {
    const h = harness(async () => ({ ok: false, kind, status: httpStatus }));
    h.controller.open(target());
    await h.controller.confirm();
    assert.deepEqual([h.controller.state.step, h.controller.state.failure.kind], ["failed", kind]);
    assert.equal(h.settled.length, 1, `${kind}: se vuelve a leer el estado`);
    assert.equal(markUncertain(h.settled[0].result, U1)?.userId ?? null, kind === "unavailable" ? U1 : null, `${kind}: solo un fallo de red/503 es incierto`);
  }
  const thrown = harness(async () => { throw new Error("red caída"); });
  thrown.controller.open(target());
  await thrown.controller.confirm();
  assert.equal(thrown.controller.state.failure.kind, "unavailable");
  thrown.controller.open(target());
  assert.equal(thrown.controller.state.step, "confirming", "tras un fallo se puede volver a intentar");
});

test("controller: disposed while the request is in flight (user or session changed) -> the late outcome changes nothing and notifies nobody", async () => {
  const gate = deferred();
  const { controller, states, settled } = harness(() => gate.promise);
  controller.open(target());
  const pending = controller.confirm();
  const before = states.length;
  controller.dispose();
  gate.resolve({ ok: false, kind: "session", status: 401 });
  await pending;
  assert.equal(states.length, before, "ni estado nuevo");
  assert.equal(settled.length, 0, "ni 401 que cierre la sesión siguiente");
  const idle = harness(async () => ok());
  idle.controller.dispose();
  idle.controller.dispose();
  idle.controller.open(target());
  await idle.controller.confirm();
  assert.equal(idle.sent.length, 0, "un controlador liberado no envía");
});

// ---- 5. incertidumbre, bloqueo, relectura y vista por usuario ----

test("uncertainty: only a network failure or 503 is uncertain; it ends ONLY with a complete correct re-read of the SAME user; switching user drops it", () => {
  assert.equal(markUncertain({ ok: false, kind: "unavailable", status: 503 }, U1)?.userId, U1);
  assert.equal(markUncertain({ ok: false, kind: "pair_not_offered", status: 409 }, U1), null);
  assert.equal(markUncertain({ ok: true, data: 1, status: 200 }, U1), null);
  const pending = { userId: U1 };
  assert.equal(nextUncertainty(pending, U1, false), pending, "relectura en curso o fallida: sigue incierto");
  assert.equal(nextUncertainty(pending, U1, true), null, "relectura completa: se cierra");
  assert.equal(nextUncertainty(pending, U2, false), null, "otro usuario seleccionado: la incertidumbre del anterior no aplica");
  assert.equal(nextUncertainty(null, U1, false), null);
  assert.equal(isReread([{ status: "ready", refreshing: false }, { status: "ready", refreshing: false }]), true);
  assert.equal(isReread([{ status: "ready", refreshing: true }]), false, "aún relee");
  assert.equal(isReread([{ status: "error", refreshing: false }]), false, "una relectura fallida no confirma nada");
  assert.equal(isReread([{ status: "loading" }]), false);
});

test("actions are locked while blocked, uncertain, loading or re-reading, and open only when every needed read is ready", () => {
  const ready = { status: "ready", data: {}, refreshing: false };
  assert.equal(actionsLocked({ block: null, uncertain: false, views: [ready, ready] }), false);
  assert.equal(actionsLocked({ block: "forbidden", uncertain: false, views: [ready] }), true);
  assert.equal(actionsLocked({ block: "origin", uncertain: false, views: [ready] }), true);
  assert.equal(actionsLocked({ block: null, uncertain: true, views: [ready] }), true);
  assert.equal(actionsLocked({ block: null, uncertain: false, views: [ready, { ...ready, refreshing: true }] }), true);
  assert.equal(actionsLocked({ block: null, uncertain: false, views: [ready, { status: "loading" }] }), true);
  assert.equal(actionsLocked({ block: null, uncertain: false, views: [ready, { status: "error", kind: "unavailable", refreshing: false }] }), true);
  assert.equal(actionsLocked({ block: null, uncertain: false, views: [ready, { status: "idle" }] }), true);
});

test("after a result the user's reads are repeated; a 409 or a missing resource also refreshes the catalogues", () => {
  assert.deepEqual(refreshPlan({ ok: true, data: changeOf(), status: 200 }), { user: true, catalogs: false });
  for (const kind of ["pair_not_offered", "machine_not_found", "form_not_found", "not_found"]) assert.deepEqual(refreshPlan({ ok: false, kind, status: 409 }), { user: true, catalogs: true }, kind);
  for (const kind of ["unavailable", "forbidden", "invalid", "unsupported"]) assert.deepEqual(refreshPlan({ ok: false, kind, status: 503 }), { user: true, catalogs: false }, kind);
});

test("a late answer for the previously selected user never reaches the view of the current one (resource keys, feedback owner, uncertainty)", () => {
  const stored = { key: `grants:s1:${U1}`, attempt: 0, result: { ok: true, data: grants([row("MP1", "VINTO-P1-01")]) } };
  assert.equal(deriveResource(true, `grants:s1:${U1}`, 0, stored).status, "ready");
  assert.equal(deriveResource(true, `grants:s1:${U2}`, 0, stored).status, "loading", "otro usuario: jamás se muestran las concesiones del anterior");
  assert.equal(deriveResource(true, `grants:s2:${U1}`, 0, stored).status, "loading", "otra sesión tampoco");
  const feedback = { owner: U1, tone: "ok", text: "Acceso concedido" };
  assert.deepEqual(visibleFeedback(feedback, U1), { tone: "ok", text: "Acceso concedido" });
  assert.equal(visibleFeedback(feedback, U2), null);
  assert.equal(visibleFeedback(feedback, null), null);
  assert.equal(visibleFeedback(null, U1), null);
  assert.equal(nextUncertainty({ userId: U1 }, U2, false), null);
});

// ---- 6. textos ----

test("the confirmation names user, machine, form and operation, warns about the missing sector and the unapplied effect, and revoking keeps the history", () => {
  const grantText = grantConfirmationText(target({ machineName: "Máquina 1", formName: "Parámetros", sectorGranted: false, inert: ["sector_missing"] }));
  assert.deepEqual(grantText.lines.map((l) => [l.label, l.value]), [["Usuario", "Operación DEV"], ["Máquina", "MP1 · Máquina 1"], ["Formulario", "VINTO-P1-01 · Parámetros"], ["Operación", "Conceder"]]);
  assert.ok(grantText.warnings.includes(SECTOR_NOT_GRANTED_NOTICE));
  assert.ok(grantText.warnings.includes(NOT_EFFECTIVE_NOTICE));
  assert.ok(grantText.warnings.some((w) => /Concesión inerte/.test(w)));
  assert.match(grantText.body, /SOLO en esa máquina/);
  assert.equal(grantText.confirm, "Conceder acceso");
  const revokeText = grantConfirmationText(target({ operation: "revoke", inert: ["pair_not_offered"] }));
  assert.equal(revokeText.lines[3].value, "Revocar");
  assert.match(revokeText.body, /Las concesiones de otras máquinas no cambian/);
  assert.ok(revokeText.warnings.some((w) => /conserva el historial/.test(w)));
  assert.equal(revokeText.confirm, "Revocar acceso");
});

test("results say what happened: applied, unchanged (idempotent), inert and revoked; nothing claims effective access", () => {
  const label = "Operación DEV";
  assert.match(grantResultText(changeOf(), label, "MP1", "VINTO-P1-01").text, /Acceso concedido a Operación DEV: VINTO-P1-01 en MP1\. Queda registrado; todavía no se aplica a las capturas/);
  assert.equal(grantResultText(changeOf(), label, "MP1", "VINTO-P1-01").warning, null);
  const inert = grantResultText(changeOf({ context: context({ sector_granted: false }) }), label, "MP1", "VINTO-P1-01");
  assert.match(inert.warning, /Concesión inerte: el usuario no tiene concedido el sector/);
  assert.equal(grantResultText(changeOf({ changed: false, request_id: null }), label, "MP1", "VINTO-P1-01").tone, "info");
  const revoked = changeOf({ operation: "revoke", active: false, grant: revokedRow("MP1", "VINTO-P1-01") });
  assert.match(grantResultText(revoked, label, "MP1", "VINTO-P1-01").text, /Acceso revocado a Operación DEV: VINTO-P1-01 en MP1\. El registro anterior se conserva en el historial/);
  assert.match(grantResultText(changeOf({ operation: "revoke", active: false, changed: false, request_id: null, grant: null }), label, "MP1", "VINTO-P1-01").text, /no tenía concedido/);
  for (const change of [changeOf(), revoked]) assert.doesNotMatch(grantResultText(change, label, "MP1", "VINTO-P1-01").text, /efectiv/i);
});

// ---- 7. salvaguardas del código fuente ----

const SOURCES = ["lib/vinto/admin-grants.ts", "lib/vinto/admin-api.ts", "lib/vinto/use-admin.ts", "components/vinto/admin/admin-grants-parts.tsx", "components/vinto/admin/admin-console.tsx"];
const code = (file) => read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");

test("no new source stores credentials or permissions locally, reads cookies, sets Origin, falls back to demo data or sends authority fields", () => {
  for (const file of SOURCES) {
    assert.doesNotMatch(code(file), /localStorage|sessionStorage|document\.cookie|indexedDB|Authorization|["']Origin["']|credentials:\s*["']omit["']|\b[Dd]emo\b/, file);
  }
  const grants = code("lib/vinto/admin-grants.ts");
  assert.match(grants, /credentials/.test(code("lib/vinto/admin.ts")) ? /createAdminRequester/ : /x^/, "reutiliza el requester administrativo");
  assert.doesNotMatch(grants, /fetch\(/, "no abre otro canal de red");
  assert.doesNotMatch(grants, /actor_id/, "el frontend no conoce ni envía actor_id");
  assert.match(grants, /body: \{ machine_code: machineCode, form_code: formCode \}/, "el cuerpo enviado es exactamente machine_code y form_code");
  assert.equal([...grants.matchAll(/method: "POST"/g)].length, 1, "solo hay una escritura HTTP");
  assert.match(read("lib/vinto/admin.ts"), /credentials:\s*"include"/);
});

test("the application code contains no static list of machines or forms: everything comes from the API", () => {
  for (const file of ["lib/vinto/admin-grants.ts", "components/vinto/admin/admin-grants-parts.tsx", "components/vinto/admin/admin-console.tsx"]) {
    assert.doesNotMatch(code(file), /["'`](MP1|MP3|BELOIT|OVER|COPASA|PERICHUN|TUBETERA|GAMBINI|SINCRO_I+|OMET_I+|PANUELERA|WALLY)["'`]/, `${file}: sin códigos de máquina`);
    assert.doesNotMatch(code(file), /["'`]VINTO-P1-\d+["'`]/, `${file}: sin códigos de formulario`);
  }
});

test("wiring: the grants hook is released on unmount, the console reads only the seven documented endpoints and the access block includes the new reads", () => {
  const hook = read("lib/vinto/use-admin.ts");
  assert.match(hook, /createGrantChangeController\(grantsApi/);
  assert.match(hook, /created\.dispose\(\)/);
  const source = read("lib/vinto/admin-grants.ts");
  const urls = [...source.matchAll(/["'`](\/api\/admin\/[^"'`?$]*)/g)].map((m) => m[1]).sort();
  assert.deepEqual([...new Set(urls)], ["/api/admin/catalog", "/api/admin/catalog/forms", "/api/admin/users/"]);
  assert.match(source, /\/grants\/\$\{operation\}/);
  const consoleSource = read("components/vinto/admin/admin-console.tsx");
  assert.match(consoleSource, /grantsApi\.getMachineCatalog/);
  assert.match(consoleSource, /grantsApi\.getFormsCatalog/);
  assert.match(consoleSource, /grantsApi\.getUserDetail/);
  assert.match(consoleSource, /grantsApi\.getUserGrants\(/);
  assert.match(consoleSource, /grantsApi\.getUserGrantsHistory/);
  assert.match(consoleSource, /key=\{view\.user\.id\}|session = user\.id/);
  assert.match(consoleSource, /machines:\$\{session\}/, "las claves incluyen la sesión");
  assert.match(consoleSource, /grants:\$\{session\}:\$\{selectedId/, "y el usuario seleccionado");
});
