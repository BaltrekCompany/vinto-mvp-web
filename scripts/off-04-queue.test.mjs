// OFF-04.2 (laboratory): structural isolation and immutability contracts of the SIMULATED local pending queue.
// IndexedDB behaviour (atomicity, races, tampering, restart) is exercised in real Chrome by off-04-queue-browser.py.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { captureIdFor, PENDING_SCHEMA } from "../lib/vinto/offline-lab-queue.ts";
import { isLabPending, LAB_QUEUE_DB, LAB_QUEUE_STORE, LAB_STATUS } from "../lib/vinto/offline-lab-queue-store.ts";

const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const U = (n) => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;
const QUEUE_FILES = ["lib/vinto/offline-lab-queue-store.ts", "lib/vinto/offline-lab-queue.ts"];
const row = () => ({
    capture_id: U(1), draftId: U(2), ownerId: U(3), deviceKey: U(4), formCode: "VINTO-P1-26", formVersion: 1, contextId: U(5),
    sourceRevision: 1, queuedAt: "2026-11-19T10:00:00.000Z", status: LAB_STATUS, lab: true, syncState: "NOT_SYNCED",
    sealed: { format: "aes-gcm-v1", iv: "AAAAAAAAAAAAAAAA", ciphertext: "A".repeat(40) },
});

test("capture id is deterministic per owner+browser+draft and UUIDv4-shaped", async () => {
    const a = await captureIdFor(U(3), U(4), U(2));
    assert.equal(a, await captureIdFor(U(3).toUpperCase(), U(4), U(2).toUpperCase()));
    assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    const others = await Promise.all([captureIdFor(U(6), U(4), U(2)), captureIdFor(U(3), U(6), U(2)), captureIdFor(U(3), U(4), U(6))]);
    assert.equal(new Set([a, ...others]).size, 4);
});

test("pending record shape is strict: only the isolated simulation status is accepted", () => {
    assert.equal(isLabPending(row()), true);
    const bad = [
        { ...row(), status: "queued" }, { ...row(), status: "synced" }, { ...row(), lab: false }, { ...row(), syncState: "SYNCED" },
        { ...row(), extra: 1 }, { ...row(), sourceRevision: 0 }, { ...row(), capture_id: "x" }, { ...row(), queuedAt: "ayer" },
        { ...row(), sealed: { ...row().sealed, format: "plain" } }, (() => { const r = row(); delete r.syncState; return r; })(), null, [],
    ];
    bad.forEach((b, i) => assert.equal(isLabPending(b), false, "case " + i));
    assert.equal(LAB_STATUS, "queued_local_simulation");
    assert.match(PENDING_SCHEMA, /pending-sim/);
});

test("structural isolation: its own database, never the application database or the real send queue", () => {
    assert.equal(LAB_QUEUE_DB, "vinto-off04lab-queue-v1");
    assert.equal(LAB_QUEUE_STORE, "lab_pending");
    for (const f of QUEUE_FILES) {
        const src = read(f);
        assert.doesNotMatch(src, /vinto-offline-v1|offline-store/, f);                    // never imports or opens the app database
        assert.doesNotMatch(src, /\boutbox\b|queueSealedDraft|listQueuedForOwner|saveSealedDraft/, f);
        assert.doesNotMatch(src, /status:\s*"queued"|"queued"|'queued'/, f);              // the real pending status is never produced
    }
    // nothing outside the laboratory imports the simulated queue (a future sync engine cannot reach it by accident)
    const allowed = new Set(["lib/vinto/offline-lab-queue.ts", "lib/vinto/offline-lab-queue-store.ts",
        "lib/vinto/offline-draft-store.ts", "lib/vinto/offline-draft-lab.ts", "scripts/off-04-harness-entry.ts", "scripts/off-04-queue.test.mjs"]);
    const walk = (dir) => readdirSync(join(root, dir)).flatMap(n => {
        if (["node_modules", ".next", "dist", ".git"].includes(n)) return [];
        const rel = dir + "/" + n;
        return statSync(join(root, rel)).isDirectory() ? walk(rel) : [rel];
    });
    for (const f of [...walk("lib"), ...walk("app"), ...walk("scripts"), ...walk("backend/app").filter(x => /\.(ts|tsx|mjs|js|py)$/.test(x))]) {
        if (!/\.(ts|tsx|mjs|js|py)$/.test(f) || allowed.has(f) || f.endsWith("off-04-queue-browser.py")) continue;
        assert.doesNotMatch(read(f), /offline-lab-queue|vinto-off04lab-queue|lab_pending|queued_local_simulation/, f);
    }
});

test("immutability by construction: the pending store only ADDS", () => {
    for (const f of QUEUE_FILES) {
        assert.doesNotMatch(read(f), /\.(put|delete|clear|openCursor|openKeyCursor)\s*\(|\.deleteDatabase|deleteObjectStore/, f);
    }
    assert.match(read("lib/vinto/offline-lab-queue-store.ts"), /\.add\(record\)/);
    assert.match(read("lib/vinto/offline-lab-queue-store.ts"), /unique: true/);                 // one pending per draft
    assert.match(read("lib/vinto/offline-lab-queue-store.ts"), /keyPath: "capture_id"/);        // capture id is the primary key
});

test("the source draft becomes read-only once pending, failing closed", () => {
    const store = read("lib/vinto/offline-draft-store.ts");
    assert.match(store, /getLabPendingByDraft/);
    assert.match(store, /new DraftError\("pending_local"\)/);
    assert.match(store, /throw error instanceof DraftError \? error : new DraftError\("storage"\)/);
    // the application database structure and version stay as in OFF-02
    const app = read("lib/vinto/offline-store.ts");
    assert.match(app, /OFFLINE_DB_VERSION = 1;/);
    assert.doesNotMatch(app, /lab_pending|queued_local_simulation/);
});

test("no network, no innerHTML, no capture-flag or authorisation changes, no sync wording in the queue code", () => {
    for (const f of [...QUEUE_FILES, "lib/vinto/offline-draft-lab.ts", "lab/offline-lab.html"]) {
        const src = read(f);
        assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|apiBaseUrl|\/api\//, f);
        assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/, f);
        assert.doesNotMatch(src, /capture_eligible\s*=[^=]|captures_enabled\s*=[^=]|capture_eligible:\s*true|captures_enabled:\s*true/, f);
        assert.doesNotMatch(src, /localStorage\.setItem|sessionStorage|document\.cookie/, f);
    }
    const ui = read("lib/vinto/offline-draft-lab.ts") + read("lab/offline-lab.html");
    assert.match(ui, /Pendiente local — NO sincronizado/);
    assert.doesNotMatch(ui, />\s*(Enviar|Sincronizar|Aprobar)\b/);
});
