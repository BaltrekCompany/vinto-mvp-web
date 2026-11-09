// node --test scripts/usr-05-admin-users.test.mjs
// USR-05: contratos reales de USR-02/03/04, HTTP, autorización y estado transitorio.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
    ACCOUNT_CLOSED, createAccountClient, createAccountController, parseAccountOutcome, parseAccountProfiles,
    validateAccountInput,
} from "../lib/vinto/admin-users.ts";

const U1 = "11111111-1111-4111-8111-111111111111";
const U2 = "22222222-2222-4222-8222-222222222222";
const profile = [{ code: "DATA_BALTREK", name: "Data Baltrek" }, { code: "OPERACION", name: "Operación" }];
const user = { id: U1, username: "qa.admin", display_name: "QA Admin", active: true, profiles: ["DATA_BALTREK"], sectors: [] };
const target = (action, account = user) => ({ action, user: action === "create" ? null : account });
const payload = {
    create: { action: "create", username: " qa.Nuevo ", display_name: "QA Nuevo", profile_code: "OPERACION", password: "password-valid-123" },
    edit: { action: "edit", display_name: "QA Editado", profile_code: "OPERACION" },
    reset: { action: "reset", password: "new-password-valid-123" },
    deactivate: { action: "deactivate", reason: "Baja de prueba" },
    reactivate: { action: "reactivate", reason: "Alta de prueba" },
};
const reply = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });
const response = {
    create: { id: U2, username: "qa.nuevo", display_name: "QA Nuevo", active: true, profiles: ["OPERACION"], sectors: [] },
    edit: { user_id: U1, username: "qa.admin", display_name: "QA Editado", profile_code: "OPERACION", active: true, changed: true, sessions_revoked: 1, request_id: "admin-user-edit:123" },
    reset: { user_id: U1, changed: true, must_change: false, sessions_revoked: 1, request_id: "admin-password-reset:123" },
    deactivate: { user_id: U1, username: "qa.admin", active: false, changed: true, sessions_revoked: 2, request_id: "admin-user-deactivate:123" },
    reactivate: { user_id: U1, username: "qa.admin", active: true, changed: true, sessions_revoked: 1, request_id: "admin-user-reactivate:123" },
};
const recorder = (handler) => {
    const calls = [];
    const client = createAccountClient(() => "http://vinto.test", async (url, init) => {
        calls.push({ url, init });
        return handler(url, init);
    });
    return { client, calls };
};

test("profiles: read a central catalogue without creating fake codes or duplicates", async () => {
    assert.deepEqual(parseAccountProfiles(profile), profile);
    assert.deepEqual(parseAccountProfiles([]), []);
    for (const invalid of [null, {}, [{ code: "bad", name: "x" }], [profile[0], profile[0]], [{ code: "A", name: "" }], [{ code: "A", name: 1 }]]) {
        assert.equal(parseAccountProfiles(invalid), null);
    }
    const { client, calls } = recorder(() => reply(200, profile));
    const result = await client.listProfiles();
    assert.deepEqual(result.data, profile);
    assert.equal(calls[0].url, "http://vinto.test/api/admin/profiles");
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.cache, "no-store");
    assert.equal(calls[0].init.method, "GET");
    assert.equal(calls[0].init.headers, undefined);
});

test("create/edit/reset/deactivate/reactivate use exact endpoint, method and minimal JSON body", async () => {
    for (const kind of ["create", "edit", "reset", "deactivate", "reactivate"]) {
        const { client, calls } = recorder(() => reply(kind === "create" ? 201 : 200, response[kind]));
        const result = await client.mutate(target(kind, kind === "reactivate" ? { ...user, active: false } : user), payload[kind]);
        assert.equal(result.ok, true, kind + ": " + JSON.stringify(result));
        assert.equal(result.data.action, kind);
        assert.equal(calls.length, 1);
        const call = calls[0], init = call.init;
        const expectedPath = kind === "create" ? "/api/admin/users" : "/api/admin/users/" + U1 +
            (kind === "edit" ? "" : kind === "reset" ? "/reset-password" : "/" + kind);
        assert.equal(call.url, "http://vinto.test" + expectedPath);
        assert.equal(init.method, kind === "edit" ? "PATCH" : "POST");
        assert.deepEqual(init.headers, { "Content-Type": "application/json" });
        assert.equal(init.credentials, "include");
        assert.equal(init.cache, "no-store");
        assert.equal(init.body.includes("actor_id"), false);
        assert.equal(init.body.includes("user_id"), false);
        assert.equal(init.body.includes("grant"), false);
        assert.equal(init.body.includes("cookie"), false);
        const parsed = JSON.parse(init.body);
        if (kind === "create") assert.deepEqual(parsed, { username: "qa.nuevo", display_name: "QA Nuevo", profile_code: "OPERACION", password: payload.create.password });
        if (kind === "edit") assert.deepEqual(parsed, { display_name: "QA Editado", profile_code: "OPERACION" });
        if (kind === "reset") assert.deepEqual(parsed, { password: payload.reset.password });
        if (kind === "deactivate" || kind === "reactivate") assert.deepEqual(parsed, { reason: payload[kind].reason });
        assert.equal(JSON.stringify(result).includes(payload.create.password), false);
        assert.equal(JSON.stringify(result).includes(payload.reset.password), false);
    }
});

test("strict success parser rejects another user, forged audit, wrong active state and malformed responses", () => {
    assert.equal(parseAccountOutcome("create", target("create"), response.create).userId, U2);
    assert.equal(parseAccountOutcome("reset", target("reset"), response.reset).changed, true);
    const invalid = [
        ["create", { ...response.create, sectors: [{ code: "BOBINAS", name: "Bobinas", active: true, operational: true }] }],
        ["create", { ...response.create, password_hash: "secret", id: "not-a-uuid" }],
        ["edit", { ...response.edit, user_id: U2 }],
        ["edit", { ...response.edit, changed: false, request_id: "wrong" }],
        ["reset", { ...response.reset, must_change: true }],
        ["deactivate", { ...response.deactivate, active: true }],
        ["reactivate", { ...response.reactivate, changed: true, request_id: null }],
        ["reactivate", { ...response.reactivate, sessions_revoked: -1 }],
    ];
    for (const [kind, body] of invalid) assert.equal(parseAccountOutcome(kind, target(kind), body), null, kind);
    assert.equal(parseAccountOutcome("deactivate", target("deactivate"), { ...response.deactivate, changed: false, request_id: null, sessions_revoked: 0 }).changed, false);
});

test("validate forms against central profiles, immutable username, password length and reason", () => {
    assert.equal(validateAccountInput(target("create"), { ...payload.create, username: "   QA.NUEVO  " }, profile), null);
    assert.equal(validateAccountInput(target("edit"), payload.edit, profile), null);
    assert.equal(validateAccountInput(target("reset"), payload.reset, profile), null);
    assert.equal(validateAccountInput(target("deactivate"), payload.deactivate, profile), null);
    assert.equal(validateAccountInput(target("reactivate", { ...user, active: false }), payload.reactivate, profile), null);
    for (const [t, input, profiles] of [
        [target("create"), { ...payload.create, username: "../invalid" }, profile],
        [target("create"), { ...payload.create, profile_code: "ADMIN_INVENTADO" }, profile],
        [target("create"), { ...payload.create, password: "corta" }, profile],
        [target("edit"), { ...payload.edit, display_name: " ", profile_code: "DATA_BALTREK" }, profile],
        [target("edit"), { ...payload.edit, display_name: user.display_name, profile_code: user.profiles[0] }, profile],
        [target("edit"), payload.edit, []],
        [target("reset"), { ...payload.reset, password: "x" }, profile],
        [target("deactivate"), { ...payload.deactivate, reason: " " }, profile],
        [target("reactivate"), payload.reactivate, profile],
    ]) assert.notEqual(validateAccountInput(t, input, profiles), null);
});

test("invalid body or target sends no request, even with malformed ids and action mismatch", async () => {
    const { client, calls } = recorder(() => reply(200, response.edit));
    const bad = [
        [target("edit", { ...user, id: "path/../" }), payload.edit],
        [target("create"), { ...payload.create, password: "short" }],
        [target("deactivate"), { ...payload.deactivate, reason: " " }],
        [target("edit"), payload.reset],
    ];
    for(const [t, i] of bad) assert.equal((await client.mutate(t, i)).ok, false);
    assert.equal(calls.length, 0);
});

test("401/403/409/415/422/503 and transport errors are explicit, without server message leakage", async () => {
    for(const [status,code,kind] of [
        [401,null,"session"], [403,null,"forbidden"], [403,"ORIGIN_NOT_ALLOWED","origin"],
        [409,"LAST_ADMINISTRATOR","invalid"], [409,"USERNAME_ALREADY_EXISTS","invalid"],
        [415,"UNSUPPORTED_MEDIA_TYPE","unsupported"], [422,"NEW_USER_INVALID","invalid"], [503,null,"unavailable"],
    ]) {
        const { client } = recorder(() => reply(status, { code, detail: "secreto del servidor" }));
        const result = await client.mutate(target("edit"), payload.edit);
        assert.equal(result.ok, false);
        assert.equal(result.kind, kind);
        assert.equal(JSON.stringify(result).includes("secreto"), false);
    }
    const offline = recorder(() => { throw new Error("fetch failed"); }).client;
    assert.equal((await offline.mutate(target("deactivate"), payload.deactivate)).kind, "unavailable");
});

test("controller sends only after explicit submit, serializes double click and ignores stale response after disposal", async () => {
    let settle;
    const pending = new Promise((resolve) => { settle = resolve; });
    let calls = 0, states = [], callbacks = [];
    const client = { mutate: () => { calls++; return pending; } };
    const controller = createAccountController(client, (state) => states.push(state), (result) => callbacks.push(result));
    controller.open(target("reset"));
    assert.equal(controller.state.step, "draft");
    assert.equal(calls, 0);
    const one = controller.submit(payload.reset);
    const duplicate = controller.submit(payload.reset);
    controller.close(); // no close while POST could have reached PostgreSQL
    controller.open(target("deactivate")); // no change of target during pending
    assert.equal(controller.state.step, "submitting");
    assert.equal(calls, 1);
    settle({ ok: true, data: { action: "reset", userId: U1, username: "qa.admin", changed: true, sessionsRevoked: 1, requestId: "audit" }, status: 200 });
    await Promise.all([one, duplicate]);
    assert.equal(controller.state.step, "done");
    assert.equal(callbacks.length, 1);
    controller.close();
    assert.deepEqual(controller.state, ACCOUNT_CLOSED);
    const other = createAccountController(client, (state) => states.push(state), (result) => callbacks.push(result));
    other.open(target("reset"));
    const wait = other.submit(payload.reset);
    const before = callbacks.length;
    other.dispose();
    await wait;
    assert.equal(callbacks.length, before);
});

test("source integration: no bypass of existing /admin permission gate; password never enters navigation or storage", () => {
    const read = (path) => readFileSync(new URL("../" + path, import.meta.url), "utf8");
    const page = read("app/admin/page.tsx");
    const client = read("lib/vinto/admin-users.ts");
    const screen = read("components/vinto/admin/admin-user-accounts.tsx");
    const console = read("components/vinto/admin/admin-console.tsx");
    assert.ok(page.includes('screen === "denied"') && page.includes("<AdminConsole key={view.user.id}"));
    assert.ok(console.includes("useAccountChange") && console.includes("profiles:"));
    assert.ok(screen.includes('type="password"') && screen.includes('autoComplete="new-password"'));
    for(const source of [client,screen,console]) {
        assert.ok(!source.includes("localStorage") && !source.includes("sessionStorage") && !source.includes("document.cookie"));
    }
});
