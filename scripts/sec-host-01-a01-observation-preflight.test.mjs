import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const path = new URL("./sec-host-01-a01-observation-preflight.sh", import.meta.url).pathname;
const source = readFileSync(path, "utf8");
const invoke = (...args) => spawnSync("bash", [path, ...args], {
  encoding: "utf8", timeout: 4000,
  env: { PATH: process.env.PATH, HOME: process.env.HOME },
});

test("only read-only audit mode exists; start/stop/apply are rejected", () => {
  assert.equal(invoke().status, 2);
  assert.equal(invoke("--help").status, 0);
  for (const mode of [
    "start", "stop", "apply", "enable", "disable", "rollback",
    "watch", "install", "observe", "reconfigure", "restore",
  ]) {
    const result = invoke(mode);
    assert.equal(result.status, 1, mode);
    assert.match(result.stderr, /BLOCKED_READ_ONLY_AUDIT_ONLY/, mode);
  }
});

test("target and PG credentials must come from private execution context", () => {
  for (const key of ["OBS_CONTAINER", "OBS_CONTAINER_ID", "OBS_DB", "OBS_ROLE"]) {
    assert.ok(source.includes(key), key);
  }
  assert.match(source, /\^\[0-9a-f\]\{64\}\$/);
  assert.match(source, /CONTAINER_ID_CHANGED/);
  assert.match(source, /TARGET_NOT_RUNNING/);
  assert.doesNotMatch(source, /(?:\b\d{1,3}\.){3}\d{1,3}\b|password=|PGPASSWORD|postgresql:\/\/|PGHOST=/i);
});

test("PostgreSQL read-only preflight checks version, GUC type, source and sink", () => {
  for (const expected of [
    "default_transaction_read_only=on",
    "statement_timeout=15000",
    "FROM pg_settings WHERE name = 'log_connections'",
    "server_version_num",
    "140000 AND 179999",
    "vartype = 'bool'",
    "context = 'superuser-backend'",
    "setting = 'off' AND NOT pending_restart",
    "source NOT IN ('command line', 'override')",
    "name = 'log_destination'",
    "name = 'logging_collector'",
    "name = 'log_statement'",
    "name = 'log_min_duration_statement'",
    "PASS_GUC_CANDIDATE_DISABLED",
    "PASS_STDERR_DIRECT",
    "NO_DATABASE_WRITES=PASS",
  ]) assert.ok(source.includes(expected), expected);
  assert.match(source, /psql -X -qAt -v ON_ERROR_STOP=1/);
});

test("preflight contains no SQL or shell mutation or access to raw connection logs", () => {
  assert.doesNotMatch(source, /ALTER SYSTEM|pg_reload_conf\(|pg_ctl reload|log_connections\s*=\s*(on|true)|log_disconnections\s*=\s*on/);
  assert.doesNotMatch(source, /docker (?:run|stop|restart|rm|exec .* psql .* -f)|systemctl (?:start|stop|restart|enable)|iptables -|nft add|ufw (?:allow|deny)|chmod |chown |tee |curl /);
  assert.doesNotMatch(source, /SELECT .*client_addr|pg_stat_activity|docker logs|journalctl|pg_read_file/);
});

test("cannot mistakenly claim external origins or automatic rollback are proven", () => {
  for (const marker of [
    "SEC_HOST_A01_LOG_SOURCE_FIDELITY=NOT_VERIFIED",
    "SEC_HOST_A01_LOG_RETENTION_AND_ACCESS=NOT_VERIFIED",
    "SEC_HOST_A01_AUTO_STOP_AND_RESTORE=NOT_INSTALLED",
    "SEC_HOST_A01_EXTERNAL_CLIENT_ORIGIN=NOT_VERIFIED",
    "SEC_HOST_A01_START_STOP=NOT_AUTHORIZED",
    "SEC_HOST_A01_PREFLIGHT=PASS_READ_ONLY_WITH_OPERATIONAL_GATES_OPEN",
  ]) assert.ok(source.includes(marker), marker);
});
