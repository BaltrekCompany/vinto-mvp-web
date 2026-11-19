// OFF-04.2 / 04.2-R2 (laboratory): structural isolation, immutability and consistency contracts of the consolidated
// laboratory database. Behaviour (atomicity, races, tampering, migration, restart) is exercised in real Chrome by
// off-04-queue-browser.py and off-04-consistency-browser.py.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { captureIdFor, PENDING_SCHEMA } from "../lib/vinto/offline-lab-queue.ts";
import { isLabDraftRow, isLabPending, LAB_DB, LAB_EPOCH_KEY, LAB_STATUS } from "../lib/vinto/offline-lab-db.ts";
import { LEGACY_QUEUE_DB } from "../lib/vinto/offline-lab-migration.ts";

const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const U = (n) => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;

// Authorised laboratory code and QA scripts. Everything else (lib/, app/, backend/, build and other scripts) is operational.
const AUTHORISED = new Set(["lib/vinto/offline-lab-db.ts", "lib/vinto/offline-lab-queue.ts", "lib/vinto/offline-lab-migration.ts",
    "lib/vinto/offline-draft-store.ts", "lib/vinto/offline-draft-lab.ts", "lib/vinto/offline-quality-e2e-lab.ts"]);
const QA_SCRIPT = /^scripts\/(off-04-[A-Za-z0-9.-]+\.(ts|mjs|py)|off04_fixture\.py)$/;
const SOURCE = /\.(ts|tsx|mjs|js|py)$/;
const FORBIDDEN = /offline-lab-(queue|db|migration)|vinto-off04lab|lab_pending|lab_drafts|lab_quarantine|lab_meta|queued_local_simulation/;
const isOperational = (f) => SOURCE.test(f) && !AUTHORISED.has(f) && !QA_SCRIPT.test(f);
export function findForbiddenRefs(files, readFile) {
    return files.filter(f => isOperational(f) && FORBIDDEN.test(readFile(f)));
}
// Modules that must never see the application's offline database or its send queue.
const ISOLATED = ["lib/vinto/offline-lab-db.ts", "lib/vinto/offline-lab-queue.ts", "lib/vinto/offline-draft-store.ts"];
const LAB_CODE = [...ISOLATED, "lib/vinto/offline-lab-migration.ts", "lib/vinto/offline-draft-lab.ts", "lab/offline-lab.html"];

const sealed = { format: "aes-gcm-v1", iv: "AAAAAAAAAAAAAAAA", ciphertext: "A".repeat(40) };
const pending = () => ({
    capture_id: U(1), draftId: U(2), ownerId: U(3), deviceKey: U(4), formCode: "VINTO-P1-26", formVersion: 1, contextId: U(5),
    sourceRevision: 1, queuedAt: "2026-11-19T10:00:00.000Z", status: LAB_STATUS, lab: true, syncState: "NOT_SYNCED", sealed,
});
const draftRow = () => ({ id: U(2), ownerId: U(3), deviceKey: U(4), formCode: "VINTO-P1-26", formVersion: 1, contextId: U(5),
    savedAt: "2026-11-19T10:00:00.000Z", revision: 1, sealed });

test("capture id is deterministic per owner+browser+draft and UUIDv4-shaped", async () => {
    const a = await captureIdFor(U(3), U(4), U(2));
    assert.equal(a, await captureIdFor(U(3).toUpperCase(), U(4), U(2).toUpperCase()));
    assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    const others = await Promise.all([captureIdFor(U(6), U(4), U(2)), captureIdFor(U(3), U(6), U(2)), captureIdFor(U(3), U(4), U(6))]);
    assert.equal(new Set([a, ...others]).size, 4);
});

test("pending and draft row shapes are strict", () => {
    assert.equal(isLabPending(pending()), true);
    const bad = [{ ...pending(), status: "queued" }, { ...pending(), status: "synced" }, { ...pending(), lab: false }, { ...pending(), syncState: "SYNCED" },
        { ...pending(), extra: 1 }, { ...pending(), sourceRevision: 0 }, { ...pending(), capture_id: "x" }, { ...pending(), queuedAt: "ayer" },
        { ...pending(), sealed: { ...sealed, format: "plain" } }, (() => { const r = pending(); delete r.syncState; return r; })(), null, []];
    bad.forEach((b, i) => assert.equal(isLabPending(b), false, "pending " + i));
    assert.equal(LAB_STATUS, "queued_local_simulation");
    assert.match(PENDING_SCHEMA, /pending-sim/);
    assert.equal(isLabDraftRow(draftRow()), true);
    assert.equal(isLabDraftRow({ ...draftRow(), frozenBy: U(1) }), true);
    [{ ...draftRow(), frozenBy: "x" }, { ...draftRow(), extra: 1 }, { ...draftRow(), revision: 0 }, { ...draftRow(), id: "x" },
        (() => { const r = draftRow(); delete r.revision; return r; })(), null].forEach((b, i) => assert.equal(isLabDraftRow(b), false, "draft " + i));
});

test("structural isolation: one consolidated laboratory database, never the application database or its send queue", () => {
    assert.equal(LAB_DB, "vinto-off04lab-v2");
    assert.equal(LAB_EPOCH_KEY, "vinto-off04lab-epoch");
    assert.equal(LEGACY_QUEUE_DB, "vinto-off04lab-queue-v1");
    for (const f of ISOLATED) {
        const src = read(f);
        assert.doesNotMatch(src, /vinto-offline-v1|offline-store/, f);
        assert.doesNotMatch(src, /\boutbox\b|queueSealedDraft|listQueuedForOwner|saveSealedDraft|getSealedDraft|listSealedDrafts/, f);
        assert.doesNotMatch(src, /status:\s*"queued"|"queued"|'queued'/, f);
    }
    // nothing OPERATIONAL outside the laboratory references the simulated queue (a future sync engine cannot reach it by accident)
    const walk = (dir) => readdirSync(join(root, dir)).flatMap(n => {
        if (["node_modules", ".next", "dist", ".git"].includes(n)) return [];
        const rel = dir + "/" + n;
        return statSync(join(root, rel)).isDirectory() ? walk(rel) : [rel];
    });
    const files = [...walk("lib"), ...walk("app"), ...walk("scripts"), ...walk("backend/app")];
    const offenders = findForbiddenRefs(files, read);
    assert.deepEqual(offenders, [], "simulated-queue reference in operational code: " + offenders.join(", "));
    assert.ok(files.some(f => f.startsWith("lib/vinto/offline-store")) && files.some(f => f.startsWith("app/")));   // the scan is not vacuous
    assert.ok(files.every(f => !isOperational(f) || !AUTHORISED.has(f)));
    // the application's own offline database is unchanged
    const app = read("lib/vinto/offline-store.ts");
    assert.match(app, /OFFLINE_DB_VERSION = 1;/);
    assert.match(app, /for \(const name of \["drafts", "outbox"\]\)/);
    assert.doesNotMatch(app, /lab_pending|lab_drafts|queued_local_simulation|vinto-off04lab/);
});

test("immutability and atomicity by construction", () => {
    const db = read("lib/vinto/offline-lab-db.ts");
    assert.doesNotMatch(db, /\.(delete|clear|openCursor|openKeyCursor)\s*\(|deleteDatabase|deleteObjectStore/);       // no removal primitive at all
    assert.doesNotMatch(db, /\bpending\.(put|delete|clear)\(|S_PENDING\)\.(put|delete|clear)/);                           // pendings: add only
    for (const m of db.matchAll(/\b(\w+)\.put\(/g)) assert.ok(["drafts", "meta"].includes(m[1]), "put on " + m[1]);       // put only on drafts/meta
    assert.match(db, /unique: true/);
    assert.match(db, /keyPath: "capture_id"/);
    // the transition and every save are ONE transaction over drafts AND pendings
    const trans = db.slice(db.indexOf("export async function transitionLabDraft"), db.indexOf("/** All pending rows"));
    assert.match(trans, /writeTx<TransitionResult>\(db, \[S_DRAFTS, S_PENDING\]/);
    assert.match(trans, /pending\.add\(rec\)/);
    assert.match(trans, /drafts\.put\(\{ \.\.\.draft, frozenBy: rec\.capture_id \}\)/);
    assert.match(trans, /draft\.revision !== input\.expectedRevision \|\| draft\.sealed\.ciphertext !== input\.expectedCiphertext/);
    const save = db.slice(db.indexOf("export async function saveLabDraftRevision"), db.indexOf("// ---- pendings ----"));
    assert.match(save, /writeTx<void>\(db, \[S_DRAFTS, S_PENDING\]/);
    assert.match(save, /frozenReason\(existing, k, d\)/);
    assert.match(save, /existing\.revision !== expectedRevision/);
    // handlers are attached to BOTH lookups at once (a late handler would silently drop the save)
    assert.match(db, /function pair\(/);
    assert.doesNotMatch(db, /reqOk\(byKey/);
    // the draft is frozen by a marker on its own row, independent of the pending row
    assert.match(db, /frozenBy/);
    assert.match(read("lib/vinto/offline-draft-store.ts"), /saveLabDraftRevision/);
});

test("loss or replacement of the laboratory database is fail-closed, never recreated silently", () => {
    const db = read("lib/vinto/offline-lab-db.ts");
    assert.match(db, /oldVersion !== 0/);
    assert.match(db, /refused = new LabDbError\("lab_lost"\)/);
    assert.match(db, /epoch !== instance/);
    assert.match(db, /lab_mismatch/);
});

test("migration is non-destructive: reads legacy data, never writes, changes or deletes it", () => {
    const mig = read("lib/vinto/offline-lab-migration.ts");
    assert.doesNotMatch(mig, /saveSealedDraft|queueSealedDraft|deleteDatabase|\.put\(|\.delete\(|\.clear\(|\.add\(|readwrite/);
    assert.match(mig, /import \{ listSealedDrafts, type OfflineDraft \} from "\.\/offline-store\.ts"/);
    for (const fn of ["prepareLegacyMigration", "verifyMigrationPlan", "commitLegacyMigration", "verifyCommittedMigration", "runLegacyMigration"]) {
        assert.match(mig, new RegExp("export (async )?function " + fn));
    }
    assert.match(mig, /legacyFingerprint/);                                  // legacy sources are re-read and compared after the commit
    assert.match(mig, /request\.transaction\?\.abort\(\)/);                  // an absent legacy database is never created
    assert.match(read("lib/vinto/offline-lab-db.ts"), /commitMigrationBatch/);
});

test("no network, no innerHTML, no capture-flag or authorisation changes, no sync wording in the laboratory code", () => {
    for (const f of LAB_CODE) {
        const src = read(f);
        assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|apiBaseUrl|\/api\//, f);
        assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/, f);
        assert.doesNotMatch(src, /capture_eligible\s*=[^=]|captures_enabled\s*=[^=]|capture_eligible:\s*true|captures_enabled:\s*true/, f);
        assert.doesNotMatch(src, /sessionStorage|document\.cookie/, f);
        if (f !== "lib/vinto/offline-lab-db.ts") assert.doesNotMatch(src, /localStorage\.(setItem|removeItem|clear)/, f);   // only the epoch is ever written
    }
    assert.equal([...read("lib/vinto/offline-lab-db.ts").matchAll(/localStorage\.(setItem|removeItem)/g)].length, 1);   // epoch write only
    const ui = read("lib/vinto/offline-draft-lab.ts") + read("lab/offline-lab.html");
    assert.match(ui, /Pendiente local — NO sincronizado/);
    assert.match(ui, /Contenido CONGELADO/);
    assert.match(ui, /EN CUARENTENA/);
    assert.doesNotMatch(ui, />\s*(Enviar|Sincronizar|Aprobar|Eliminar|Borrar|Exportar)\b/);
});

test("the UI shows the frozen pending content, never a later draft version", () => {
    const ui = read("lib/vinto/offline-draft-lab.ts");
    assert.match(ui, /loadFrozenForDraft/);
    assert.match(ui, /const source = frozen \? frozen\.draft : loaded\.payload/);
    assert.match(ui, /renderEditor\(editing, frozen\.draft\.values/);
});

test("negative control: the isolation scanner flags operational code and ignores only authorised files", () => {
    const fake = { "lib/vinto/offline-sync-engine.ts": 'import { listLabPending } from "./offline-lab-db.ts";',
        "app/page.tsx": 'indexedDB.open("vinto-off04lab-v2")', "backend/app/x.py": "status = 'queued_local_simulation'",
        "scripts/build-offline-boot.mjs": "const s = 'lab_pending';", "lib/vinto/other.ts": "from 'offline-lab-migration'",
        "scripts/off-04-new-qa.py": "lab_pending", "lib/vinto/offline-draft-lab.ts": "offline-lab-queue", "scripts/off-04-evil.txt": "lab_pending",
        "lib/vinto/ok.ts": "nothing" };
    assert.deepEqual(findForbiddenRefs(Object.keys(fake), f => fake[f]).sort(),
        ["app/page.tsx", "backend/app/x.py", "lib/vinto/offline-sync-engine.ts", "lib/vinto/other.ts", "scripts/build-offline-boot.mjs"]);
    assert.equal(isOperational("scripts/off-04-queue.test.mjs"), false);
    assert.equal(isOperational("scripts/other/off-04-queue-browser.py"), true);
    assert.equal(isOperational("lib/vinto/offline-device.ts"), true);
});
