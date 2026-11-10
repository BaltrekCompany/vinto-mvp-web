import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { P112, P112_FIELDS, P112_LEGACY_FIELDS } from "../lib/vinto/p1-12.ts";

const seed = JSON.parse(readFileSync(new URL("../backend/seed_data/forms/VINTO-P1-12.json", import.meta.url), "utf8"));
const draft = { cantidad_jabas: "2", hora_inicio: "08:15", hora_fin: "09:05" };
const assign = "44444444-4444-4444-8444-444444444444";
const device = "99999999-9999-4999-8999-999999999999";
const captureId = "11111111-1111-4111-8111-111111111111";

function envelope(version, values, pallet) {
    return {
        id: captureId, status: "submitted", revision: 1,
        captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z",
        form: { code: "VINTO-P1-12", version_number: version, name: "Producción diaria de papel higiénico" },
        machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "MANANA", name: "Mañana" },
        operating_date: "2026-10-06", assignment: { id: assign },
        work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-001" },
        line: { id: "33333333-3333-4333-8333-333333333333", line_code: "L1", pv_reference: "PV-1",
                article: { code: "10351", description: "PERLITA ECO PLUS 4*12" } },
        values, ...(pallet === undefined ? {} : { pallet })
    };
}

test("P1-12 v4 solo solicita jabas y horas; formulario historico conservado", () => {
    assert.equal(seed.version_number, 4);
    assert.deepEqual(new Set(seed.fields.map(f => f.key)), new Set(["cantidad_jabas", "hora_inicio", "hora_fin"]));
    assert.deepEqual(new Set(P112_FIELDS.map(f => f.key)), new Set(seed.fields.map(f => f.key)));
    assert.equal(P112_LEGACY_FIELDS.length, 20);
    assert.ok(seed.fields.every(f => f.required));
});

test("valida jabas positivas y horas manuales; rechaza valores extra", () => {
    assert.equal(P112.createAttempt(draft, assign, device, () => captureId).ok, true);
    for (const bad of ["0", "-1", "1.5", "", " "]) {
        const result = P112.createAttempt({ ...draft, cantidad_jabas: bad }, assign, device, () => captureId);
        assert.equal(result.ok, false, bad);
    }
    const invalid = P112.createAttempt({ ...draft, hora_fin: "29:99" }, assign, device, () => captureId);
    assert.equal(invalid.ok, false);
});

test("P1-12 v4 solo acepta snapshots de pallet persistidos por backend", () => {
    const values = { cantidad_jabas: 2, hora_inicio: "08:15:00", hora_fin: "09:05:00" };
    const pallet = { number: 1, quantity_jabas: 2, nominal_weight_kg: "1.740000", total_weight_kg: "3.480000" };
    const parsed = P112.parseCapture(envelope(4, values, pallet));
    assert.ok(parsed);
    assert.equal(parsed.pallet.number, 1);
    assert.equal(parsed.pallet.total_weight_kg, "3.480000");
    assert.equal(P112.parseCapture(envelope(4, values)), null);
    assert.equal(P112.parseCapture(envelope(4, values, { ...pallet, number: 0 })), null);
});

test("las capturas P1-12 v3 continúan legibles sin pallet", () => {
    const old = envelope(3, { hora_inicio: "08:15:00", hora_fin: "09:05:00",
        empaque_saldo_inicial: "7", producto: "PERLITA", formato: "4*12" });
    const parsed = P112.parseCapture(old);
    assert.ok(parsed);
    assert.equal(parsed.values.formato, "4*12");
    assert.equal(parsed.pallet, undefined);
});
