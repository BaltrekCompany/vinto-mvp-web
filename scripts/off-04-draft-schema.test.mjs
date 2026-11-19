// OFF-04.1 (laboratory): pure draft schema/validation and static safety contracts.
// IndexedDB/vault behaviour is exercised in real Chrome by off-04-drafts-browser.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { verifyOfflineScope } from "../lib/vinto/offline-scope-verify.ts";
import { verifyQualityPackage } from "../lib/vinto/offline-quality-verify.ts";
import {
    buildDraftPayload, contextIdFor, draftMatchesDefinition, editableFields, evaluateDraft, isLabEligible,
    parseDraftPayload, DRAFT_SCHEMA,
} from "../lib/vinto/offline-draft-schema.ts";

const path = process.env.OFF04_FIXTURE_JSON;
if (!path) throw new Error("Python signed lab fixture required (OFF04_FIXTURE_JSON)");
const fx = JSON.parse(readFileSync(path, "utf8"));
const identity = fx.identity;
const pin = fx.scope.public_key_b64url;
const scope = await verifyOfflineScope(fx.scope, pin, identity);
const pkg = await verifyQualityPackage(fx.package, { envelope: scope, trustedPublicKey: pin }, identity);
const pkg2 = await verifyQualityPackage(fx.package_v2, { envelope: await verifyOfflineScope(fx.scope_v2, pin, identity), trustedPublicKey: pin }, identity);
const def = pkg.envelope.payload.definition;
const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const good = {
    numero_de_cuba: "C-001", tipo_pasta: "estandar", masa_humeda_g: "120,50", masa_seca_g: "30.1",
    cantidad_muestras: "3", fecha_muestreo: "2026-11-18", hora_muestreo: "08:30", muestra_valida: true, observaciones: "ok",
};
const codes = (r) => r.typeIssues.map(i => i.key + ":" + i.code).sort();

test("signed synthetic lab package verifies; only SYNTHETIC definitions are lab-eligible", async () => {
    assert.equal(def.capture_eligible, false);
    assert.equal(pkg.envelope.payload.captures_enabled, false);
    assert.equal(isLabEligible(def), true);
    const real = await verifyQualityPackage(fx.non_lab_package, { envelope: await verifyOfflineScope(fx.non_lab_scope, fx.non_lab_scope.public_key_b64url, identity),
        trustedPublicKey: fx.non_lab_scope.public_key_b64url }, identity);
    assert.equal(isLabEligible(real.envelope.payload.definition), false);        // an ordinary package is never editable here
    const renamed = { ...def, form_name: "Control de pasta" };
    assert.equal(isLabEligible(renamed), false);
    assert.equal(isLabEligible({ ...def, note: "Official published definition" }), false);
});

test("valid values normalise; calculated fields are never editable or stored", () => {
    const r = evaluateDraft(def, good);
    assert.deepEqual(r.typeIssues, []);
    assert.deepEqual(r.missingRequired, []);
    assert.equal(r.clean.masa_humeda_g, "120.50");                                // comma -> dot, text not float
    assert.equal(r.clean.muestra_valida, true);
    assert.equal("consistencia_pct" in r.clean, false);
    assert.deepEqual(editableFields(def).map(f => f.key).includes("consistencia_pct"), false);
    assert.deepEqual(codes(evaluateDraft(def, { ...good, consistencia_pct: "25.00" })), ["consistencia_pct:calculated"]);
    assert.deepEqual(codes(evaluateDraft(def, { ...good, campo_inventado: "x" })), ["campo_inventado:unknown"]);
});

test("required fields keep a draft incomplete but never block saving; typed errors do block", () => {
    const empty = evaluateDraft(def, {});
    assert.deepEqual(empty.missingRequired.map(i => i.key).sort(),
        ["cantidad_muestras", "fecha_muestreo", "masa_humeda_g", "masa_seca_g", "muestra_valida", "numero_de_cuba", "tipo_pasta"]);
    assert.deepEqual(empty.typeIssues, []);
    assert.deepEqual(evaluateDraft(def, { numero_de_cuba: "   ", observaciones: "" }).clean, {});   // blanks are absent
    const partial = evaluateDraft(def, { numero_de_cuba: "C-1" });
    assert.equal(partial.missingRequired.some(i => i.key === "numero_de_cuba"), false);
});

test("types and closed option lists are enforced exactly as the definition states", () => {
    const bad = {
        masa_humeda_g: "12,3,4", masa_seca_g: "abc", cantidad_muestras: "3.5", fecha_muestreo: "2026-02-30",
        hora_muestreo: "25:00", muestra_valida: "true", tipo_pasta: "inventada", numero_de_cuba: "x".repeat(201),
    };
    assert.deepEqual(codes(evaluateDraft(def, bad)), [
        "cantidad_muestras:type", "fecha_muestreo:type", "hora_muestreo:type", "masa_humeda_g:type", "masa_seca_g:type",
        "muestra_valida:type", "numero_de_cuba:too_long", "tipo_pasta:option"]);
    assert.deepEqual(codes(evaluateDraft(def, { numero_de_cuba: "a\u0000b" })), ["numero_de_cuba:type"]);
    assert.deepEqual(codes(evaluateDraft(def, { observaciones: "x".repeat(2001) })), ["observaciones:too_long"]);
    assert.deepEqual(codes(evaluateDraft(def, { observaciones: "línea 1\nlínea 2\tok" })), []);
    for (const ok of ["0", "-5", "123456789012", "12.345678"]) assert.deepEqual(codes(evaluateDraft(def, { masa_seca_g: ok })), [], ok);
    for (const nok of ["1234567890123", "1.1234567", ".5", "5.", "1e3", "٣"]) assert.deepEqual(codes(evaluateDraft(def, { masa_seca_g: nok })), ["masa_seca_g:type"], nok);
    assert.deepEqual(codes(evaluateDraft(def, { fecha_muestreo: "2024-02-29" })), []);
    assert.deepEqual(codes(evaluateDraft(def, { fecha_muestreo: "2023-02-29" })), ["fecha_muestreo:type"]);
});

test("context id is a stable UUID bound to machine, form and signed-scope snapshot", async () => {
    const a = await contextIdFor(scope.payload.snapshot_id, "MP1", "VINTO-P1-26");
    assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.equal(a, await contextIdFor(scope.payload.snapshot_id.toUpperCase(), "MP1", "VINTO-P1-26"));
    assert.notEqual(a, await contextIdFor(scope.payload.snapshot_id, "MP3", "VINTO-P1-26"));
    assert.notEqual(a, await contextIdFor("11111111-1111-4111-8111-111111111111", "MP1", "VINTO-P1-26"));
});

test("draft payload is strict: draft state only, synthetic only, exact keys, scalar values", () => {
    const id = "99999999-9999-4999-8999-999999999999";
    const payload = buildDraftPayload({ pkg: pkg.envelope.payload, ownerId: identity.ownerId, deviceKey: identity.deviceKey },
        id, evaluateDraft(def, good).clean, 1, "2026-11-18T12:00:00.000Z", "2026-11-18T12:00:00.000Z");
    assert.equal(payload.schema, DRAFT_SCHEMA);
    assert.equal(payload.status, "draft");
    assert.equal(payload.synthetic, true);
    assert.deepEqual(parseDraftPayload(structuredClone(payload)), payload);
    const rejects = [
        { ...payload, status: "queued" }, { ...payload, synthetic: false }, { ...payload, extra: 1 }, { ...payload, revision: 0 },
        { ...payload, values: { a: { nested: 1 } } }, { ...payload, values: { a: 5 } }, { ...payload, draft_id: "x" },
        { ...payload, definition_sha256: "zz" }, { ...payload, updated_local: "ayer" }, { ...payload, schema: "other" },
    ];
    for (const bad of rejects) assert.throws(() => parseDraftPayload(bad), /OFFLINE_DRAFT_SCHEMA_INVALID/);
    const missing = { ...payload };
    delete missing.synthetic;
    assert.throws(() => parseDraftPayload(missing), /INVALID/);
});

test("a draft is editable only against the SAME definition (version, checksum, hash)", () => {
    const payload = buildDraftPayload({ pkg: pkg.envelope.payload, ownerId: identity.ownerId, deviceKey: identity.deviceKey },
        "99999999-9999-4999-8999-999999999999", {}, 1, "2026-11-18T12:00:00.000Z", "2026-11-18T12:00:00.000Z");
    assert.equal(draftMatchesDefinition(payload, pkg.envelope.payload), true);
    assert.equal(draftMatchesDefinition(payload, pkg2.envelope.payload), false);
});

test("no central call, no queue, no capture flag changes anywhere in the lab code", () => {
    const files = ["lib/vinto/offline-draft-schema.ts", "lib/vinto/offline-draft-store.ts", "lib/vinto/offline-draft-lab.ts", "lab/offline-lab.html"];
    for (const f of files) {
        const src = read(f);
        assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|apiBaseUrl|\/api\//, f);
        assert.doesNotMatch(src, /queueSealedDraft|listQueuedForOwner|outbox|status:\s*"queued"|"queued"/, f);
        assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/, f);
        assert.doesNotMatch(src, /capture_eligible\s*=[^=]|captures_enabled\s*=[^=]|capture_eligible:\s*true|captures_enabled:\s*true/, f);
        assert.doesNotMatch(src, /localStorage\.setItem|sessionStorage|document\.cookie/, f);
    }
    // the new store primitive never touches the outbox for writing
    const store = read("lib/vinto/offline-store.ts");
    const fn = store.slice(store.indexOf("export async function saveSealedDraftRevision"), store.indexOf("export async function getSealedDraft"));
    assert.doesNotMatch(fn, /outbox\.(add|put|delete|clear)|status:\s*"queued"/);
    assert.match(fn, /stop\("already_queued"\)/);
});

test("lab is opt-in at build time and absent from default builds; SW install list is unchanged", () => {
    const build = read("scripts/build-offline-boot.mjs");
    assert.match(build, /process\.env\.OFFLINE_DRAFT_LAB !== "1"/);
    assert.match(build, /rmSync\(file, \{ force: true \}\)/);
    assert.match(build, /offline-draft-lab\.ts/);
    const ignore = read(".gitignore");
    assert.match(ignore, /\/public\/offline-lab\.html/);
    assert.match(ignore, /\/public\/offline-draft-lab\.js/);
    const sw = read("public/sw.js");
    assert.match(sw, /const PUBLIC_ASSETS = \["\/offline\.html", "\/offline-probe\.js", "\/offline-boot\.js", "\/offline-device-qa\.js", "\/manifest\.webmanifest", "\/favicon\.svg"\]/);
    assert.match(sw, /LAB_PATHS/);
    assert.doesNotMatch(sw, /offline-lab[^\n]*addAll|addAll[^\n]*offline-lab/);
    assert.doesNotMatch(read("public/offline.html"), /offline-lab|offline-draft-lab/);   // no link from the operator shell
});

test("existing OFF-02 store contract is unchanged: version, stores and plaintext rejection", () => {
    const store = read("lib/vinto/offline-store.ts");
    assert.match(store, /OFFLINE_DB_VERSION = 1;/);
    assert.match(store, /for \(const name of \["drafts", "outbox"\]\)/);
    assert.match(store, /OFFLINE_OWNER_INDEX = "ownerDevice"/);
});
