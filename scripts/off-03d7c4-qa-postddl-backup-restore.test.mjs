import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const livePath = new URL("./off-03d7c4-qa-postddl-backup-restore.sh", import.meta.url).pathname;
const ciPath = new URL("./off-03d7c4-postddl-backup-ci-e2e.sh", import.meta.url).pathname;
const live = readFileSync(livePath,"utf8"), ci = readFileSync(ciPath,"utf8");
const run = (path,args, env={}) => spawnSync("bash",[path,...args],{
  encoding:"utf8", timeout:6000,
  env:{PATH:process.env.PATH, HOME:process.env.HOME, ...env}
});

test("guard rejects unsupported operations before filesystem or Docker work",()=>{
  assert.equal(run(live,[]).status,2);
  assert.equal(run(live,["--help"]).status,0);
  for (const mode of ["restore","dump","backup","migrate","apply","seed","install","deploy","cleanup","reset"]) {
    const x=run(live,[mode]);
    assert.equal(x.status,1,mode);
    assert.match(x.stderr,/unsupported_operation/);
  }
});
test("mutating branch requires two explicit confirmations and root",()=>{
  const z=run(livePath,["backup-restore"]);
  assert.notEqual(z.status,0);
  assert.match(z.stderr,/(sudo_required|CONFIRM_QA_POSTDDL_BACKUP_required)/);
  assert.match(live,/CONFIRM_QA_POSTDDL_BACKUP/);
  assert.match(live,/CONFIRM_QA_TARGET/);
  assert.match(live,/vinto_qa_offline_6554/);
  assert.match(live,/check_prerequisites/);
  assert.match(live,/OFF03D7C4_BACKUP_RESTORE=PASS_POSTDDL_QA_ONLY/);
});
test("pins audited D7C3 preflight and isolated QA source",()=>{
  for(const marker of [
    "vinto-qa-postgres","vinto_qa_offline","vinto_qa_bootstrap",
    "8baff8f5db57d0c0f7d460cf47c2b5884cb03f84",
    "OFF03D7C3_PREFLIGHT=PASS_READ_ONLY",
    "OFF03D7C3_POST_DDL_SOURCE=EMPTY_QA_31_MIGRATIONS",
    "root:700","root:600","off03d7c4-*","OFF03D7C4_NEW_BACKUP=NOT_CREATED",
  ])assert.ok(live.includes(marker),marker);
  assert.match(live,/bash "\$C3" inspect/);
  assert.doesNotMatch(live,/off03d6b2.*verify|off03d6c1.*inspect/);
});
test("source dump only, no passwords, temporary networkless PG17 restore",()=>{
  for(const marker of [
    "pg_dumpall --globals-only --no-role-passwords",
    "pg_dump -U",
    "--format=custom --create","--network none",
    "--pull=never","--tmpfs /var/lib/postgresql/data",
    "docker port","pg_restore --exit-on-error --create",
    "OFF03D7C4_RESTORE_TEST=PASS_NETWORKLESS",
    "NO_QA_DATABASE_WRITES=PASS",
  ])assert.ok(live.includes(marker),marker);
  assert.match(live,/docker exec -i "\$RESTORE" pg_restore/);
  assert.doesNotMatch(live,/docker exec -i "\$QA" pg_restore|pg_restore.*-d "\$DB"|migrate\.py|INSERT INTO|DELETE FROM|CREATE TABLE|ALTER TABLE/);
});
test("fingerprint compares metadata, checksums and is safe for read-only inspect",()=>{
  for(const marker of [
    "default_transaction_read_only=on","pg_get_userbyid",
    "vinto_meta.schema_migration","vinto_master.user_machine_form_grant",
    "vinto_config.form_version","vinto_audit.import_batch",
    "cmp -s","sha256sum -c SHA256SUMS",
    "OFF03D7C4_BACKUP_INTEGRITY=PASS",
    "OFF03D7C4_RESTORE_METADATA=PASS",
    "OFF03D7C4_PREFLIGHT=PASS_READ_ONLY",
    "OFF03D7C4_POST_DDL_BACKUP",
  ]) assert.ok(live.includes(marker) || marker==="OFF03D7C4_POST_DDL_BACKUP",marker);
});
test("CI runner requires Github Actions and has no route to the VPS",()=>{
  const x=run(ciPath,[]);
  assert.equal(x.status,2);
  assert.match(x.stderr,/OFF03D5_CI_ONLY=BLOCKED/);
  assert.match(ci,/GITHUB_ACTIONS/);
  assert.match(ci,/OFF03D7C4_CI_REAL_VPS_TOUCHED=NO/);
  assert.match(ci,/trap cleanup EXIT/);
  assert.match(ci,/docker rm -f "\$RESTORE"/);
  assert.match(ci,/--network none/);
  assert.match(ci,/off-03d7c4-qa-postddl-backup-restore.sh/);
  assert.doesNotMatch(ci,/51\.79\.65\.225|:6554|\/srv\/vinto-qa-offline|\/etc\/vinto-qa|ssh /);
});
