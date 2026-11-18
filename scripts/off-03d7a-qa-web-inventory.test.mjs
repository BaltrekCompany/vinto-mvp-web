import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const path = new URL("./off-03d7a-qa-web-inventory.sh", import.meta.url).pathname;
const src = readFileSync(path, "utf8");
const run = (args) => spawnSync("bash", [path, ...args], {
  encoding: "utf8", timeout: 4000,
  env: { PATH: process.env.PATH, HOME: process.env.HOME },
});

test("only inspect accepted; help and negative modes never touch VPS", () => {
  const help = run(["--help"]);
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /inspect/);
  for (const arg of ["install", "prepare", "deploy", "migrate", "apply", "rollback", "reset"]) {
    const res = run([arg]);
    assert.equal(res.status, 2, arg);
    assert.match(res.stderr, /only inspect permitted/);
  }
  assert.equal(run([]).status, 2);
});

test("TLS is validated without redirect, insecure bypass or credentials", () => {
  assert.match(src, /DOMAIN=qa-vinto-mvp\.baltrekservices\.com/);
  assert.match(src, /IP=51\.79\.65\.225/);
  assert.match(src, /--proto '=https'/);
  assert.match(src, /--max-redirs 0/);
  assert.match(src, /--noproxy '\*'/);
  assert.match(src, /OFF03D7A_QA_TLS_TRUST_CHAIN=PASS/);
  assert.match(src, /OFF03D7A_QA_ROOT_HTTP=404_NOT_READY/);
  assert.doesNotMatch(src, /--insecure|curl\s+-k\b|--location|--cookie/);
});

test("ports and pilot services are observational only", () => {
  assert.match(src, /for port in 3200 8200/);
  assert.match(src, /FREE_NOT_RESERVED/);
  assert.match(src, /for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web/);
  assert.match(src, /for ctr in vinto-mvp-postgres postgres-vinto vinto-qa-postgres/);
  assert.match(src, /OFF03D7A_NGINX_ROUTE=UNVERIFIED/);
  assert.match(src, /OFF03D7A_INVENTORY=COMPLETE_READ_ONLY/);
  assert.doesNotMatch(src, /docker (?:run|restart|stop|rm|exec)|systemctl (?:restart|start|stop)|nginx -s|docker compose|pg_restore|migrate\.py|git (?:checkout|pull|reset|switch)/);
});
