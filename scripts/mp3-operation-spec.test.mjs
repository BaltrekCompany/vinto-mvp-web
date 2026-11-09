import test from "node:test";
import assert from "node:assert/strict";
import {
    MP3_INSPECTION_FORM_CODE,
    MP3_INSPECTION_MACHINE,
    MP3_INSPECTION_PRINT_CODE,
    MP3_INSPECTION_CAPTURE_POLICY,
    MP3_INSPECTION_SECTIONS,
    MP3_INSPECTION_FIELDS,
    MP3_INSPECTION_CONTEXT,
} from "../lib/vinto/mp3-operation-spec.ts";

test("RG-MP3-01 is a distinct machine-specific contract", () => {
    assert.equal(MP3_INSPECTION_FORM_CODE, "VINTO-MP3-01");
    assert.equal(MP3_INSPECTION_PRINT_CODE, "RG-MP3-01");
    assert.equal(MP3_INSPECTION_MACHINE, "MP3");
    assert.equal(MP3_INSPECTION_CAPTURE_POLICY, "one_per_machine_operating_date_shift");
    assert.equal(MP3_INSPECTION_SECTIONS.length, 20);
});

test("all seven Pulper fields mandatory and every other measurement optional", () => {
    const [pulper, ...other] = MP3_INSPECTION_SECTIONS;
    assert.equal(pulper.title, "Pulper");
    assert.equal(pulper.fields.length, 7);
    assert.ok(pulper.fields.every(f => f.kind === "decimal" && f.required));
    assert.ok(other.flatMap(s => s.fields).every(f => !f.required));
});

test("no repeated keys and no manual red header or signature fields", () => {
    const keys = MP3_INSPECTION_FIELDS.map(f => f.key);
    assert.equal(new Set(keys).size, keys.length);
    assert.ok(keys.every(k => /^[a-z][a-z0-9_]*$/.test(k)));
    for (const prohibited of ["operador", "fecha", "turno", "firma", "revisado", "gramaje_producto"]) {
        assert.ok(keys.every(k => !k.includes(prohibited)), prohibited);
    }
    assert.ok(MP3_INSPECTION_CONTEXT.includes("operador_autenticado"));
    assert.ok(MP3_INSPECTION_CONTEXT.includes("turno"));
});

test("repeated printed labels have independent typed slots", () => {
    const check = (label, count) => {
        const fields = MP3_INSPECTION_FIELDS.filter(f => f.label === label);
        assert.equal(fields.length, count, label);
        assert.equal(new Set(fields.map(f => f.key)).size, count);
        assert.ok(fields.every(f => f.kind === "decimal" && !f.required));
    };
    check("Vacuómetro", 3);
    check("Caudal agua sello", 3);
    check("Bomba BA2", 2);
    check("Bomba BA3", 2);
    check("Mezcla F.C./F.L.", 2);
    check("Consistencia", 2);
    check("Apertura bomba B8", 2);
});

test("chemical slots are decimals and cleaning remains free text", () => {
    const chemicals = MP3_INSPECTION_SECTIONS.find(s => s.title === "Químicos");
    const cleaning = MP3_INSPECTION_SECTIONS.find(s => s.title === "Limpieza");
    const drive = MP3_INSPECTION_SECTIONS.find(s => s.title === "Accionamientos");
    assert.ok(chemicals);
    assert.equal(chemicals.fields.length, 10);
    assert.ok(chemicals.fields.every(f => f.kind === "decimal" && !f.required));
    assert.ok(cleaning);
    assert.equal(cleaning.fields.length, 6);
    assert.ok(cleaning.fields.every(f => f.kind === "text"));
    assert.equal(drive?.fields.find(f => f.key === "accion_vel_maquina")?.kind, "decimal");
});

test("blade changes are manual times and novedades is optional multiline", () => {
    const blade = MP3_INSPECTION_SECTIONS.find(s => s.title === "Horas de cambio de cuchillas");
    const notes = MP3_INSPECTION_SECTIONS.find(s => s.title === "Novedades");
    assert.ok(blade?.fields.every(f => f.kind === "time"));
    assert.equal(blade?.fields.length, 3);
    assert.equal(notes?.fields[0].kind, "textarea");
    assert.equal(notes?.fields[0].required, false);
});
