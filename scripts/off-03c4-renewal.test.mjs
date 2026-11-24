// OFF-03C.4: pure renewal logic and static safety contracts (no IndexedDB, no network).
// The browser/IndexedDB behaviour is exercised in real Chrome by off-03c4-renewal-browser.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { compareScopeFreshness, verifyOfflineScope, ScopeError } from "../lib/vinto/offline-scope-verify.ts";
import { planRenewalPairs, DISCARD_CONFIRMATION } from "../lib/vinto/offline-renewal.ts";
import { validStoredScope } from "../lib/vinto/offline-scope-store.ts";

const path = process.env.OFF03C4_FIXTURE_JSON;
if (!path) throw new Error("Python signed renewal fixture required (OFF03C4_FIXTURE_JSON)");
const fx = JSON.parse(readFileSync(path, "utf8"));
const identity = fx.identity;
const pin = fx.scopes.old.public_key_b64url;
const verified = async (name) => verifyOfflineScope(fx.scopes[name], pin, identity);
const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");

test("Python-signed scenario scopes verify under the pin, except foreign key/user/browser", async () => {
    for (const name of ["old", "new", "newer", "reduced", "downgrade", "older", "same_second"]) {
        const scope = await verified(name);
        assert.equal(scope.payload.captures_enabled, false, name);
    }
    await assert.rejects(verified("rotated_key"), e => e instanceof ScopeError && e.reason === "pin_mismatch");
    await assert.rejects(verified("other_user"), e => e instanceof ScopeError && e.reason === "identity_mismatch");
    await assert.rejects(verified("other_device"), e => e instanceof ScopeError && e.reason === "identity_mismatch");
});

test("anti-rollback ordering: only a strictly newer snapshot, or the identical one, is acceptable", async () => {
    const old = await verified("old");
    assert.equal(compareScopeFreshness(await verified("new"), old), "newer");
    assert.equal(compareScopeFreshness(await verified("older"), old), "older");
    assert.equal(compareScopeFreshness(await verified("same_second"), old), "ambiguous");
    assert.equal(compareScopeFreshness(old, old), "identical");
    const sameSnapshotAltered = structuredClone(old);
    sameSnapshotAltered.payload.form_scopes = old.payload.form_scopes.slice(0, 1);
    assert.equal(compareScopeFreshness(sameSnapshotAltered, old), "ambiguous");
    const unparsable = structuredClone(old);
    unparsable.payload.issued_at = "not-a-date";
    assert.equal(compareScopeFreshness(unparsable, old), "ambiguous");
});

test("renewal plan keeps granted packages, retires revoked ones and refuses ungranted extras", async () => {
    const pairs = [{ machine_code: "MP1", form_code: "VINTO-P1-18" }, { machine_code: "MP1", form_code: "VINTO-P1-22" }];
    const same = planRenewalPairs(pairs, [], await verified("new"));
    assert.deepEqual(same.renew, pairs);
    assert.deepEqual(same.removed, []);
    const reduced = planRenewalPairs(pairs, [], await verified("reduced"));
    assert.deepEqual(reduced.renew, [pairs[1]]);
    assert.deepEqual(reduced.removed, [pairs[0]]);
    const extra = planRenewalPairs([], [{ machine_code: "MP3", form_code: "VINTO-P1-26" }], await verified("new"));
    assert.deepEqual(extra.renew, []);
    assert.deepEqual(extra.missingExtra, [{ machine_code: "MP3", form_code: "VINTO-P1-26" }]);
    // non-Quality operations or forms outside P1-18/22/26/27 are never packaged
    const odd = structuredClone(await verified("new"));
    odd.payload.form_scopes[0].operation = "production_capture";
    assert.deepEqual(planRenewalPairs(pairs, [], odd).removed, [pairs[0]]);
});

test("local record schema is explicit: legacy v1 readable, unknown versions refused", () => {
    const id = { ownerId: identity.ownerId, deviceKey: identity.deviceKey };
    const base = { profileId: id.ownerId + ":" + id.deviceKey, ownerId: id.ownerId, deviceKey: id.deviceKey,
        snapshotId: "33333333-3333-4333-8333-333333333333", sealed: { format: "aes-gcm-v1", iv: "x", ciphertext: "y" } };
    assert.equal(validStoredScope(base, id), true);                                      // pre-OFF-03C.4 record
    assert.equal(validStoredScope({ ...base, schemaVersion: 2, renewal: { a: 1 } }, id), true);
    assert.equal(validStoredScope({ ...base, schemaVersion: 3 }, id), false);
    assert.equal(validStoredScope({ ...base, renewal: "plaintext" }, id), false);
    assert.equal(validStoredScope({ ...base, ownerId: "77777777-7777-4777-8777-777777777777" }, id), false);
});

test("renewal module: one atomic transaction, compare-and-swap, no network, no plaintext markers", () => {
    const src = read("lib/vinto/offline-renewal.ts");
    const writes = src.match(/db\.transaction\(\[[^\]]*\], "readwrite"\)/g) ?? [];
    assert.equal(writes.length, 1, "the commit must be a SINGLE multi-store readwrite transaction");
    assert.match(src, /\["profiles", SCOPE_STORE_NAME, PACKAGE_STORE_NAME\], "readwrite"/);
    assert.match(src, /expectedScopeSnapshotId/);
    assert.match(src, /stop\("conflict"\)/);
    assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|innerHTML|document\.|localStorage|sessionStorage/);
    assert.doesNotMatch(src, /from "\.\/offline-(scope|quality)-api/);          // network is injected
    // the only delete lives in the explicit, token-guarded cleanup, never in renewal/boot
    assert.equal((src.match(/\.delete\(/g) ?? []).length, 1);
    assert.match(src, /confirmation !== DISCARD_CONFIRMATION/);
    assert.equal(DISCARD_CONFIRMATION, "DISCARD_SUPERSEDED_PACKAGES");
    assert.match(src, /sealLocalDraft\(key, markerBinding\(identity, content\.snapshotId\), content\)/);
    assert.doesNotMatch(src, /form_scopes[^;\n]*sealMarker|sealMarker[^;\n]*form_scopes/);
    // steps happen in this order: verify -> encrypt -> commit
    assert.ok(src.indexOf("verifyOfflineScope(") < src.indexOf("sealScopeRecord(key"));
    assert.ok(src.indexOf("sealPackageRecord(key") < src.indexOf("await commit({"));
});

test("boot withholds a revoked set and never starts a capture path", () => {
    const boot = read("lib/vinto/offline-boot.ts");
    assert.match(boot, /readRenewalStatus\(/);
    assert.match(boot, /revocation_known/);
    assert.match(boot, /withheld/);
    assert.doesNotMatch(boot, /fetch\s*\(|innerHTML|postCapture|submitCapture|sendCapture|renewOfflineBundle/);
    const page = read("app/offline-preparacion/page.tsx");
    assert.match(page, /renewOfflineBundle\(/);
    assert.match(page, /allowReplaceUnreadable: recover/);
    assert.doesNotMatch(page, /discardSupersededPackages/);                          // cleanup is not wired to the UI
});

test("legacy standalone paths cannot orphan packages or accept a rollback", () => {
    const store = read("lib/vinto/offline-scope-store.ts");
    assert.match(store, /renewal_required/);
    assert.match(store, /compareScopeFreshness\(verified, earlier\.envelope\)/);
    assert.match(store, /PACKAGE_STORE_NAME/);
});

test("public cache rotated for the new offline runtime and API is still never cached", () => {
    const sw = read("public/sw.js");
    assert.match(sw, /vinto-off048-quality-static-v4/);
    assert.match(sw, /name\.startsWith\("vinto-off03c3-"\)/);
    assert.match(sw, /url\.pathname\.startsWith\("\/api\/"\)/);
    assert.match(sw, /if \(request\.method !== "GET"\) return;/);
    assert.doesNotMatch(sw, /offline\/(scope|quality-package)/);
});

test("IndexedDB schema version and store names are unchanged (no destructive migration)", () => {
    const profile = read("lib/vinto/offline-profile-store.ts");
    assert.match(profile, /PROFILE_DB_VERSION = 3;/);
    assert.match(read("public/offline-device-qa.js"), /const VERSION = 3;/);
    assert.doesNotMatch(profile, /deleteObjectStore|\.clear\(\)/);
});

// ---------------- OFF-03C.4-R1 / R2 (security review of PR #225) ----------------
test("R1: a refused (HTTP 403) renewal never claims persistence that was not confirmed", () => {
    const src = read("lib/vinto/offline-renewal.ts");
    assert.doesNotMatch(src, /recordRevocationKnown\([^)]*\)\s*\.catch\(/, "persistence errors must not be swallowed");
    assert.equal((src.match(/await refuse\(/g) ?? []).length, 2, "scope and package 403 share one fail-closed path");
    assert.match(src, /new RenewalError\("revoked_unrecorded"\)/);
    assert.match(src, /noteUnrecordedRevocation\(profileId, observedAt\.getTime\(\)\)/);
    // the status reader must consult the fallback, so the boot screen stays closed
    assert.match(src, /unrecordedRevocationAt\(raw\.profileId\)/);
    assert.match(src, /durable: false/);
});

test("R2: commit compare-and-swap includes the sealed renewal marker and stays one transaction", () => {
    const src = read("lib/vinto/offline-renewal.ts");
    assert.match(src, /markerFingerprint\(s\.renewal\) !== plan\.expectedRenewalFingerprint/);
    assert.match(src, /const observedFingerprint = markerFingerprint\(rawScope\.renewal\)/);
    // observed BEFORE any network I/O, so a marker written by another tab during preparation is detected
    assert.ok(src.indexOf("const observedFingerprint") < src.indexOf("await deps.fetchScope("));
    assert.equal((src.match(/db\.transaction\(\[[^\]]*\], "readwrite"\)/g) ?? []).length, 1);
    // the fingerprint only ever uses iv + ciphertext, never decrypted content
    assert.match(src, /sealed\.format \+ "\." \+ sealed\.iv \+ "\." \+ sealed\.ciphertext/);
});

test("fallback memory stores only a numeric time per profile key and fails open to history, never to a grant", async () => {
    const data = new Map();
    globalThis.localStorage = {
        getItem: k => (data.has(k) ? data.get(k) : null), setItem: (k, v) => { data.set(k, String(v)); },
        removeItem: k => { data.delete(k); },
    };
    const { noteUnrecordedRevocation, unrecordedRevocationAt, clearUnrecordedRevocation } =
        await import("../lib/vinto/offline-revocation-fallback.ts?case=1");
    const profile = "11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222";
    assert.equal(unrecordedRevocationAt(profile), null);
    noteUnrecordedRevocation(profile, 1_800_000_000_000);
    noteUnrecordedRevocation(profile, 1_700_000_000_000);                    // older observation never lowers it
    assert.equal(unrecordedRevocationAt(profile), 1_800_000_000_000);
    assert.deepEqual([...data.entries()], [["vinto:off03c4:revoked:" + profile, "1800000000000"]]);
    clearUnrecordedRevocation(profile, 1_799_999_999_999);                   // renewal that began BEFORE the refusal
    assert.equal(unrecordedRevocationAt(profile), 1_800_000_000_000);
    clearUnrecordedRevocation(profile, 1_800_000_000_000);                   // renewal that began at/after it
    assert.equal(unrecordedRevocationAt(profile), null);
    assert.equal(data.size, 0);
    data.set("vinto:off03c4:revoked:" + profile, "not-a-number");           // tampered value is ignored
    assert.equal(unrecordedRevocationAt(profile), null);
    // storage that refuses writes: the in-memory layer still closes this context
    globalThis.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("quota"); }, removeItem: () => { throw new Error("blocked"); } };
    noteUnrecordedRevocation(profile, 1_900_000_000_000);
    assert.equal(unrecordedRevocationAt(profile), 1_900_000_000_000);
    delete globalThis.localStorage;
});

test("fallback module holds no permissions, ciphertext, tokens or network access", () => {
    const src = read("lib/vinto/offline-revocation-fallback.ts");
    for (const word of ["form_scopes", "Authorization", "cookie", "sessionStorage", "indexedDB"]) assert.ok(!src.includes(word), word);
    assert.doesNotMatch(src, /\bfetch\s*\(|document\.|innerHTML/);
    assert.match(src, /\^\\d\{10,16\}\$/);
});
