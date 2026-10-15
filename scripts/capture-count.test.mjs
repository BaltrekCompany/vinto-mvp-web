// node --test scripts/capture-count.test.mjs
// Contador central de capturas (M1-C2-a): el cliente envía la cookie HttpOnly (credentials "include"), conserva el contrato de la respuesta,
// distingue sesión vencida / sin permiso / no disponible y no puede mostrar el conteo de otra sesión.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { CaptureCountError, getCaptureCount } from "../lib/vinto/api.ts";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => { if (body === undefined) throw new SyntaxError("no body"); return body; } });
const withFetch = async (impl, run) => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return impl(url, init); };
  try { return await run(calls); } finally { globalThis.fetch = original; }
};
const failure = async (promise) => { try { await promise; } catch (error) { return error; } assert.fail("expected a failure"); };
const signal = () => new AbortController().signal;

test("the request sends the session cookie with credentials include and nothing else that identifies the user", async () => {
  await withFetch(async () => reply(200, { front: "Bobinas", count: 7, source: "database" }), async (calls) => {
    const result = await getCaptureCount("Bobinas", signal());
    assert.deepEqual(result, { front: "Bobinas", count: 7, source: "database" });
    const [{ url, init }] = calls;
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    assert.equal(new URL(url).pathname, "/api/captures/count");
    assert.deepEqual([...new URL(url).searchParams], [["front", "Bobinas"]], "the client sends the front only: no sector, machine or user hint");
    assert.equal(init.headers, undefined, "no Authorization or custom identity headers");
    assert.equal(init.method, undefined);
  });
});

test("every front keeps its value in the query and in the contract", async () => {
  for (const front of ["Bobinas", "Rebobinado", "Conversión", "Calidad"]) {
    await withFetch(async () => reply(200, { front, count: 0, source: "database" }), async (calls) => {
      assert.deepEqual(await getCaptureCount(front, signal()), { front, count: 0, source: "database" });
      assert.equal(new URL(calls[0].url).searchParams.get("front"), front);
    });
  }
});

test("401 is a lost session, 403 is a missing permission, anything else is unavailable", async () => {
  for (const [status, kind] of [[401, "session"], [403, "forbidden"], [404, "unavailable"], [422, "unavailable"], [500, "unavailable"], [503, "unavailable"]]) {
    await withFetch(async () => reply(status, { detail: "x" }), async () => {
      const error = await failure(getCaptureCount("Bobinas", signal()));
      assert.ok(error instanceof CaptureCountError, String(status));
      assert.equal(error.kind, kind, String(status));
      assert.doesNotMatch(error.message, /detail|x$/, "the server body never reaches the user");
    });
  }
});

test("a network failure is unavailable, but an abort is rethrown so stale requests are dropped silently", async () => {
  await withFetch(async () => { throw new TypeError("fetch failed"); }, async () => {
    assert.equal((await failure(getCaptureCount("Bobinas", signal()))).kind, "unavailable");
  });
  await withFetch(async () => { throw new DOMException("aborted", "AbortError"); }, async () => {
    const error = await failure(getCaptureCount("Bobinas", signal()));
    assert.ok(!(error instanceof CaptureCountError));
    assert.equal(error.name, "AbortError");
  });
});

test("an invalid body is unavailable, never a number", async () => {
  const bad = [undefined, null, [], "7", {}, { front: "Calidad", count: 1, source: "database" }, { front: "Bobinas", count: -1, source: "database" },
    { front: "Bobinas", count: 1.5, source: "database" }, { front: "Bobinas", count: "3", source: "database" }, { front: "Bobinas", count: 1, source: "local" },
    { front: "Bobinas", count: 1 }, { count: 1, source: "database" }, { front: "Bobinas", count: Number.MAX_SAFE_INTEGER + 2, source: "database" }];
  for (const body of bad) {
    await withFetch(async () => reply(200, body), async () => {
      const error = await failure(getCaptureCount("Bobinas", signal()));
      assert.ok(error instanceof CaptureCountError && error.kind === "unavailable", JSON.stringify(body));
    });
  }
});

test("api.ts no longer omits credentials anywhere", () => {
  const source = read("lib/vinto/api.ts");
  assert.doesNotMatch(source, /credentials:\s*"omit"/);
  assert.match(source, /credentials:\s*"include"/);
  assert.doesNotMatch(source, /Authorization|localStorage|sessionStorage|document\.cookie/);
});

test("the component ties every result to user, front and attempt, cancels stale requests and reports lost sessions", () => {
  const source = read("components/vinto/capture-count.tsx");
  assert.match(source, /userKey: string; onSessionLost: \(\) => void/);
  assert.match(source, /state\.owner === userKey && state\.front === front && state\.attempt === attempt/);
  assert.match(source, /new AbortController\(\)/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /if \(!active\) return;/);
  assert.match(source, /\[front, attempt, userKey\]/);
  assert.match(source, /if \(kind === "session"\) onSessionLost\(\)/);
  assert.match(source, /captureCountView\(current, front\)/); // INT-02A (cambio de contrato): sin conteo local
  const view = read("lib/vinto/capture-count-view.ts");
  assert.doesNotMatch(view.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n"), /Registros locales|navegador/); // INT-02A (cambio de contrato): el conteo local ya no se menciona
  assert.match(view, /Registros centrales/);
  assert.match(view, /kind === "forbidden"/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|document\.cookie|Authorization/);
});

test("the tracking view passes the authenticated user and the session-lost handler to the counter", () => {
  const page = read("app/page.tsx");
  const usages = page.match(/<Tracking [^\n]*?\/>/g) ?? [];
  assert.equal(usages.length, 1); // PB-CLEAN: Calidad ya no usa Tracking (resumen central pendiente)
  for (const usage of usages) assert.match(usage, /userKey=\{user\.id\} onSessionLost=\{sessionLost\}/);
  assert.match(page, /<CaptureCount front=\{front\} userKey=\{userKey\} onSessionLost=\{onSessionLost\}\/>/);
});
