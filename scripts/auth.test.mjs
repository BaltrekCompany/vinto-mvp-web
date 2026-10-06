// node --test scripts/auth.test.mjs
// Pruebas puras de lib/vinto/auth.ts (sin red ni DOM): validación de respuestas, mapeo de perfiles y permisos.
import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_VIEW, LOGIN_MESSAGES, ROLE_LABELS, activeRole, hasPermission, interpretLogin, interpretLogout, interpretSession,
  operationalRolesFromProfiles, parseAuthResponse, profileLabel,
} from "../lib/vinto/auth.ts";

const ID = "6f1c9a7e-3b2d-4c5e-8f10-123456789abc";
const user = (overrides = {}) => ({
  id: ID, username: "dev.jefatura", display_name: "Jefatura DEV", profiles: ["JEFATURA"],
  permissions: ["assignment.read", "catalog.read", "work_order.manage", "work_order.read"], must_change: false, ...overrides,
});
const envelope = (overrides) => ({ user: user(overrides) });

test("parseAuthResponse accepts the backend shape and returns a clean copy", () => {
  const payload = envelope();
  const parsed = parseAuthResponse(payload);
  assert.deepEqual(parsed, payload.user);
  assert.notEqual(parsed.profiles, payload.user.profiles);
  assert.notEqual(parsed.permissions, payload.user.permissions);
  assert.deepEqual(Object.keys(parsed).sort(), ["display_name", "id", "must_change", "permissions", "profiles", "username"]);
});

test("parseAuthResponse rejects malformed payloads instead of trusting a cast", () => {
  const bad = [
    null, undefined, "x", 42, [], {}, { user: null }, { user: [] }, { user: "x" },
    envelope({ id: "not-a-uuid" }), envelope({ id: 7 }), envelope({ username: "" }), envelope({ username: 5 }),
    envelope({ display_name: "" }), envelope({ display_name: null }), envelope({ profiles: "JEFATURA" }),
    envelope({ profiles: ["JEFATURA", 3] }), envelope({ permissions: null }), envelope({ permissions: [{}] }),
    envelope({ must_change: "false" }), envelope({ must_change: undefined }),
  ];
  for (const payload of bad) assert.equal(parseAuthResponse(payload), null, JSON.stringify(payload));
});

test("parseAuthResponse ignores unknown extra fields (forward compatible) without exposing them", () => {
  const parsed = parseAuthResponse(envelope({ password_hash: "x", token: "y" }));
  assert.equal("password_hash" in parsed, false);
  assert.equal("token" in parsed, false);
});

test("GET /me: 200 -> authenticated, 401 -> anonymous, everything else -> unavailable (never 'logged out')", () => {
  assert.deepEqual(interpretSession(200, envelope()), { status: "authenticated", user: user() });
  assert.deepEqual(interpretSession(401, { detail: "No autenticado" }), { status: "anonymous" });
  for (const status of [0, 400, 403, 404, 422, 500, 502, 503, 504]) {
    assert.deepEqual(interpretSession(status, { status: "error", database: "unavailable" }), { status: "unavailable" }, String(status));
  }
  assert.deepEqual(interpretSession(200, { user: { id: "x" } }), { status: "unavailable" }); // 200 with a broken body is not a session
  assert.deepEqual(interpretSession(200, null), { status: "unavailable" });
});

test("POST /login mapping: 200, 401, 422 and everything else", () => {
  assert.deepEqual(interpretLogin(200, envelope()), { status: "ok", user: user() });
  assert.deepEqual(interpretLogin(401, { detail: "Credenciales inválidas" }), { status: "invalid" });
  assert.deepEqual(interpretLogin(422, { detail: "Solicitud inválida" }), { status: "rejected" });
  for (const status of [500, 503, 0]) assert.deepEqual(interpretLogin(status, null), { status: "unavailable" });
  assert.deepEqual(interpretLogin(200, { nope: true }), { status: "unavailable" });
  assert.equal(LOGIN_MESSAGES.invalid, "Credenciales inválidas");
  assert.equal(LOGIN_MESSAGES.rejected, "Solicitud inválida");
  assert.equal(LOGIN_MESSAGES.unavailable, "No se pudo conectar con el servidor");
});

test("logout: only 204 confirms the central revocation", () => {
  assert.deepEqual(interpretLogout(204), { confirmed: true });
  for (const status of [200, 503, 500, 401, 0]) assert.deepEqual(interpretLogout(status), { confirmed: false }, String(status));
});

test("profiles map to the operational roles the user really owns", () => {
  assert.deepEqual(operationalRolesFromProfiles(["JEFATURA"]), ["jefatura"]);
  assert.deepEqual(operationalRolesFromProfiles(["SUPERVISION"]), ["supervision"]);
  assert.deepEqual(operationalRolesFromProfiles(["OPERACION"]), ["operacion"]);
  assert.deepEqual(operationalRolesFromProfiles(["CALIDAD"]), ["calidad"]);
});

test("DATA_BALTREK never becomes an operational role", () => {
  assert.deepEqual(operationalRolesFromProfiles(["DATA_BALTREK"]), []);
  assert.deepEqual(operationalRolesFromProfiles([]), []);
  assert.deepEqual(operationalRolesFromProfiles(["DATA_BALTREK", "OPERACION"]), ["operacion"]); // only what is really owned
});

test("several profiles give only the roles owned, in a stable order, without duplicates", () => {
  assert.deepEqual(operationalRolesFromProfiles(["CALIDAD", "JEFATURA"]), ["jefatura", "calidad"]);
  assert.deepEqual(operationalRolesFromProfiles(["JEFATURA", "CALIDAD"]), ["jefatura", "calidad"]);
  assert.deepEqual(operationalRolesFromProfiles(["OPERACION", "OPERACION", "SUPERVISION"]), ["supervision", "operacion"]);
  assert.deepEqual(operationalRolesFromProfiles(["JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"]), ["jefatura", "supervision", "operacion", "calidad"]);
});

test("unknown or lowercase profile codes grant no role", () => {
  assert.deepEqual(operationalRolesFromProfiles(["jefatura", "ADMIN", "", "Jefatura"]), []);
});

test("the chosen role is only honoured when the user owns it", () => {
  assert.equal(activeRole(["calidad"], null), "calidad");
  assert.equal(activeRole(["jefatura", "calidad"], "calidad"), "calidad");
  assert.equal(activeRole(["calidad"], "jefatura"), "calidad"); // cannot select a role that is not in user.profiles
  assert.equal(activeRole(["jefatura", "calidad"], null), "jefatura");
  assert.equal(activeRole([], "jefatura"), null);
});

test("initial view per role", () => {
  assert.deepEqual(INITIAL_VIEW.jefatura, { front: "Bobinas", module: "programacion" });
  assert.deepEqual(INITIAL_VIEW.supervision, { front: "Bobinas", module: "programacion" });
  assert.deepEqual(INITIAL_VIEW.operacion, { front: "Bobinas", module: "ejecucion" });
  assert.deepEqual(INITIAL_VIEW.calidad, { front: "Calidad", module: "ejecucion" });
});

test("labels", () => {
  assert.deepEqual(Object.values(ROLE_LABELS), ["Jefatura", "Supervisión", "Operación", "Calidad"]);
  assert.equal(profileLabel("DATA_BALTREK"), "Data Baltrek");
  assert.equal(profileLabel("JEFATURA"), "Jefatura");
  assert.equal(profileLabel("OTRO"), "OTRO");
});

test("hasPermission reads the permissions the backend sent and infers nothing", () => {
  const jefatura = user();
  assert.equal(hasPermission(jefatura, "work_order.manage"), true);
  assert.equal(hasPermission(jefatura, "assignment.manage"), false);
  assert.equal(hasPermission(jefatura, "production.capture"), false);
  // supervision: manages assignments but NOT the base OT
  const supervision = user({ username: "dev.jefatura", profiles: ["SUPERVISION"], permissions: ["assignment.manage", "assignment.read", "catalog.read", "work_order.read"] });
  assert.equal(hasPermission(supervision, "assignment.manage"), true);
  assert.equal(hasPermission(supervision, "work_order.manage"), false);
  // the username is never used to guess permissions
  assert.equal(hasPermission(user({ username: "jefatura.admin", permissions: [] }), "work_order.manage"), false);
  assert.equal(hasPermission(null, "work_order.read"), false);
  assert.equal(hasPermission(undefined, "work_order.read"), false);
});

test("DATA_BALTREK has no plant permissions in the UI", () => {
  const admin = user({ profiles: ["DATA_BALTREK"], permissions: ["assignment.read", "catalog.manage", "catalog.read", "user.manage", "work_order.read"] });
  for (const permission of ["work_order.manage", "assignment.manage", "production.capture", "quality.capture", "quality.release"]) {
    assert.equal(hasPermission(admin, permission), false, permission);
  }
  assert.deepEqual(operationalRolesFromProfiles(admin.profiles), []);
});
