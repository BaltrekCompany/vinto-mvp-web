// node --test scripts/admin.test.mjs
// Administración de usuarios y concesiones por sector (M1-C2-b2): contratos y validadores, cliente HTTP (fetch inyectado), reglas de selección,
// máquina de estados de la operación, controlador (confirmación, doble envío, respuestas tardías) y derivación de recursos (sesión/usuario cambiados).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ADMIN_USERS_MAX, CLOSED, FAILURE_MESSAGES, INERT_NOTICE, canAdminister, changeReducer, confirmationText, createAdminClient, createChangeController, deriveResource,
  failureKind, filterUsers, grantableSectors, isLimited, loadResource, parseAdminSectors, parseAdminUsers, parseSectorChange, parseUserSectors, resultText, revocableSectors,
  sectorBadges, summarize, adminScreen, deriveAccess, BLOCK_TITLES, blockMessage,
} from "../lib/vinto/admin.ts";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const ID_A = "11111111-1111-4111-8111-111111111111", ID_B = "22222222-2222-4222-8222-222222222222", ID_C = "33333333-3333-4333-8333-333333333333";
const BOBINAS = { code: "BOBINAS", name: "Bobinas", active: true, operational: true };
const REBOBINADO = { code: "REBOBINADO", name: "Rebobinado", active: true, operational: false };
const CONVERSION = { code: "CONVERSION", name: "Conversión", active: false, operational: false };
const user = (o = {}) => ({ id: ID_A, username: "dev.jefatura", display_name: "Jefatura DEV", active: true, profiles: ["JEFATURA"], sectors: [BOBINAS], ...o });
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => { if (body === undefined) throw new SyntaxError("sin cuerpo"); return body; } });
const change = (o = {}) => ({ user_id: ID_A, sector_code: "REBOBINADO", operation: "grant", changed: true, sector: REBOBINADO, granted_sectors: [BOBINAS, REBOBINADO], request_id: "admin-sector-grant:abc", ...o });
const recorder = (responder) => { const calls = []; const fetchImpl = async (url, init) => { calls.push({ url, init }); return responder(url, init, calls.length); }; return { fetchImpl, calls }; };
const clientWith = (responder) => { const rec = recorder(responder); return { client: createAdminClient(() => "http://api.test", rec.fetchImpl), calls: rec.calls }; };
const failureOf = async (promise) => { const result = await promise; assert.equal(result.ok, false); return result; };
const target = (o = {}) => ({ operation: "grant", userId: ID_A, userLabel: "Jefatura DEV", sector: REBOBINADO, ...o });
const tick = () => new Promise((resolve) => setImmediate(resolve));

// ---- validadores -------------------------------------------------------------------------------------------------------------------------

test("sectors: a valid catalogue parses and every inconsistent one is rejected", () => {
  assert.deepEqual(parseAdminSectors([BOBINAS, REBOBINADO, CONVERSION]), [BOBINAS, REBOBINADO, CONVERSION]);
  assert.deepEqual(parseAdminSectors([]), []);
  const bad = [null, {}, "x", [null], [{ ...BOBINAS, code: "bobinas" }], [{ ...BOBINAS, name: "" }], [{ ...BOBINAS, active: "yes" }], [{ ...BOBINAS, operational: 1 }],
    [{ ...CONVERSION, operational: true }], [BOBINAS, BOBINAS], [{ code: "X" }], [{ ...BOBINAS, code: "B".repeat(40) }]];
  for (const payload of bad) assert.equal(parseAdminSectors(payload), null, JSON.stringify(payload));
});

test("users: valid users parse, extra fields are dropped and malformed ones are rejected", () => {
  const parsed = parseAdminUsers([user(), user({ id: ID_B, username: null, display_name: "Sin acceso", active: false, profiles: [], sectors: [] })]);
  assert.equal(parsed.length, 2);
  assert.equal(parsed[1].username, null);
  assert.deepEqual(Object.keys(parseAdminUsers([{ ...user(), password_hash: "x", token: "y" }])[0]).sort(), ["active", "display_name", "id", "profiles", "sectors", "username"]);
  const bad = [null, {}, [null], [user({ id: "no-es-uuid" })], [user({ display_name: 5 })], [user({ active: "si" })], [user({ profiles: [1] })], [user({ profiles: "JEFATURA" })],
    [user({ sectors: [{ code: "bobinas" }] })], [user({ username: 7 })], [user(), user()], [user({ sectors: "BOBINAS" })]];
  for (const payload of bad) assert.equal(parseAdminUsers(payload), null, JSON.stringify(payload));
});

test("user sectors and changes: shape and consistency are enforced (idempotence, audit id, final state)", () => {
  assert.deepEqual(parseUserSectors({ user_id: ID_A, username: "u", active: true, sectors: [BOBINAS] }), { user_id: ID_A, username: "u", active: true, sectors: [BOBINAS] });
  for (const payload of [null, {}, { user_id: ID_A, username: "u", active: true }, { user_id: "x", username: "u", active: true, sectors: [] }, { user_id: ID_A, username: "u", active: 1, sectors: [] }]) {
    assert.equal(parseUserSectors(payload), null);
  }
  assert.equal(parseSectorChange(change()).changed, true);
  assert.equal(parseSectorChange(change({ changed: false, request_id: null })).request_id, null, "an idempotent repetition carries no audit id");
  assert.equal(parseSectorChange(change({ operation: "revoke", granted_sectors: [BOBINAS] })).operation, "revoke");
  const bad = [null, change({ operation: "delete" }), change({ changed: "yes" }), change({ changed: true, request_id: null }), change({ changed: false, request_id: "x" }), change({ request_id: "" }),
    change({ user_id: "nope" }), change({ sector_code: "rebobinado" }), change({ sector: BOBINAS }), change({ granted_sectors: [BOBINAS] }), // grant whose final state lacks the sector
    change({ operation: "revoke" }), // revoke whose final state still holds it
    change({ granted_sectors: [BOBINAS, BOBINAS, REBOBINADO] })];
  for (const payload of bad) assert.equal(parseSectorChange(payload), null, JSON.stringify(payload));
});

// ---- cliente HTTP ------------------------------------------------------------------------------------------------------------------------

test("reads: GET with the session cookie (credentials include), no cache, no body, no identity headers and no Origin", async () => {
  const { client, calls } = clientWith((url) => url.includes("/sectors") && !url.includes("/users/") ? reply(200, [BOBINAS]) : url.includes("/users/") ? reply(200, { user_id: ID_A, username: "u", active: true, sectors: [BOBINAS] }) : reply(200, [user()]));
  assert.equal((await client.listUsers()).ok, true);
  assert.equal((await client.listSectors()).ok, true);
  assert.equal((await client.getUserSectors(ID_A)).ok, true);
  assert.deepEqual(calls.map((c) => c.url), [`http://api.test/api/admin/users?limit=${ADMIN_USERS_MAX}`, "http://api.test/api/admin/sectors", `http://api.test/api/admin/users/${ID_A}/sectors`]);
  for (const { init } of calls) {
    assert.equal(init.method, "GET");
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    assert.equal(init.body, undefined);
    assert.equal(init.headers, undefined, "no Authorization/Origin/Cookie/X-* headers are set by the client");
  }
});

test("changes: POST JSON with only sector_code; actor, user and scope never travel in the body", async () => {
  const { client, calls } = clientWith((url) => reply(200, change({ operation: url.endsWith("revoke") ? "revoke" : "grant", changed: true, granted_sectors: url.endsWith("revoke") ? [BOBINAS] : [BOBINAS, REBOBINADO] })));
  const granted = await client.changeSector("grant", ID_A, "REBOBINADO");
  const revoked = await client.changeSector("revoke", ID_A, "REBOBINADO");
  assert.equal(granted.ok && revoked.ok, true);
  assert.deepEqual(calls.map((c) => c.url), [`http://api.test/api/admin/users/${ID_A}/sectors/grant`, `http://api.test/api/admin/users/${ID_A}/sectors/revoke`]);
  for (const { init } of calls) {
    assert.equal(init.method, "POST");
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    assert.deepEqual(init.headers, { "Content-Type": "application/json" });
    assert.deepEqual(JSON.parse(init.body), { sector_code: "REBOBINADO" });
  }
});

test("statuses are told apart: 401 session, 403 permission (not session), 404, 415, 422 and 503/network", async () => {
  const cases = [[401, undefined, "session"], [403, undefined, "forbidden"], [403, "ORIGIN_NOT_ALLOWED", "origin"], [404, "USER_NOT_FOUND", "user_not_found"], [404, "SECTOR_NOT_FOUND", "sector_not_found"],
    [404, undefined, "not_found"], [415, "UNSUPPORTED_MEDIA_TYPE", "unsupported"], [422, "SECTOR_INACTIVE", "sector_inactive"], [422, undefined, "invalid"], [503, undefined, "unavailable"], [500, undefined, "unavailable"], [502, undefined, "unavailable"]];
  for (const [status, code, kind] of cases) {
    const { client } = clientWith(() => reply(status, code ? { detail: "texto del servidor", code } : { detail: "texto del servidor" }));
    for (const result of [await failureOf(client.listUsers()), await failureOf(client.changeSector("grant", ID_A, "BOBINAS"))]) {
      assert.deepEqual([result.kind, result.status], [kind, status], `${status} ${code}`);
      assert.ok(!JSON.stringify(result).includes("texto del servidor"), "the server body is never surfaced");
    }
    assert.equal(failureKind(status, code), kind);
  }
  const offline = clientWith(() => { throw new TypeError("fetch failed"); }).client;
  assert.deepEqual(await failureOf(offline.listSectors()), { ok: false, kind: "unavailable", status: 0 });
  assert.deepEqual(await failureOf(offline.changeSector("revoke", ID_A, "BOBINAS")), { ok: false, kind: "unavailable", status: 0 });
  assert.ok(Object.values(FAILURE_MESSAGES).every((message) => typeof message === "string" && message.length > 10));
  assert.notEqual(FAILURE_MESSAGES.forbidden, FAILURE_MESSAGES.session);
});

test("an aborted request is rethrown so a stale response can be dropped silently", async () => {
  const { client } = clientWith(() => { throw new DOMException("aborted", "AbortError"); });
  await assert.rejects(client.listUsers(), (error) => error.name === "AbortError");
});

test("invalid or mismatching responses are never treated as success; malformed ids send nothing", async () => {
  const bodies = [undefined, null, {}, "x", [{ nope: 1 }]];
  for (const body of bodies) {
    const { client } = clientWith(() => reply(200, body));
    assert.equal((await failureOf(client.listUsers())).kind, "unavailable");
    assert.equal((await failureOf(client.listSectors())).kind, "unavailable");
  }
  const wrong = [change({ user_id: ID_B }), change({ sector_code: "BOBINAS", sector: BOBINAS, granted_sectors: [BOBINAS] }), change({ operation: "revoke", granted_sectors: [BOBINAS] })];
  for (const payload of wrong) assert.equal((await failureOf(clientWith(() => reply(200, payload)).client.changeSector("grant", ID_A, "REBOBINADO"))).kind, "unavailable");
  const { client, calls } = clientWith(() => reply(200, change()));
  for (const result of [await client.changeSector("grant", "../../x", "BOBINAS"), await client.changeSector("grant", ID_A, "bobinas; DROP"), await client.getUserSectors("nope")]) {
    assert.deepEqual([result.ok, result.kind], [false, "invalid"]);
  }
  assert.equal(calls.length, 0, "no request is made with malformed identifiers");
});

// ---- permisos y reglas de vista ------------------------------------------------------------------------------------------------------------

test("only the user.manage permission opens the administration, whatever the profiles are", () => {
  assert.equal(canAdminister({ permissions: ["catalog.read", "user.manage"], profiles: ["DATA_BALTREK"] }), true);
  assert.equal(canAdminister({ permissions: ["user.manage", "work_order.manage"], profiles: ["JEFATURA", "DATA_BALTREK"] }), true, "user.manage plus an operational profile still reaches /admin");
  assert.equal(canAdminister({ permissions: ["catalog.read", "catalog.manage"], profiles: ["DATA_BALTREK"] }), false, "the profile name alone is not authority");
  assert.equal(canAdminister({ permissions: ["work_order.manage", "assignment.manage"], profiles: ["JEFATURA"] }), false);
  assert.equal(canAdminister({ permissions: [] }), false);
  assert.equal(canAdminister(null), false);
  assert.equal(canAdminister(undefined), false);
});

test("local search works only on the retrieved users and understands accents, several terms and profiles", () => {
  const users = [user(), user({ id: ID_B, username: "dev.supervision", display_name: "Supervisión DEV", profiles: ["SUPERVISION"] }), user({ id: ID_C, username: "dev.data", display_name: "Data Baltrek", profiles: ["DATA_BALTREK"] })];
  assert.equal(filterUsers(users, "").length, 3);
  assert.deepEqual(filterUsers(users, "supervision").map((u) => u.id), [ID_B]);
  assert.deepEqual(filterUsers(users, "SUPERVISIÓN dev").map((u) => u.id), [ID_B]);
  assert.deepEqual(filterUsers(users, "data baltrek").map((u) => u.id), [ID_C], "the profile code DATA_BALTREK is searchable as words");
  assert.deepEqual(filterUsers(users, "jefatura").map((u) => u.id), [ID_A]);
  assert.deepEqual(filterUsers(users, "no-existe"), []);
  assert.deepEqual(filterUsers(users, "   "), users);
  assert.equal(filterUsers(users, "x").every((u) => users.includes(u)), true, "never returns a user that was not retrieved");
});

test("summary counts what was retrieved and flags a result limited by the API maximum", () => {
  const users = [user(), user({ id: ID_B, active: false, sectors: [BOBINAS, REBOBINADO] })];
  assert.deepEqual(summarize(users, [BOBINAS, REBOBINADO, CONVERSION]), { users: 2, activeUsers: 1, grants: 3, operationalSectors: 1, limited: false });
  const many = Array.from({ length: ADMIN_USERS_MAX }, (_, i) => user({ id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}` }));
  assert.equal(summarize(many, []).limited, true);
  assert.equal(isLimited(ADMIN_USERS_MAX - 1), false);
  assert.equal(isLimited(ADMIN_USERS_MAX), true);
});

test("grantable sectors are the active ones not yet granted; revocable ones include inactive grants; granted, active and operational are different badges", () => {
  const catalog = [BOBINAS, REBOBINADO, CONVERSION];
  assert.deepEqual(grantableSectors(catalog, [BOBINAS]).map((s) => s.code), ["REBOBINADO"], "an inactive sector is never offered and a granted one is not offered again");
  assert.deepEqual(grantableSectors(catalog, []).map((s) => s.code), ["BOBINAS", "REBOBINADO"]);
  assert.deepEqual(grantableSectors(catalog, [BOBINAS, REBOBINADO]), []);
  assert.deepEqual(grantableSectors([], []), []);
  assert.deepEqual(revocableSectors([CONVERSION, BOBINAS]).map((s) => s.code), ["CONVERSION", "BOBINAS"], "an old grant on an inactive sector can still be removed");
  assert.deepEqual(sectorBadges(BOBINAS).map((b) => b.text), ["Activo", "Operativo"]);
  assert.deepEqual(sectorBadges(REBOBINADO).map((b) => [b.text, b.tone]), [["Activo", "ok"], ["No operativo", "warn"]]);
  assert.deepEqual(sectorBadges(CONVERSION).map((b) => b.text), ["Inactivo", "No operativo"]);
});

// ---- máquina de estados y controlador ------------------------------------------------------------------------------------------------------

test("reducer: nothing is submitted without opening and confirming; a second submit, a late response and a close while sending do nothing", () => {
  assert.deepEqual(changeReducer(CLOSED, { type: "submit", token: 1 }), CLOSED, "no confirmation, no submission");
  const open = changeReducer(CLOSED, { type: "open", target: target() });
  assert.equal(open.step, "confirming");
  const sending = changeReducer(open, { type: "submit", token: 1 });
  assert.deepEqual([sending.step, sending.token], ["submitting", 1]);
  assert.equal(changeReducer(sending, { type: "submit", token: 2 }), sending, "double submit");
  assert.equal(changeReducer(sending, { type: "close" }), sending, "cannot dismiss while sending");
  assert.equal(changeReducer(sending, { type: "open", target: target({ userId: ID_B }) }), sending, "cannot open another operation while sending");
  assert.equal(changeReducer(sending, { type: "resolved", token: 99, result: { ok: true, data: change(), status: 200 } }), sending, "late response of another submission");
  assert.equal(changeReducer(open, { type: "resolved", token: 1, result: { ok: true, data: change(), status: 200 } }), open, "a response without a submission");
  const done = changeReducer(sending, { type: "resolved", token: 1, result: { ok: true, data: change(), status: 200 } });
  assert.deepEqual([done.step, done.change.changed], ["done", true]);
  const failed = changeReducer(sending, { type: "resolved", token: 1, result: { ok: false, kind: "forbidden", status: 403 } });
  assert.deepEqual([failed.step, failed.failure.kind], ["failed", "forbidden"]);
  assert.equal(changeReducer(done, { type: "close" }).step, "closed");
  assert.equal(changeReducer(sending, { type: "reset" }).step, "closed");
  assert.equal(changeReducer(CLOSED, { type: "open", target: target({ operation: "grant", sector: CONVERSION }) }).step, "closed", "granting an inactive sector is never offered");
  assert.equal(changeReducer(CLOSED, { type: "open", target: target({ operation: "revoke", sector: CONVERSION }) }).step, "confirming", "revoking an inactive one is");
});

const harness = (responder) => {
  const calls = [], states = [], settled = [];
  const client = { changeSector: async (...args) => { calls.push(args); return responder(...args); } };
  const controller = createChangeController(client, (s) => states.push(s.step), (r) => settled.push(r));
  return { controller, calls, states, settled };
};

test("controller: opening the dialog sends nothing; confirming sends exactly once and reports the outcome", async () => {
  const h = harness(async () => ({ ok: true, data: change(), status: 200 }));
  h.controller.open(target());
  await tick();
  assert.equal(h.calls.length, 0, "selecting an operation never changes anything by itself");
  assert.equal(h.controller.state.step, "confirming");
  h.controller.close();
  assert.equal(h.controller.state.step, "closed");
  await h.controller.confirm();
  assert.equal(h.calls.length, 0, "confirm without an open dialog does nothing");
  h.controller.open(target());
  await h.controller.confirm();
  assert.deepEqual(h.calls.map((call) => call.slice(0, 3)), [["grant", ID_A, "REBOBINADO"]]);
  assert.equal(h.calls[0][3].aborted, false, "an active controller passes a live abort signal (aborted only on dispose)");
  assert.equal(h.controller.state.step, "done");
  assert.deepEqual(h.states, ["confirming", "closed", "confirming", "submitting", "done"]);
  assert.equal(h.settled.length, 1);
  assert.equal(h.settled[0].ok, true);
});

test("controller: a double click is one request, and the dialog cannot be closed or re-confirmed while it is in flight", async () => {
  let release;
  const h = harness(() => new Promise((resolve) => { release = () => resolve({ ok: true, data: change({ changed: false, request_id: null }), status: 200 }); }));
  h.controller.open(target());
  const first = h.controller.confirm();
  const second = h.controller.confirm();
  const third = h.controller.confirm();
  h.controller.close();
  h.controller.open(target({ userId: ID_B }));
  assert.equal(h.controller.state.step, "submitting");
  assert.equal(h.calls.length, 1, "double submission is blocked");
  release();
  await Promise.all([first, second, third]);
  assert.equal(h.calls.length, 1);
  assert.equal(h.controller.state.step, "done");
  assert.equal(h.controller.state.change.changed, false, "an unchanged state is reported as such");
});

test("controller: failures are reported, an unknown network outcome still triggers a re-read, and the operation can be repeated afterwards", async () => {
  for (const [responder, kind] of [[async () => ({ ok: false, kind: "forbidden", status: 403 }), "forbidden"], [async () => { throw new Error("boom"); }, "unavailable"], [async () => ({ ok: false, kind: "sector_inactive", status: 422 }), "sector_inactive"]]) {
    const h = harness(responder);
    h.controller.open(target());
    await h.controller.confirm();
    assert.deepEqual([h.controller.state.step, h.controller.state.failure.kind], ["failed", kind]);
    assert.equal(h.settled.length, 1, "the caller always re-reads the central state after a response, success or not");
    h.controller.close();
    h.controller.open(target());
    await h.controller.confirm();
    assert.equal(h.calls.length, 2, "a rejected operation can be confirmed again by the user");
  }
});

test("controller: a response that arrives after a reset (user or session changed) never overwrites the new state", async () => {
  let release;
  const h = harness(() => new Promise((resolve) => { release = () => resolve({ ok: true, data: change(), status: 200 }); }));
  h.controller.open(target());
  const pending = h.controller.confirm();
  h.controller.reset(); // the session or the selected user changed while the request was in flight
  assert.equal(h.controller.state.step, "closed");
  h.controller.open(target({ userId: ID_B, userLabel: "Otro" }));
  release();
  await pending;
  assert.equal(h.controller.state.step, "confirming", "the late response of the previous submission is ignored");
  assert.equal(h.controller.state.target.userId, ID_B);
  assert.equal(h.settled.length, 1, "the central state is still re-read");
  h.controller.dispose();
  h.controller.close();
  assert.equal(h.states.at(-1), "confirming", "a disposed controller no longer notifies");
});

// ---- recursos: sesión y usuario cambiados ----------------------------------------------------------------------------------------------------

test("deriveResource never shows data stored for another session or user", () => {
  const stored = { key: "detail:s1:A", attempt: 0, result: { ok: true, data: { sectors: [BOBINAS] } } };
  assert.equal(deriveResource(false, "detail:s1:A", 0, stored).status, "idle");
  assert.equal(deriveResource(true, "detail:s1:A", 0, null).status, "loading");
  assert.deepEqual(deriveResource(true, "detail:s1:A", 0, stored), { status: "ready", data: stored.result.data, refreshing: false });
  assert.equal(deriveResource(true, "detail:s1:A", 1, stored).refreshing, true, "re-reading keeps the previous data flagged as refreshing");
  assert.equal(deriveResource(true, "detail:s1:B", 0, stored).status, "loading", "another user");
  assert.equal(deriveResource(true, "detail:s2:A", 0, stored).status, "loading", "another session");
  assert.deepEqual(deriveResource(true, "k", 0, { key: "k", attempt: 0, result: { ok: false, kind: "forbidden" } }), { status: "error", kind: "forbidden", refreshing: false });
});

test("loadResource: aborted (stale) loads are dropped, a 401 is reported once and errors are stored", async () => {
  const stored = [];
  let unauthorized = 0;
  const store = (value) => stored.push(value);
  const slow = new AbortController();
  let finishSlow;
  const staleLoad = loadResource(() => new Promise((resolve) => { finishSlow = () => resolve({ ok: true, data: "A", status: 200 }); }), slow.signal, "detail:A", 0, store, () => { unauthorized += 1; });
  slow.abort(); // the user selected somebody else: the cleanup aborts the previous request
  const fresh = new AbortController();
  await loadResource(async () => ({ ok: true, data: "B", status: 200 }), fresh.signal, "detail:B", 0, store, () => { unauthorized += 1; });
  finishSlow();
  await staleLoad;
  assert.deepEqual(stored.map((s) => [s.key, s.result.data]), [["detail:B", "B"]], "the late answer of the previous user is not stored");
  await loadResource(async () => ({ ok: false, kind: "session", status: 401 }), fresh.signal, "k", 0, store, () => { unauthorized += 1; });
  assert.equal(unauthorized, 1);
  assert.deepEqual(stored.at(-1).result, { ok: false, kind: "session" });
  await loadResource(async () => { throw new Error("x"); }, fresh.signal, "k2", 0, store, () => { unauthorized += 1; });
  assert.deepEqual(stored.at(-1).result, { ok: false, kind: "unavailable" });
  const aborted = new AbortController();
  aborted.abort();
  const before = stored.length;
  await loadResource(async () => { throw new Error("late"); }, aborted.signal, "k3", 0, store, () => { unauthorized += 1; });
  await loadResource(async () => ({ ok: false, kind: "session", status: 401 }), aborted.signal, "k4", 0, store, () => { unauthorized += 1; });
  assert.equal(stored.length, before);
  assert.equal(unauthorized, 1, "an aborted load never reports a session loss");
});

// ---- textos --------------------------------------------------------------------------------------------------------------------------------

test("the confirmation explains what will happen; revoking warns about the immediate effect and an inert grant says so", () => {
  const grant = confirmationText(target());
  assert.match(grant.title, /Conceder/);
  assert.match(grant.body, /Jefatura DEV/);
  assert.match(grant.body, /Rebobinado \(REBOBINADO\)/);
  assert.equal(grant.warning, INERT_NOTICE, "a non operational sector warns that the grant is inert");
  assert.equal(confirmationText(target({ sector: BOBINAS })).warning, undefined);
  const revoke = confirmationText(target({ operation: "revoke", sector: BOBINAS }));
  assert.match(revoke.body, /inmediato/);
  assert.match(revoke.body, /sesión abierta/);
  assert.match(revoke.warning, /auditada/);
});

test("results say what happened: applied, unchanged (idempotent) or inert", () => {
  assert.match(resultText(change(), "Ana").text, /concedido a Ana/);
  assert.match(resultText(change(), "Ana").text, /inerte/);
  assert.equal(resultText(change({ changed: false, request_id: null }), "Ana").tone, "info");
  assert.match(resultText(change({ changed: false, request_id: null }), "Ana").text, /ya tenía acceso/);
  assert.match(resultText(change({ operation: "revoke", granted_sectors: [BOBINAS] }), "Ana").text, /revocado a Ana/);
  assert.match(resultText(change({ operation: "revoke", changed: false, request_id: null, granted_sectors: [BOBINAS] }), "Ana").text, /no tenía acceso/);
});

// ---- credenciales y cableado -----------------------------------------------------------------------------------------------------------------

test("no administrative source stores credentials, reads cookies, sets Origin or falls back to local/demo data", () => {
  for (const file of ["lib/vinto/admin.ts", "lib/vinto/admin-api.ts", "lib/vinto/use-admin.ts", "components/vinto/admin/admin-console.tsx", "components/vinto/admin/admin-parts.tsx", "components/vinto/admin/admin-access.tsx", "app/admin/page.tsx"]) {
    const source = read(file).replace(/\/\/.*$/gm, ""); // comments may explain what is NOT done
    assert.doesNotMatch(source, /localStorage|sessionStorage|document\.cookie|indexedDB|Authorization|["']Origin["']|credentials:\s*["']omit["']|\b[Dd]emo\b/, file);
  }
  assert.match(read("lib/vinto/admin.ts"), /credentials:\s*"include"/);
});

test("wiring: the page decides by session and permission before mounting the console; the console is keyed by user; entry points use the permission", () => {
  const page = read("app/admin/page.tsx");
  assert.ok(page.indexOf("adminScreen(view, loggingOut)") < page.indexOf("<AdminConsole"), "the screen (session + permission + logout) is decided before the console (and its requests) exists");
  assert.match(page, /screen === "closing"\) return <AuthChecking label="Cerrando sesión…"\/>/, "while logging out the console is unmounted");
  assert.match(page, /screen === "checking"\) return <AuthChecking\/>/);
  assert.match(page, /screen === "unavailable"\) return <AuthUnavailable onRetry/);
  assert.match(page, /view\.status !== "authenticated"\) return <Login/);
  assert.match(page, /screen === "denied"\) return <AdminDenied/);
  assert.match(page, /<AdminConsole key=\{view\.user\.id\}/);
  const technical = read("components/vinto/technical-view.tsx");
  assert.match(technical, /canAdminister\(user\)/);
  assert.doesNotMatch(technical, /profiles\.includes\("DATA_BALTREK"\)/);
  assert.match(technical, /href="\/admin"/);
  assert.match(read("app/page.tsx"), /hasPermission\(user, "user\.manage"\) && <a href="\/admin"/);
});

test("wiring of the confirmation dialog: it cannot be dismissed while sending, the confirm button is disabled while pending and nothing is sent from the list or the detail buttons", () => {
  const parts = read("components/vinto/admin/admin-parts.tsx");
  assert.match(parts, /onOpenChange=\{\(next\) => \{ if \(!next && !pending\) onClose\(\); \}\}/);
  assert.match(parts, /disabled=\{pending\} onClick=\{onConfirm\}/);
  assert.match(parts, /pending \? "Aplicando…" : text\.confirm/);
  assert.doesNotMatch(parts, /adminApi|fetch\(|changeSector/, "presentational components never call the API");
  const consoleSource = read("components/vinto/admin/admin-console.tsx");
  assert.match(consoleSource, /onGrant=\{\(sector\) => props\.onOpen\("grant", sector\)\}/);
  assert.match(consoleSource, /change\.open\(\{ operation, userId: selected\.id/, "buttons only OPEN the dialog");
  assert.match(consoleSource, /users\.refresh\(\); detail\.refresh\(\)/, "the central state is re-read after every response");
  assert.match(consoleSource, /result\.kind === "session"\) \{ onSessionLost\(\)/);
  assert.match(consoleSource, /result\.kind === "forbidden" \|\| result\.kind === "origin"\)\) setChangeFailure\(result\.kind\)/);
  assert.match(consoleSource, /deriveAccess\(\[users\.view, catalog\.view, detail\.view, machines\.view, forms\.view, userDetail\.view, grants\.view, history\.view\], changeFailure\)/, "users, catalogue and detail all feed the access block");
  assert.match(parts, /state\.failure\.kind === "origin" \? BLOCK_TITLES\.origin/, "the failed-operation dialog names an unauthorised origin correctly");
});

// ---- PR #20: controlador liberado, logout y bloqueo por 403 --------------------------------------------------------------------------------------------

const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const pendingHarness = () => {
  const pending = deferred(), calls = [], states = [], settled = [], sessionLost = [];
  const client = { changeSector: (...args) => { calls.push(args); return pending.promise; } };
  const controller = createChangeController(client, (s) => states.push(s.step), (r) => { settled.push(r); if (!r.ok && r.kind === "session") sessionLost.push(1); });
  return { controller, pending, calls, states, settled, sessionLost };
};

test("A) a 401 that arrives after the console was unmounted never reaches the callbacks, so it cannot close the NEXT session", async () => {
  const old = pendingHarness();
  old.controller.open(target());
  const inFlight = old.controller.confirm();
  old.controller.dispose(); // the console unmounts (logout, user change) while the POST is pending
  assert.equal(old.calls[0][3].aborted, true, "the pending request is aborted on unmount");
  // a NEW session mounts its own controller and starts working
  const next = harness(async () => ({ ok: true, data: change(), status: 200 }));
  next.controller.open(target({ userId: ID_B }));
  const statesBefore = [...next.states];
  old.pending.resolve({ ok: false, kind: "session", status: 401 }); // the late 401 of the OLD session
  await inFlight;
  assert.deepEqual(old.settled, [], "no callback of the old controller runs");
  assert.deepEqual(old.sessionLost, [], "onSessionLost is never triggered by the old session");
  assert.deepEqual(old.states, ["confirming", "submitting"], "the old administrative state is not published after disposal");
  assert.deepEqual(next.states, statesBefore);
  assert.equal(next.controller.state.step, "confirming", "the new session is intact");
  assert.equal(next.settled.length, 0);
});

test("B) a 200 that arrives after unmount changes nothing in the new interface; the controller does not presume what the server did", async () => {
  const old = pendingHarness();
  old.controller.open(target());
  const inFlight = old.controller.confirm();
  old.controller.dispose();
  old.pending.resolve({ ok: true, data: change(), status: 200 }); // the server may well have applied it: aborting a POST guarantees nothing
  await inFlight;
  assert.deepEqual([old.settled.length, old.states.at(-1)], [0, "submitting"], "no state, no re-read callback from a disposed controller");
  assert.equal(old.controller.state.step, "submitting", "it keeps no verdict about the operation: the new console reads the central API again");
  const fresh = harness(async () => ({ ok: true, data: change({ changed: false, request_id: null }), status: 200 }));
  fresh.controller.open(target());
  await fresh.controller.confirm();
  assert.equal(fresh.controller.state.step, "done");
  assert.equal(fresh.settled.length, 1, "a controller that is still active keeps the normal reconciliation");
});

test("C) logout during a pending request: the console is gone while closing and the late outcome cannot alter the next session", async () => {
  assert.equal(adminScreen({ status: "authenticated", user: { permissions: ["user.manage"] } }, true), "closing", "even with a still-valid session, the console is not shown while logging out");
  assert.equal(adminScreen({ status: "authenticated", user: { permissions: ["user.manage"] } }, false), "console");
  const old = pendingHarness();
  old.controller.open(target());
  const inFlight = old.controller.confirm();
  await old.controller.confirm();
  assert.equal(old.calls.length, 1, "no new operation can start meanwhile");
  old.controller.dispose(); // the page renders "Cerrando sesión…" and unmounts the console
  old.controller.open(target({ userId: ID_B }));
  await old.controller.confirm();
  assert.equal(old.calls.length, 1, "a disposed controller cannot start operations either");
  old.pending.resolve({ ok: false, kind: "session", status: 401 });
  await inFlight;
  assert.deepEqual([old.settled.length, old.sessionLost.length], [0, 0]);
});

test("H) a 401 of an operation on an ACTIVE controller still reports the session loss normally and keeps the failure", async () => {
  const h = pendingHarness();
  h.controller.open(target());
  const inFlight = h.controller.confirm();
  h.pending.resolve({ ok: false, kind: "session", status: 401 });
  await inFlight;
  assert.deepEqual(h.sessionLost, [1], "the page is told to go back to the Login");
  assert.deepEqual([h.controller.state.step, h.controller.state.failure.kind], ["failed", "session"]);
  assert.equal(h.settled.length, 1);
});

test("a controller disposed before sending never sends, and dispose is idempotent", async () => {
  const h = pendingHarness();
  h.controller.open(target());
  h.controller.dispose();
  h.controller.dispose();
  await h.controller.confirm();
  assert.equal(h.calls.length, 0, "a disposed controller never sends anything");
  assert.equal(h.settled.length, 0);
});

test("deriveAccess: a 403 on ANY read or on a change blocks the actions, an unauthorised origin is told apart, and a 401 never blocks", () => {
  const ready = { status: "ready" }, loading = { status: "loading" }, idle = { status: "idle" };
  const err = (kind) => ({ status: "error", kind });
  assert.equal(deriveAccess([ready, ready, ready], null), null);
  assert.equal(deriveAccess([loading, idle, ready], null), null);
  assert.equal(deriveAccess([err("forbidden"), ready, idle], null), "forbidden", "D) users list 403");
  assert.equal(deriveAccess([ready, err("forbidden"), ready], null), "forbidden", "E) catalogue 403 while users and detail exist");
  assert.equal(deriveAccess([ready, ready, err("forbidden")], null), "forbidden", "F) user detail 403");
  assert.equal(deriveAccess([ready, ready, ready], "forbidden"), "forbidden", "a 403 on a change");
  assert.equal(deriveAccess([ready, ready, ready], "origin"), "origin", "G) ORIGIN_NOT_ALLOWED on a change");
  assert.equal(deriveAccess([ready, err("forbidden"), ready], "origin"), "origin", "the unauthorised origin is the more specific cause");
  for (const kind of ["session", "unavailable", "not_found", "user_not_found", "sector_not_found", "invalid", "sector_inactive", "unsupported"]) {
    assert.equal(deriveAccess([err(kind), err(kind), err(kind)], kind), null, `${kind} must not block the actions as if it were a permission problem`);
  }
  assert.notEqual(BLOCK_TITLES.origin, BLOCK_TITLES.forbidden);
  assert.match(blockMessage("origin"), /dirección no está autorizada/);
  assert.match(blockMessage("forbidden"), /No tienes permiso/);
  assert.doesNotMatch(`${blockMessage("origin")} ${blockMessage("forbidden")}`, /sesión ya no es válida/);
});

test("adminScreen: closing wins over everything; session, permission and availability decide the rest", () => {
  const manager = { status: "authenticated", user: { permissions: ["user.manage"] } }, plain = { status: "authenticated", user: { permissions: ["catalog.read"] } };
  assert.equal(adminScreen({ status: "checking" }, false), "checking");
  assert.equal(adminScreen({ status: "unavailable" }, false), "unavailable");
  assert.equal(adminScreen({ status: "anonymous" }, false), "login");
  assert.equal(adminScreen(plain, false), "denied");
  assert.equal(adminScreen(manager, false), "console");
  for (const view of [manager, plain, { status: "anonymous" }, { status: "checking" }]) assert.equal(adminScreen(view, true), "closing");
});
