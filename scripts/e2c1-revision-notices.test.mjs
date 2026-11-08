// E2-C1 UI/API contract: no local state fallback and no actor-selected receipts.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const tmp = join(root, `.tmp-e2c1-${process.pid}`);
const alias = { name: "alias-at", enforce: "pre", resolveId(spec) {
    if (!spec.startsWith("@/")) return null;
    const path = `${root}/${spec.slice(2)}`;
    return [`${path}.tsx`, `${path}.ts`, `${path}/index.tsx`, `${path}/index.ts`].find(existsSync) ?? null;
} };
async function bundle(entry, name) {
    const built = await build({ configFile: false, root, logLevel: "error", mode: "production", plugins: [alias],
        oxc: { jsx: { runtime: "automatic" } },
        build: { write: false, ssr: join(root, entry), minify: false,
            target: "node22", rollupOptions: { output: { format: "es" } } } });
    const chunk = (Array.isArray(built) ? built[0] : built).output.find(o => o.type === "chunk");
    const filename = join(tmp, name + ".mjs");
    writeFileSync(filename, chunk.code);
    return import(pathToFileURL(filename).href);
}

let api, inbox, React, server;
before(async () => {
    mkdirSync(tmp, { recursive: true });
    [React, server] = [await import("react"), await import("react-dom/server")];
    [api, inbox] = await Promise.all([bundle("lib/vinto/revision-notices-api.ts", "api"),
        bundle("components/vinto/revision-notice-inbox.tsx", "inbox")]);
});
after(() => rmSync(tmp, { recursive: true, force: true }));

const UUID = "12345678-1234-4234-8234-123456789012";
const notice = {
    assignment_id: UUID, version_number: 2, work_order_number: "OT-2026-0001",
    line_code: "L1", machine_code: "MP1", reason: "Cambio autorizado por Jefatura",
    revised_at: "2026-11-08T01:00:00Z", acknowledged_at: null,
    pv_reference: "PV-100", article_code: "ART-1", quantity: "120.00", due_date: "2026-12-10",
};
async function fetchMock(respond, action) {
    const original = globalThis.fetch, calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        const [status, payload] = respond();
        return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
    };
    try { return { result: await action(), calls }; }
    finally { globalThis.fetch = original; }
}

test("strict notice schema rejects malformed, injected and stale data", () => {
    assert.deepEqual(api.parseRevisionNotices([]), []);
    assert.deepEqual(api.parseRevisionNotices([notice]), [notice]);
    for (const bad of [{ ...notice, assignment_id: "wrong" },
        { ...notice, version_number: 1 }, { ...notice, acknowledged_at: undefined },
        { ...notice, quantity: 120 }, { ...notice, reason: null }]) {
        assert.equal(api.parseRevisionNotices([bad]), null);
    }
    assert.equal(api.parseRevisionNotices({}), null);
    assert.equal(api.parseRevisionReceipt({ assignment_id: UUID, version_number: 2, acknowledged_at: "2026-11-08T01:20:00Z" })?.version_number, 2);
    assert.equal(api.parseRevisionReceipt({ assignment_id: UUID, version_number: 1, acknowledged_at: "t" }), null);
});

test("GET uses the authenticated session and never caches notices", async () => {
    const { result, calls } = await fetchMock(() => [200, [notice]], () => api.listRevisionNotices());
    assert.equal(result.ok, true);
    assert.deepEqual(result.data, [notice]);
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/assignments\/revision-notices$/);
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.cache, "no-store");
    assert.equal(calls[0].init.method, "GET");
});

test("acknowledgement POST carries only the expected version, never user, machine or reason", async () => {
    const { result, calls } = await fetchMock(() => [200, {
        assignment_id: UUID, version_number: 2, acknowledged_at: "2026-11-08T01:20:00Z",
    }], () => api.acknowledgeRevision(UUID, 2));
    assert.equal(result.ok, true);
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.credentials, "include");
    assert.match(calls[0].url, /\/api\/assignments\/12345678-1234-4234-8234-123456789012\/acknowledge-revision$/);
    assert.deepEqual(JSON.parse(calls[0].init.body), { expected_version: 2 });
    const conflict = await fetchMock(() => [409, { code: "REVISION_NOTICE_CHANGED" }],
        () => api.acknowledgeRevision(UUID, 1));
    assert.equal(conflict.result.ok, false);
    assert.equal(conflict.calls.length, 1, "never auto-retry an outdated version");
    assert.equal(conflict.result.kind, "conflict");
});

test("operator panel clearly separates current notices, errors, and no production capture gates", () => {
    const html = server.renderToStaticMarkup(React.createElement(inbox.RevisionNoticeInbox, {
        scope: "user:" + UUID, onSessionLost: () => {},
    }));
    assert.match(html, /data-e2c1-revision-inbox/);
    assert.match(html, /Cambios de programación asignada/);
    assert.match(html, /Consultando avisos vigentes/);
    assert.ok(!html.includes("No tienes avisos"), "loading is not interpreted as zero notices");
    const rootPage = readFileSync(join(root, "app/page.tsx"), "utf8");
    assert.match(rootPage, /activeModule === "ejecucion" && front !== "Calidad"/);
    assert.match(rootPage, /<RevisionNoticeInbox key=\{scope\} scope=\{scope\}/);
    const serverCode = readFileSync(join(root, "backend/app/assignments/revision_notices.py"), "utf8");
    assert.ok(!/UPDATE vinto_txn\.(assignment|capture|work_order_line_execution)/.test(serverCode));
});
