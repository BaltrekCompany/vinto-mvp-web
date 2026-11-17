import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const file = new URL('./off-03d3-qa-schema-preflight.sh', import.meta.url).pathname;
const source = readFileSync(file, 'utf8');
function run(args) {
  return spawnSync('bash', [file, ...args], {
    encoding: 'utf8',
    timeout: 7000,
    env: { PATH: process.env.PATH, HOME: process.env.HOME },
  });
}
test('help is read-only and documented', () => {
  const r = run(['--help']);
  assert.equal(r.status, 0);
  assert.match(r.stdout, /Solo lectura/);
});
test('unknown operation is fail-closed', () => {
  const r = run(['install']);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /operacion no soportada/);
});
test('missing argument is rejected', () => {
  const r = run([]);
  assert.equal(r.status, 2);
});
test('source pins QA identity and inspects PostgreSQL metadata read-only', () => {
  assert.match(source, /vinto-qa-postgres/);
  assert.match(source, /vinto_qa_offline/);
  assert.match(source, /vinto-qa-offline-pgdata/);
  assert.match(source, /127\.0\.0\.1:\$QA_PORT/);
  assert.match(source, /default_transaction_read_only=on/);
  assert.match(source, /QA_APPLICATION_ROLES_ABSENT=PASS/);
  assert.match(source, /QA_MIGRATION_HISTORY_ABSENT=PASS/);
  assert.doesNotMatch(source, /docker (?:run|create|rm|stop|restart|exec -i|volume create|network create)/);
});
