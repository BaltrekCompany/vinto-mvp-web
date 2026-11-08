// E2-C2 operator-independent versioned supervisor acknowledgement HTTP/UI.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const tmp = join(root, `.tmp-e2c2-${process.pid}`);
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
    [api, inbox] = await Promise.all([
        bundle("lib/vinto/supervision-revision-api.ts", "api"),
        bundle("components/vinto/supervision-revision-inbox.tsx", "inbox"),
    ]);
});
after(() => rmSync(tmp, { recursive: true, force: true }));

const UUID = "12345678-1234-4234-8234-123456789012";
const beforeLine = { pv_reference: "PV-001", article_code: "A1", quantity: "100", due_date: "2026-11-09" };
const afterLine = { ...beforeLine, quantity: "120" };
const notice = {
    work_order_id: UUID, work_order_number: "OT-2026-0001",
    status: "published", version_number: 2, line_code: "L1",
    reason: "Cambio de programa autorizado", revised_at: "2026-11-08T01:00:00Z",
    changed_by: "Jefatura QA", machine_code: "MP1", before: beforeLine,
    after: afterLine, acknowledged_at: null,
};
async function mocked(responder, call) {
    const prev = globalThis.fetch, calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        const [status, payload] = responder();
        return new Response(JSON.stringify(payload),
            { status, headers: { "Content-Type": "application/json" } });
    };
    try { return { result: await call(), calls }; }
    finally { globalThis.fetch = prev; }
}

test("strict notice and receipt parsers reject stale/injected and invalid payloads", () => {
    assert.deepEqual(api.parseSupervisionNotices([]), []);
    assert.deepEqual(api.parseSupervisionNotices([notice]), [notice]);
    for (const invalid of [
        { ...notice, version_number: 1 },
        { ...notice, work_order_id: "other" },
        { ...notice, status: "draft" },
        { ...notice, changed_by: 123 },
        { ...notice, after: { ...notice.after, quantity: 120 } },
        { ...notice, acknowledged_at: undefined },
    ]) assert.equal(api.parseSupervisionNotices([invalid]), null);
    assert.equal(api.parseSupervisionNotices({}), null);
    assert.equal(api.parseSupervisionAck(
        { work_order_id: UUID, version_number: 2, acknowledged_at: "2026-11-08T01:30:00Z" })?.version_number, 2);
    assert.equal(api.parseSupervisionAck(
        { work_order_id: UUID, version_number: 1, acknowledged_at: "now" }), null);
});

test("supervisor GET never caches, carries session cookie and has no actor parameters", async () => {
    const { result, calls } = await mocked(() => [200, [notice]], () => api.listSupervisionNotices());
    assert.equal(result.ok, true);
    assert.deepEqual(result.data, [notice]);
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/work-orders\/supervision-revision-notices$/);
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.cache, "no-store");
    assert.equal(calls[0].init.method, "GET");
});

test("supervisor POST only sends expected version; 409 never automatically retries", async () => {
    const { result, calls } = await mocked(() => [200, {
        work_order_id: UUID, version_number: 2, acknowledged_at: "2026-11-08T01:30:00Z",
    }], () => api.acknowledgeSupervisionRevision(UUID, 2));
    assert.equal(result.ok, true);
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.credentials, "include");
    assert.deepEqual(JSON.parse(calls[0].init.body), { expected_version: 2 });
    assert.match(calls[0].url, /\/api\/work-orders\/12345678-1234-4234-8234-123456789012\/acknowledge-supervision-revision$/);
    const conflict = await mocked(() => [409, { code: "SUPERVISION_REVISION_CHANGED" }],
        () => api.acknowledgeSupervisionRevision(UUID, 2));
    assert.equal(conflict.result.ok, false);
    assert.equal(conflict.result.kind, "conflict");
    assert.equal(conflict.calls.length, 1);
});

test("supervisor panel is conditional, explicit on load/error, without production gating", () => {
    const html = server.renderToStaticMarkup(React.createElement(inbox.SupervisionRevisionInbox, {
        scope: "user:" + UUID, onSessionLost: () => {},
    }));
    assert.match(html, /data-e2c2-supervision-inbox/);
    assert.match(html, /Supervisión/);
    assert.match(html, /Consultando reprogramaciones/);
    assert.ok(!html.includes("No hay reprogramaciones"), "loading is not interpreted as zero notices");
    const page = readFileSync(join(root, "app/page.tsx"), "utf8");
    assert.match(page, /activeModule === "programacion" && front !== "Calidad" && canManageAssignments/);
    assert.match(page, /<SupervisionRevisionInbox key=\{scope\} scope=\{scope\}/);
    const service = readFileSync(join(root, "backend/app/work_orders/supervision_revision_notices.py"), "utf8");
    assert.ok(!/UPDATE vinto_txn\.(assignment|work_order_line_execution|capture|bobbin)/.test(service));
});
