import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';

const file=new URL('./off-03d6b2-qa-backup-restore.sh',import.meta.url).pathname;
const src=readFileSync(file,'utf8');
const run=args=>spawnSync('bash',[file,...args],{
  encoding:'utf8',timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test('help and no supported mutation except explicitly confirmed backup-restore',()=>{
  const h=run(['--help']);
  assert.equal(h.status,0,h.stderr);
  assert.match(h.stdout,/backup-restore/);
  for(const mode of ['migrate','apply','install','drop','restore','cleanup','deploy']){
    const res=run([mode]);
    assert.equal(res.status,1);
    assert.match(res.stderr,/operacion no soportada/);
  }
  assert.equal(run([]).status,2);
});
test('no confirmation -> backup-restore refuses regardless of execution privileges',()=>{
  const res=run(['backup-restore']);
  assert.notEqual(res.status,0);
  assert.match(res.stderr,/(requiere sudo|CONFIRM_QA_BACKUP_RESTORE)/);
});
test('source checks B1 pin and separates QA from pilot/TVC',()=>{
  assert.match(src,/B1_BLOB=d398cedb367c151b3bb0a916c1d59f610a441703/);
  assert.match(src,/bash "\$B1" verify \|\| die/);
  assert.match(src,/QA=vinto-qa-postgres/);
  assert.match(src,/DB=vinto_qa_offline/);
  assert.match(src,/127\.0\.0\.1:6554/);
  assert.match(src,/vinto-qa-internal/);
});
test('dump reads only and passwords excluded; restore has no network or persistent volume',()=>{
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/pg_dumpall --globals-only --no-role-passwords/);
  assert.match(src,/pg_dump -U "\$BOOT" -d "\$DB" --format=custom --create/);
  assert.match(src,/--network none/);
  assert.match(src,/--tmpfs \/var\/lib\/postgresql\/data/);
  assert.match(src,/--pull=never/);
  assert.match(src,/pg_restore --exit-on-error --create/);
  assert.match(src,/sha256sum -c SHA256SUMS/);
  assert.match(src,/cmp -s "\$BACKUP\/origin\.json" "\$BACKUP\/restored\.json"/);
  assert.match(src,/OFF03D6B2_RESTORE_TEST=PASS_NETWORKLESS/);
  assert.match(src,/NO_QA_DATABASE_WRITES=PASS/);
  assert.doesNotMatch(src,/migrate\.py|--target dev|docker (?:volume rm|network create)|pg_restore.*\$QA|pg_restore.*vinto-qa-postgres/);
});
