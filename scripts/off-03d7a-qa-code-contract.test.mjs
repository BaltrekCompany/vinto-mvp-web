import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (p) => readFileSync(new URL("../" + p, import.meta.url), "utf8");

test("frontend candidate requires exact Node and pnpm toolchain", () => {
  const pkg = JSON.parse(read("package.json"));
  assert.equal(pkg.engines.node, ">=22.18.0");
  assert.equal(pkg.packageManager, "pnpm@11.25.0");
  assert.equal(pkg.scripts.build, "node scripts/run-framework.mjs build");
  assert.match(pkg.scripts.start, /wrangler.*dev.*--local/);
  assert.equal(pkg.scripts.dev, "node scripts/run-framework.mjs dev");
  assert.match(read("vite.config.ts"), /vinext\(\)/);
  assert.match(read("scripts/run-framework.mjs"), /buildOfflineBoot\(\)/);
});
test("public API URL is NOT safe by default; QA build must set same-origin HTTPS", () => {
  const api = read("lib/vinto/api.ts");
  assert.match(api, /NEXT_PUBLIC_API_URL/);
  assert.match(api, /http:\/\/127\.0\.0\.1:8000/);
  const frontend = read("lib/vinto/offline-scope-api.ts");
  assert.match(frontend, /window\.isSecureContext/);
  assert.match(frontend, /url\.protocol === "https:"/);
});
test("backend flags disabled by default and scopes require auth", () => {
  const cfg = read("backend/app/config.py");
  assert.match(cfg, /offline_scope_issue_enabled: bool = False/);
  assert.match(cfg, /offline_quality_package_issue_enabled: bool = False/);
  assert.match(cfg, /offline_scope_signing_seed_b64url: SecretStr \| None = None/);
  const r = read("backend/app/offline_scope/router.py");
  assert.match(r, /Depends\(current_user\)/);
  assert.match(r, /not settings\.offline_scope_issue_enabled/);
  assert.match(r, /not settings\.offline_quality_package_issue_enabled/);
  assert.match(r, /NO_STORE = \{"Cache-Control": "no-store"/);
});
test("QA middleware protects entire central API, not just OFF-04 flags", () => {
  const main = read("backend/app/main.py");
  const guard = read("backend/app/qa_offline_guard.py");
  assert.match(main, /@app\.middleware\("http"\)/);
  assert.match(main, /qa_offline_request_permitted/);
  assert.match(main, /status_code=403/);
  assert.match(guard, /if app_env != "qa":/);
  assert.match(guard, /\("POST", "\/api\/offline\/scope"\)/);
  assert.match(guard, /\("POST", "\/api\/offline\/quality-package"\)/);
  assert.doesNotMatch(guard, /\("POST", "\/api\/captures"\)/);
  assert.doesNotMatch(guard, /\("POST", "\/api\/admin\/users"\)/);
});
test("independent mobile QA protocol remains read-only", () => {
  const doc=read("docs/OFF-03C3-qa-movil-calidad.md");
  assert.match(doc, /M01/);
  assert.match(doc, /M11/);
  assert.match(doc, /N06/);
  assert.match(doc, /P1-18\/22\/26\/27/);
  const https=read("scripts/off-03d1-https-preflight.sh");
  assert.match(https, /OFF03D1_REMOTE_GATE=PASS_NETWORK_ONLY/);
  assert.match(https, /MOBILE_HARD_RESTART=NOT_RUN/);
});
