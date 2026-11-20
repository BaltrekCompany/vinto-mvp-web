// OFF-04.5A / OFF-04.5B-06B: structural contracts of the end-to-end Quality laboratory (bridge between the lab pending queue and the sync engine; same-origin real-session client).
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const E2E = "lib/vinto/offline-quality-e2e-lab.ts";
const src = read(E2E), html = read("lab/offline-e2e-lab.html");

test("the E2E page is lab-only, opt-in at build time and never reaches the app's offline database or send queue", () => {
    assert.doesNotMatch(src, /vinto-offline-v1|offline-store|\boutbox\b|queueSealedDraft|listQueuedForOwner|saveSealedDraft|listSealedDrafts|offline-lab-migration/);
    assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/);
    assert.doesNotMatch(src, /capture_eligible\s*=[^=]|captures_enabled\s*=[^=]|capture_eligible:\s*true|captures_enabled:\s*true/);
    assert.doesNotMatch(src, /sessionStorage|document\.cookie|localStorage\.(setItem|removeItem|clear)/);
    const build = read("scripts/build-offline-boot.mjs");
    assert.match(build, /public\/offline-e2e-lab\.html/);
    assert.match(build, /offline-quality-e2e-lab\.ts/);
    assert.match(build, /process\.env\.OFFLINE_DRAFT_LAB !== "1"/);
    assert.match(read("public/sw.js"), /\/offline-e2e-lab\.html/);
    assert.match(read(".gitignore"), /\/public\/offline-e2e-lab\.html/);
    assert.doesNotMatch(read("public/offline.html"), /offline-e2e-lab/);
    // nothing operational references this module
    const walk = (dir) => readdirSync(join(root, dir)).flatMap(n => {
        if (["node_modules", ".next", "dist", ".git"].includes(n)) return [];
        const rel = dir + "/" + n;
        return statSync(join(root, rel)).isDirectory() ? walk(rel) : [rel];
    });
    for (const f of [...walk("lib"), ...walk("app")]) {
        if (f === E2E || !/\.(ts|tsx)$/.test(f)) continue;
        assert.doesNotMatch(read(f), /offline-quality-e2e-lab|offline-e2e-lab/, f);
    }
});

test("the only network access is ONE fetch, to the page's OWN origin, with the real cookie and no identity header; there is no way to name another URL", () => {
    assert.equal([...src.matchAll(/\bfetch\s*\(/g)].length, 1);
    assert.doesNotMatch(src, /XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts/);
    assert.match(src, /credentials: "include"/);
    assert.match(src, /cache: "no-store"/);
    assert.match(src, /fetch\(path, \{/);                                                       // a RELATIVE path, never a composed URL
    assert.match(src, /\^\\\/api\\\/\[A-Za-z0-9_\\-\/\]\*\$/);                                  // api() only accepts /api/... paths
    assert.match(src, /location\.protocol === "https:" \|\| \(location\.protocol === "http:" && \(location\.hostname === "127\.0\.0\.1" \|\| location\.hostname === "localhost"\)\)/);
    assert.doesNotMatch(src, /URLSearchParams|location\.search|[?&]receiver=|X-Synthetic-User|X-Synthetic|OTHER_USER/);
    assert.doesNotMatch(src, /https?:\/\/(?!127\.0\.0\.1|localhost)/);
    assert.doesNotMatch(src, /\bnew URL\(|\bnew Request\(/);
    assert.doesNotMatch(html, /e2e-session|receiver=|X-Synthetic/);
    assert.match(src, /if \(!session \|\| syncing \|\| !ONLINE_OK\) return;/);
    assert.match(src, /syncButton\.disabled = !ONLINE_OK/);
    const paths = [...src.matchAll(/api\("(?:GET|POST)", "([^"]+)"/g)].map(m => m[1]).sort();
    assert.deepEqual([...new Set(paths)], ["/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/offline/bobbin-context", "/api/offline/quality-package", "/api/offline/scope"]);
});

test("login, enrolment and sync use the existing building blocks and the ORIGINAL author's real session", () => {
    assert.match(src, /import \{ interpretLogin, interpretSession, type AuthUser \} from "\.\/auth\.ts"/);
    assert.match(src, /createLocalVault\(identity, secret\)/);
    assert.match(src, /storeOfflineScope\(key, identity, envelope, envelope\.public_key_b64url\)/);        // the key is pinned from the authenticated online response
    assert.match(src, /storeQualityPackage\(key, identity, pkgRes\.json\)/);
    assert.match(src, /record\.ownerId !== identity\.ownerId \|\| record\.deviceKey !== identity\.deviceKey/);  // never replaces another user's profile
    assert.match(src, /session: async \(\) => \{ const me = await currentUser\(\); return me\.status === "ok" \? \{ userId: me\.user\.id\.toLowerCase\(\) \} : null; \}/);
    assert.match(src, /probe\.status === "unreachable"/);                                                     // offline: nothing is sent, nothing changes
    assert.match(src, /loginPass\.value = ""/);                                                              // the password never stays in the DOM
    assert.doesNotMatch(src, /localStorage\.setItem\([^)]*(password|secret|token)/i);
    assert.match(html, /e2e-login-form/); assert.match(html, /e2e-prepare-form/); assert.match(html, /autocomplete="current-password"/);
});

test("the bridge is explicit and keeps identity: same capture_id, frozen content only, original author, one record", () => {
    assert.match(src, /async function bridgeToSync\(/);
    assert.match(src, /loadFrozenForDraft\(session\.key, session\.identity, draftId\)/);
    assert.match(src, /captureId: frozen\.capture_id/);
    assert.match(src, /payload: frozen\.draft\.values/);
    assert.match(src, /bobbinContextVersion\(frozen\.draft\.scope_snapshot_id, b\.bobbin_id, b\.context_digest\) : frozen\.draft\.scope_snapshot_id/);   // OFF-04.6: machine forms keep the snapshot; by-bobbin forms bind the bobbin
    assert.match(src, /bridge\.addEventListener\("click"/);                       // only a user click bridges; nothing is bridged automatically
    assert.equal([...src.matchAll(/bridgeToSync\(/g)].length, 2);                   // definition + the single click handler
    assert.match(src, /if \(r\.stage === "pending"\)/);                             // only frozen pendings can be bridged
});

test("the UI distinguishes local save, technical receipt and industrial approval, with all seven required states", () => {
    for (const key of ["draft", "pending", "queued", "syncing", "synced", "synced_warning", "requires_review", "conflict"]) assert.match(src, new RegExp("\\b" + key + ":"));
    assert.match(src, /Guardado localmente/);
    assert.match(src, /Pendiente de sincronización/);
    assert.match(src, /Sincronizando/);
    assert.match(src, /Sincronizado: recepción técnica confirmada \(NO es aprobación industrial\)/);
    assert.match(src, /Sincronizado con advertencia/);
    assert.match(src, /Requiere revisión/);
    assert.match(src, /Conflicto/);
    assert.match(html, /Sincronizar ahora/);
    assert.match(html, /NO es aprobación industrial/);
    assert.match(html, /No usa el outbox operativo ni habilita captura industrial/);
    assert.match(src, /Contadores:/);
    assert.doesNotMatch(src + html, />\s*(Aprobar|Liberar|Eliminar|Borrar)\b/);
});
