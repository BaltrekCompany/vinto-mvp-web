// OFF-04.3: structural isolation and safety contracts of the synchronisation engine laboratory.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { TERMINAL_STATES, DONE_STATES } from "../lib/vinto/offline-sync-types.ts";

const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const SYNC = ["types", "rules", "engine", "fake-server", "store", "capture", "lab"].map(n => `lib/vinto/offline-sync-${n}.ts`);
const AUTHORISED = new Set(SYNC);
const QA_SCRIPT = /^scripts\/(off-04-[A-Za-z0-9.-]+\.(ts|mjs|py)|off04_fixture\.py)$/;
const SOURCE = /\.(ts|tsx|mjs|js|py)$/;
const FORBIDDEN = /offline-sync-(types|rules|engine|fake-server|store|capture|lab)|vinto-off043|sync_queue|offline-sync-lab/;
const isOperational = (f) => SOURCE.test(f) && !AUTHORISED.has(f) && !QA_SCRIPT.test(f) && f !== "scripts/build-offline-boot.mjs";
export function findSyncRefs(files, readFile) { return files.filter(f => isOperational(f) && FORBIDDEN.test(readFile(f))); }

test("states are exactly the seven of OFF-01 V2 section 8 (uncertain is a flag, not a state)", () => {
    const types = read("lib/vinto/offline-sync-types.ts");
    const m = types.match(/export type SyncState =([^;]+);/)[1];
    assert.deepEqual([...m.matchAll(/"(\w+)"/g)].map(x => x[1]).sort(),
        ["conflict", "queued", "requires_review", "retry_wait", "synced", "synced_warning", "syncing"]);
    assert.deepEqual([...TERMINAL_STATES].sort(), ["conflict", "requires_review", "synced", "synced_warning"]);
    assert.deepEqual([...DONE_STATES].sort(), ["synced", "synced_warning"]);
    assert.match(types, /uncertain: boolean/);
});

test("the engine is separate from the application outbox and from the synthetic lab pending queue", () => {
    for (const f of SYNC) {
        const src = read(f);
        assert.doesNotMatch(src, /vinto-offline-v1|offline-store|\boutbox\b|queueSealedDraft|listQueuedForOwner|saveSealedDraft/, f);
        assert.doesNotMatch(src, /offline-lab-(db|queue|migration)|vinto-off04lab|lab_pending|lab_drafts|queued_local_simulation|offline-draft-store/, f);
    }
    // ... and the synthetic lab queue never references the engine
    for (const f of ["lib/vinto/offline-lab-db.ts", "lib/vinto/offline-lab-queue.ts", "lib/vinto/offline-lab-migration.ts", "lib/vinto/offline-draft-store.ts", "lib/vinto/offline-draft-lab.ts"]) {
        assert.doesNotMatch(read(f), /offline-sync-|vinto-off043|sync_queue/, f);
    }
    assert.match(read("lib/vinto/offline-sync-store.ts"), /vinto-off043-sync-lab-v1/);
    // the application's own offline database is unchanged
    assert.match(read("lib/vinto/offline-store.ts"), /OFFLINE_DB_VERSION = 1;/);
});

test("nothing operational references the engine laboratory (scan with negative control)", () => {
    const walk = (dir) => readdirSync(join(root, dir)).flatMap(n => {
        if (["node_modules", ".next", "dist", ".git"].includes(n)) return [];
        const rel = dir + "/" + n;
        return statSync(join(root, rel)).isDirectory() ? walk(rel) : [rel];
    });
    const files = [...walk("lib"), ...walk("app"), ...walk("scripts"), ...walk("backend/app")];
    const offenders = findSyncRefs(files, read);
    assert.deepEqual(offenders, [], "operational code references the sync laboratory: " + offenders.join(", "));
    assert.ok(files.some(f => f.startsWith("lib/vinto/offline-store")) && files.some(f => f.startsWith("app/")));
    const fake = { "lib/vinto/offline-engine-bridge.ts": 'import "./offline-sync-engine.ts"', "app/page.tsx": 'indexedDB.open("vinto-off043-sync-lab-v1")',
        "backend/app/x.py": "t = 'sync_queue'", "lib/vinto/offline-sync-lab.ts": "offline-sync-engine", "scripts/off-04-new.py": "sync_queue", "lib/vinto/ok.ts": "x" };
    assert.deepEqual(findSyncRefs(Object.keys(fake), f => fake[f]).sort(), ["app/page.tsx", "backend/app/x.py", "lib/vinto/offline-engine-bridge.ts"]);
});

test("no real network access anywhere in the engine laboratory; the only transport is the fake server", () => {
    for (const f of SYNC) {
        const src = read(f);
        assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|apiBaseUrl|\/api\/|https?:\/\//, f);
        assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/, f);
        assert.doesNotMatch(src, /capture_eligible\s*=[^=]|captures_enabled\s*=[^=]|capture_eligible:\s*true|captures_enabled:\s*true/, f);
        assert.doesNotMatch(src, /sessionStorage|document\.cookie|localStorage\.(setItem|removeItem)/, f);
    }
    const lab = read("lib/vinto/offline-sync-lab.ts") + read("lab/offline-sync-lab.html");
    assert.match(lab, /FakeSyncServer/);
    assert.match(lab, /SERVIDOR SIMULADO/);
    assert.match(lab, /Sincronizar ahora/);
    assert.match(lab, /NO se conecta con FastAPI/);
});

test("engine safety rules are present: stable id, reconcile-before-repeat, identity, integrity, lease, no deletion", () => {
    const eng = read("lib/vinto/offline-sync-engine.ts");
    assert.doesNotMatch(eng, /randomUUID|Math\.random\(\)\s*\)\s*\.slice/);                           // the engine never mints identifiers
    assert.match(eng, /capture_id: rec\.capture_id/);
    assert.match(eng, /if \(rec\.uncertain \|\| claim\.recovered\)/);
    assert.ok(eng.indexOf("transport.lookup") < eng.indexOf("transport.send"), "lookup precedes send");
    assert.match(eng, /lc\(session\.userId\) !== lc\(deps\.identity\.ownerId\)/);
    assert.match(eng, /lc\(listed\.ownerId\) !== lc\(session\.userId\)/);
    assert.match(eng, /hash !== rec\.payloadSha256/);
    assert.match(eng, /paused = "different_user"/);
    assert.match(eng, /paused = "session_invalid"/);
    assert.match(eng, /status === 401/);
    assert.match(eng, /status === 403/);
    assert.match(eng, /retries_exhausted/);
    assert.match(eng, /running\.has\(guard\)/);
    const rules = read("lib/vinto/offline-sync-rules.ts");
    assert.match(rules, /rec\.lease\.until > now/);
    assert.match(rules, /rec\.lease\.owner !== tabId/);
    const store = read("lib/vinto/offline-sync-store.ts");
    assert.doesNotMatch(store, /\.(delete|clear|openCursor)\s*\(|deleteDatabase|deleteObjectStore/);   // records are never removed
    assert.match(store, /oncomplete/);
    const types = read("lib/vinto/offline-sync-types.ts");
    assert.match(types, /lookup\(captureId: string/);
});

test("the laboratory ships only with the opt-in flag and is absent from default builds", () => {
    const build = read("scripts/build-offline-boot.mjs");
    assert.match(build, /public\/offline-sync-lab\.html/);
    assert.match(build, /public\/offline-sync-lab\.js/);
    assert.match(build, /process\.env\.OFFLINE_DRAFT_LAB !== "1"/);
    assert.match(build, /offline-sync-lab\.ts/);
    const sw = read("public/sw.js");
    assert.match(sw, /\/offline-sync-lab\.html/);
    assert.match(sw, /const PUBLIC_ASSETS = \["\/offline\.html", "\/offline-probe\.js", "\/offline-boot\.js", "\/offline-device-qa\.js", "\/manifest\.webmanifest", "\/favicon\.svg"\]/);
    assert.match(read(".gitignore"), /\/public\/offline-sync-lab\.html/);
    assert.doesNotMatch(read("public/offline.html"), /offline-sync-lab/);
});
