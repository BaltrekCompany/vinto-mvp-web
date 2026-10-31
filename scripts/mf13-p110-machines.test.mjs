// node --test scripts/mf13-p110-machines.test.mjs
// MF-13-01B.2 · VINTO-P1-10 v3 en las cinco rebobinadoras. La disponibilidad la decide SOLO el backend (GET /api/production/machines): el frontend ofrece P1-10 en una máquina únicamente si la respuesta
// la trae, reconoce la versión 3 con el mismo contrato de valores que la 2 y sigue leyendo las capturas de COPASA de la v2 y de la v1. Funciones puras: sin red, sin DOM.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";

import { offeredForms, parseAvailability, screenFor, sectorView } from "../lib/vinto/availability.ts";
import { CONTEXT_NOTES, P1_10_CODE, parseP110Capture, parseP110List, parseP110Values } from "../lib/vinto/p1-10.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");

const P110 = (version) => ({ code: P1_10_CODE, name: "Registro de fardos", version_number: version });
const OTHER = { BELOIT: { code: "VINTO-P1-07", name: "Registro de producción de bobinas rebobinadas", version_number: 2 }, OVER: { code: "VINTO-P1-07", name: "Registro de producción de bobinas rebobinadas", version_number: 2 },
  COPASA: { code: "VINTO-P1-07", name: "Registro de producción de bobinas rebobinadas", version_number: 2 }, PERICHUN: { code: "VINTO-P1-30", name: "Producción Perichun", version_number: 2 },
  TUBETERA: { code: "VINTO-P1-29", name: "Producción Tubetera", version_number: 2 } };
const FIVE = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"];
const machines = (withP110) => FIVE.map((code) => ({ code, name: code, forms: withP110(code) ? [OTHER[code], P110(3)] : [OTHER[code]] }));
const availability = (list) => parseAvailability({ sectors: [{ code: "REBOBINADO", name: "Rebobinado", machines: list }] });
const SCREEN = { "VINTO-P1-07": "p107", "VINTO-P1-30": "p130", "VINTO-P1-29": "p129", [P1_10_CODE]: "p110" };

test("con la v3 en la respuesta del backend, las cinco rebobinadoras ofrecen P1-10 con su pantalla y conservan sus otros formularios", () => {
  const view = sectorView(availability(machines(() => true)), "REBOBINADO");
  assert.equal(view.kind, "ready");
  assert.deepEqual(view.sector.machines.map((m) => m.code), FIVE);
  for (const machine of view.sector.machines) {
    const offered = offeredForms("REBOBINADO", machine);
    assert.deepEqual(offered.map((o) => o.form.code).sort(), [OTHER[machine.code].code, P1_10_CODE].sort(), machine.code);
    for (const { form, screen } of offered) assert.equal(screen, SCREEN[form.code], `${machine.code} ${form.code}`);
    assert.equal(offered.find((o) => o.form.code === P1_10_CODE).form.version_number, 3, "la versión que sirve el backend se conserva");
  }
});

test("la disponibilidad depende del backend: una máquina cuya respuesta no trae P1-10 no lo ofrece, aunque sea una de las cinco", () => {
  const view = sectorView(availability(machines((code) => code !== "OVER" && code !== "TUBETERA")), "REBOBINADO");
  const byMachine = Object.fromEntries(view.sector.machines.map((m) => [m.code, offeredForms("REBOBINADO", m).map((o) => o.form.code)]));
  assert.ok(byMachine.OVER.every((c) => c !== P1_10_CODE) && byMachine.TUBETERA.every((c) => c !== P1_10_CODE));
  for (const code of ["BELOIT", "COPASA", "PERICHUN"]) assert.ok(byMachine[code].includes(P1_10_CODE), code);
});

test("sin sector REBOBINADO en la respuesta (sin concesión o no operativo) la vista queda deshabilitada y no hay ningún formulario", () => {
  assert.deepEqual(sectorView(parseAvailability({ sectors: [] }), "REBOBINADO"), { kind: "disabled" });
  assert.deepEqual(sectorView(parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines: [{ code: "MP1", name: "MP1", forms: [] }] }] }), "REBOBINADO"), { kind: "disabled" });
});

test("P1-10 solo tiene pantalla en Rebobinado: en cualquier otro sector se informa «sin pantalla central»", () => {
  assert.equal(screenFor("REBOBINADO", P1_10_CODE), "p110");
  for (const sector of ["BOBINAS", "CONVERSION"]) assert.equal(screenFor(sector, P1_10_CODE), null, sector);
});

const envelope = (version, values, machine = "COPASA") => ({
  id: "11111111-1111-4111-8111-111111111111", status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: P1_10_CODE, version_number: version, name: "Registro de fardos" },
  machine: { code: machine, name: machine }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "44444444-4444-4444-8444-444444444444" },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const V2_VALUES = { peso_fardo: "12,5 kg", hora_inicio: "06:30:00", hora_fin: "14:45:00" };
const V1_VALUES = { codigo_numero_de_producto: "EJ-PROD", numero_de_fardo: "00-0042", peso_fardo: "12,5 kg" };

test("la versión 3 se lee con el mismo contrato de valores que la 2 (peso y dos horas), en cualquiera de las cinco máquinas", () => {
  for (const machine of FIVE) {
    const capture = parseP110Capture(envelope(3, V2_VALUES, machine));
    assert.ok(capture, machine);
    assert.deepEqual(capture.values, V2_VALUES);
    assert.equal(capture.machine.code, machine);
  }
  assert.deepEqual(parseP110Values(V2_VALUES, 3), parseP110Values(V2_VALUES, 2), "v3 y v2 comparten parser");
  assert.equal(parseP110Capture(envelope(3, V1_VALUES)), null, "los valores de la v1 (número de fardo) no son válidos en la v3");
  assert.equal(parseP110Capture(envelope(3, { ...V2_VALUES, hora_fin: undefined })), null, "las horas siguen siendo obligatorias");
});

test("las capturas históricas de COPASA (v2 y v1) siguen leyéndose junto a las nuevas", () => {
  const list = parseP110List([envelope(1, V1_VALUES), envelope(2, V2_VALUES), envelope(3, V2_VALUES)]);
  assert.deepEqual(list.map((c) => c.form.version_number), [1, 2, 3]);
  assert.deepEqual(list[0].values, V1_VALUES, "la v1 conserva su número de fardo");
});

test("la nota de la máquina ya no dice «por confirmar» y no se inventa ninguna regla nueva", () => {
  assert.ok(!/Por confirmar/.test(CONTEXT_NOTES.maquina.pending));
  assert.match(CONTEXT_NOTES.maquina.pending, /Beloit, Over, Copasa, Perichun y Tubetera/);
  assert.equal(Object.keys(CONTEXT_NOTES).join(), "fecha,maquina,responsable,firma");
  for (const key of ["responsable", "firma"]) assert.match(CONTEXT_NOTES[key].pending, /Por (confirmar|definir)/, `${key} sigue pendiente`);
});

test("el frontend no fija la lista de máquinas de P1-10: la pantalla se enruta por (sector, formulario), no por máquina", () => {
  const source = read("lib/vinto/availability.ts").replace(/\/\/[^\n]*/g, "");
  assert.ok(!/COPASA|BELOIT|PERICHUN|TUBETERA/.test(source), "availability.ts no nombra máquinas");
  const page = read("components/vinto/p1-10-capture.tsx").replace(/\/\/[^\n]*/g, "");
  assert.ok(!/["'`]COPASA["'`]/.test(page), "la pantalla P1-10 no se limita a COPASA");
});
