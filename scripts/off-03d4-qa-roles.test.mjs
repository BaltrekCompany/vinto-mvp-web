import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const file = new URL('./off-03d4-qa-roles.sh', import.meta.url).pathname;
const source = readFileSync(file, 'utf8');
function invoke(args, extraEnv={}) {
  return spawnSync('bash', [file, ...args], {
    encoding: 'utf8', timeout: 8000,
    env: {PATH: process.env.PATH, HOME: process.env.HOME, ...extraEnv},
  });
}
test('help is non-destructive and lists separate commands',()=>{
  const x=invoke(['--help']);
  assert.equal(x.status,0);
  assert.match(x.stdout,/preflight/);
  assert.match(x.stdout,/verify/);
  assert.match(x.stdout,/install/);
});
test('install without explicit gate fails before checking Docker and touching files',()=>{
  const x=invoke(['install']);
  assert.notEqual(x.status,0);
  assert.match(x.stderr,/CONFIRM_QA_ROLE_CREATE=YES/);
  assert.doesNotMatch(x.stdout,/CREANDO SOLO ROLES QA/);
});
test('invalid command fails closed',()=>{
  const x=invoke(['drop']);
  assert.notEqual(x.status,0);
  assert.match(x.stderr,/operacion no soportada/);
});
test('missing mode fails closed',()=>{
  const x=invoke([]);
  assert.equal(x.status,2);
});
test('installer pins SQL blobs, QA target and transfers passwords on stdin',()=>{
  assert.match(source,/SOURCE_COMMIT=0e68f40396ab1b506e52897c7aa17f2890aab77c/);
  assert.match(source,/SQL00_BLOB=28a1ddbfa24297f730bf68092aa477d827e8fcdb/);
  assert.match(source,/SQL01_BLOB=306c452381b12b2a194ee0173346372179c290d6/);
  assert.match(source,/git hash-object/);
  assert.match(source,/CONFIRM_QA_ROLE_CREATE/);
  assert.match(source,/vinto_qa_offline/);
  assert.match(source,/vinto-qa-postgres/);
  assert.match(source,/127\.0\.0\.1:6554/);
  assert.match(source,/postgres-bootstrap\.password/);
  assert.match(source,/IFS= read -r APP_PASSWORD/);
  assert.match(source,/default_transaction_read_only=on/);
  assert.match(source,/QA_ROLE_AUTH=PASS/);
  assert.doesNotMatch(source,/--env[ =](APP_PASSWORD|MIGRATOR_PASSWORD|REFERENCE_PASSWORD)/);
  assert.doesNotMatch(source,/docker (?:stop|restart|rm|volume rm|network rm|system prune)/);
});
