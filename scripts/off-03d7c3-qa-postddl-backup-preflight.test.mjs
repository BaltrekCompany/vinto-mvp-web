import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
const path=new URL("./off-03d7c3-qa-postddl-backup-preflight.sh",import.meta.url).pathname;
const s=readFileSync(path,"utf8");
const run=args=>spawnSync("bash",[path,...args],{
 encoding:"utf8",timeout:5000,env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test("only read-only inspect; deny backup, restore and deploy",()=>{
 assert.equal(run([]).status,2);
 assert.equal(run(["--help"]).status,0);
 for(const m of ["apply","backup","backup-restore","restore","install","migrate","seed","deploy","verify"]){
  const z=run([m]); assert.equal(z.status,1,m);
  assert.match(z.stderr,/only_read_only_inspect_permitted/);
 }
});
test("pin trusted postmigration QA audit and preserve pre-DDL B2",()=>{
 for(const marker of [
  "ebb773f88ba6740ddf4fef53f1b76de541346a85",
  "OFF03D6C3_AUDIT=PASS_READ_ONLY","OFF03D6C3_MIGRATION_HISTORY_31=PASS",
  "off03d6b2-*","off03d7c3-*","root:700",
  "OFF03D7C3_PRE_DDL_BACKUP_PRESERVED=PASS",
  "OFF03D7C3_POST_DDL_BACKUP=NOT_CREATED",
 ]) assert.ok(s.includes(marker),marker);
 assert.match(s,/bash "\$C3" audit/);
 assert.doesNotMatch(s,/bash .*off03d6b2.* verify|bash .*off03d6c1.* inspect/);
});
test("only QA container, tools and empty post-DDL baseline, NO writes",()=>{
 for(const marker of [
  "vinto-qa-postgres","vinto_qa_offline",
  "pg_dump pg_dumpall pg_restore","default_transaction_read_only=on",
  "vinto_meta.schema_migration","count(*) FROM vinto_config.form_version",
  "count(*) FROM vinto_audit.import_batch","OFF03D7C3_FREE_DISK_2GIB=PASS",
  "OFF03D7C3_BACKUP_RESTORE=NOT_AUTHORIZED",
  "OFF03D7C3_PREFLIGHT=PASS_READ_ONLY","NO_DATABASE_WRITES=PASS"
 ]) assert.ok(s.includes(marker),marker);
 assert.doesNotMatch(s,/pg_dump.*>\s*["']?\$BACKUPS|docker (?:run|stop|restart|rm|exec -i)|pg_restore --|migrate\.py|INSERT INTO|CREATE TABLE|DELETE FROM|ALTER TABLE|systemctl (?:start|restart|stop)|mktemp -d/);
});
