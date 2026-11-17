// OFF-02 contract tests: pure checks and mocked Service Worker, no browser or database required.
// Run: node --experimental-strip-types --test scripts/off-02-foundation.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import {
  OFFLINE_DB_NAME, OFFLINE_DB_VERSION, OfflineStoreError, getSealedDraft,
  listQueuedForOwner, saveSealedDraft, queueSealedDraft, offlineStorageStatus,
} from "../lib/vinto/offline-store.ts";

const root = resolve(import.meta.dirname, "..");
const source = (path) => readFileSync(resolve(root, path), "utf8");
const ORIGIN = "https://vinto.example.test";
const ID = "11111111-1111-4111-8111-111111111111";
const USER = "22222222-2222-4222-8222-222222222222";
const DEVICE = "33333333-3333-4333-8333-333333333333";
const CONTEXT = "44444444-4444-4444-8444-444444444444";

function worker() {
  const handlers = {}, fetched = [], matched = [], opened = [], added = [];
  let online = true;
  const cached = { from: "offline-static" };
  const cache = {
    addAll: async (assets) => { added.push(...assets); },
    match: async (request) => {
      matched.push(typeof request === "string" ? request : request.url);
      return typeof request === "string" && request === "/offline.html" ? cached : undefined;
    },
    put: async () => {},
  };
  const caches = {
    open: async (name) => { opened.push(name); return cache; },
    keys: async () => ["vinto-off02-static-v0", "unrelated-cache"],
    delete: async () => true,
    match: async (path) => cache.match(path),
  };
  const fakeFetch = async (request) => {
    fetched.push(request.url ?? request);
    if (!online) throw new Error("network offline");
    return { ok: true, type: "basic", from: "network", clone() { return this; } };
  };
  runInNewContext(source("public/sw.js"), {
    self: { location: { origin: ORIGIN }, addEventListener: (name, handler) => { handlers[name] = handler; }, clients: { claim: async () => {} } },
    caches, URL, Response, fetch: fakeFetch,
  });
  async function request(path, { method = "GET", mode = "same-origin", origin = ORIGIN } = {}) {
    let response;
    const task = { request: { url: origin + path, method, mode }, respondWith: (value) => { response = Promise.resolve(value); }, waitUntil: () => {} };
    handlers.fetch(task);
    return response ? await response : null;
  }
  return { handlers, request, fetched, matched, opened, added, setOnline: (value) => { online = value; } };
}

test("manifest is a scoped stand-alone PWA with existing public icon", () => {
  const manifest = JSON.parse(source("public/manifest.webmanifest"));
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.display, "standalone");
  assert.deepEqual(manifest.icons.map(({ src }) => src), ["/favicon.svg"]);
});

test("service worker precaches only public shell and no private API/admin responses", async () => {
  const w = worker();
  await new Promise((resolve) => w.handlers.install({ waitUntil: (promise) => Promise.resolve(promise).then(resolve) }));
  assert.deepEqual(w.added.sort(), ["/offline.html", "/offline-probe.js", "/manifest.webmanifest", "/favicon.svg"].sort());
  assert.ok(w.added.every((path) => !path.startsWith("/api") && !path.startsWith("/admin")));
  for (const path of ["/api/auth/me", "/api/captures", "/admin", "/admin/users"]) {
    assert.equal(await w.request(path), null, path);
  }
  assert.equal(w.fetched.length, 0);
});

test("network root navigation falls back to PUBLIC offline shell; other private routes never fallback", async () => {
  const w = worker();
  assert.equal((await w.request("/", { mode: "navigate" })).from, "network");
  w.setOnline(false);
  assert.equal((await w.request("/", { mode: "navigate" })).from, "offline-static");
  assert.equal((await w.request("/offline.html", { mode: "navigate" })).from, "offline-static");
  assert.equal(await w.request("/admin", { mode: "navigate" }), null);
  assert.equal(await w.request("/api/auth/me", { mode: "navigate" }), null);
  assert.ok(w.matched.includes("/offline.html"));
});

test("worker never intercepts non-GET or cross-origin requests", async () => {
  const w = worker();
  assert.equal(await w.request("/api/captures", { method: "POST" }), null);
  assert.equal(await w.request("/", { origin: "https://elsewhere.example" }), null);
  assert.equal(w.fetched.length, 0);
});

test("offline storage starts unavailable in Node and rejects raw unsealed captures", async () => {
  assert.equal(OFFLINE_DB_NAME, "vinto-offline-v1");
  assert.equal(OFFLINE_DB_VERSION, 1);
  const invalid = {
    id: ID, ownerId: USER, deviceKey: DEVICE, contextId: CONTEXT,
    formCode: "VINTO-P1-22", formVersion: 1, savedAt: "2026-11-17T10:00:00Z",
    values: { nombre: "NO DEBE GUARDARSE EN CLARO" },
  };
  await assert.rejects(saveSealedDraft(invalid), (err) => err instanceof OfflineStoreError && err.reason === "invalid");
  const sealed = { ...invalid, sealed: { format: "aes-gcm-v1", iv: "AAAAAAAAAAAAAAAA", ciphertext: "AAAAAAAAAAAAAAAAAAAAAAAA" } };
  delete sealed.values;
  await assert.rejects(saveSealedDraft(sealed), (err) => err instanceof OfflineStoreError && err.reason === "unavailable");
  await assert.rejects(getSealedDraft(USER, DEVICE, ID), (err) => err.reason === "unavailable");
  await assert.rejects(listQueuedForOwner(USER, DEVICE), (err) => err.reason === "unavailable");
  await assert.rejects(queueSealedDraft(USER, DEVICE, ID, "2026-11-17T10:00:00Z"), (err) => err.reason === "unavailable");
  assert.deepEqual(await offlineStorageStatus(), { supported: false, persisted: null, estimatedBytes: null });
});

test("offline fallback contains clear safety boundary and technical persistence probe", () => {
  const html = source("public/offline.html");
  const probe = source("public/offline-probe.js");
  assert.match(html, /la captura de datos reales/);
  assert.match(html, /Requieren OFF-03 y OFF-04/);
  assert.ok(html.includes("/offline-probe.js"));
  assert.match(probe, /vinto-off02-probe/);
  assert.doesNotMatch(probe, /localStorage/);
  assert.doesNotMatch(probe, /cookie|password|username/i);
});

test("online auth remains authoritative; no production form imported the offline store", () => {
  const layout = source("app/layout.tsx");
  assert.match(layout, /OfflineRegistration/);
  assert.match(layout, /manifest\.webmanifest/);
  assert.doesNotMatch(source("app/page.tsx"), /offline-store/);
  assert.doesNotMatch(source("lib/vinto/use-session.ts"), /offline-store/);
});
