// E1-09: differential full frontend regression against the exact pre-E1 main baseline.
// This is NOT a waiver of the historical 32 failures: they remain reported.
// Any unexpected failed test, incomplete run, or runner error fails the job.
import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const baseline = JSON.parse(readFileSync(join(root, "scripts/e1-broad-regression-baseline.json"), "utf8"));
const known = new Set(baseline.failures);
if (baseline.failures.length !== 32 || known.size !== 32) {
  throw new Error("Baseline is missing or has duplicate entries");
}
const files = readdirSync(join(root, "scripts"))
  .filter(name => name.endsWith(".test.mjs")).sort()
  .map(name => join("scripts", name));
if (files.length < 60) throw new Error("Incomplete frontend test discovery");

const run = spawnSync(process.execPath, ["--test", ...files], {
  cwd: root,
  encoding: "utf8",
  maxBuffer: 128 * 1024 * 1024,
  env: { ...process.env, WORK_ORDER_LINE_EXECUTION_ENABLED: "false" },
});
const output = (run.stdout ?? "") + "\n" + (run.stderr ?? "");
const failures = [...output.matchAll(/^not ok \d+ - (.*)$/gm)].map(m => m[1].trim());
const summary = Object.fromEntries([...output.matchAll(/^# (tests|pass|fail|skipped) (\d+)/gm)]
  .map(m => [m[1], Number(m[2])]));
const unexpected = failures.filter(name => !known.has(name));
const historical = failures.filter(name => known.has(name));
const improved = baseline.failures.filter(name => !failures.includes(name));

console.log("E1 differential full frontend suite, source:", baseline.source);
console.log("CI test modules:", files.length);
console.log("Node TAP summary:", JSON.stringify(summary));
console.log("Historical baseline failures still present:", historical.length);
console.log("Historical baseline failures resolved:", improved.length);
console.log("NEW failures not present on main:", unexpected.length);
for (const name of unexpected) console.error("NEW FAILURE:", name);
// Diagnostico adicional sin cambiar la linea base ni las reglas del gate: muestra
// las aserciones del TAP que causaron una nueva falla, no solo su titulo.
if (unexpected.length > 0) {
  const lines = output.split("\n");
  for (const name of unexpected) {
    const start = lines.findIndex(line => /^not ok \d+ - /.test(line) && line.slice(line.indexOf(" - ") + 3).trim() === name);
    if (start < 0) continue;
    const end = lines.findIndex((line, i) => i > start && /^(?:not ok|ok) \d+ - |^# Subtest: /.test(line));
    const details = lines.slice(start, end < 0 ? Math.min(start + 48, lines.length) : Math.min(end, start + 48));
    console.error("NEW FAILURE DETAIL:", name, "\n" + details.join("\n"));
  }
}
for (const name of improved) console.log("HISTORICAL TEST FIXED:", name);

if (run.error || run.signal || run.status === null || (run.status !== 0 && failures.length === 0)) {
  console.error("Runner failed:", run.error?.message ?? run.signal ?? run.status);
  process.exit(1);
}
if (!Number.isInteger(summary.tests) || summary.tests < 990 ||
    !Number.isInteger(summary.fail) || summary.fail !== failures.length ||
    !Number.isInteger(summary.pass) || summary.pass < 900) {
  console.error("Incomplete or inconsistent TAP result; refusing to certify the regression.");
  process.exit(1);
}
if (unexpected.length > 0 || (run.status === 0 && failures.length > 0)) {
  console.error("E1 integration blocked: test failures beyond the pre-E1 baseline.");
  process.exit(1);
}
console.log("PASS: full frontend suite has zero new failures relative to exact pre-E1 main.");
console.log("WARNING: historical failures remain technical debt and were not counted as passing.");
