/**
 * RG-MP3-01: generador reproducible y aditivo para el bundle oficial.
 * --emit produce JSON en una sola línea para revisión/conexión GitHub.
 * --check compara los archivos comprometidos; nunca altera el bundle.
 * No muta BD ni el inventario de MP1/P1-01.
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { MP3_INSPECTION_FIELDS, MP3_INSPECTION_FORM_CODE } from "../lib/vinto/mp3-operation-spec.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const seedDir = root + "backend/seed_data/";
const path = `forms/${MP3_INSPECTION_FORM_CODE}.json`;
const sourcePath = "lib/vinto/mp3-operation-spec.ts";
const sha256 = s => createHash("sha256").update(s, "utf8").digest("hex");
const canonical = obj => Array.isArray(obj)
    ? `[${obj.map(canonical).join(",")}]`
    : obj !== null && typeof obj === "object"
        ? `{${Object.keys(obj).sort().map(k => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(",")}}`
        : JSON.stringify(obj);

const definition = {
    legacy_key: "form_mp3_rg01_operacion_inspeccion_maquina",
    code: MP3_INSPECTION_FORM_CODE,
    legacy_number: null,
    name: "Operación e inspección de máquina MP3",
    area: "production",
    workflow: "production-standard",
    version_number: 1,
    machines: ["MP3"],
    groups: [],
    fields: MP3_INSPECTION_FIELDS.map((f, index) => ({
        key: f.key, label: f.label, value_type: f.kind,
        source: "manual", required: f.required, unit: null,
        display_order: index + 1,
    })),
};
const form = { schema_version: 1, ...definition, definition_checksum: sha256(canonical(definition)) };
const formText = JSON.stringify(form, null, 2) + "\n";

const manifest = JSON.parse(readFileSync(seedDir + "manifest.json", "utf8"));
const source = readFileSync(root + sourcePath, "utf8").replace(/\r\n/g, "\n");
const existingFile = manifest.files.find(x => x.path === path);
const existingSource = manifest.generated_from.find(x => x.path === sourcePath);
const existingScope = manifest.scope.forms.includes(MP3_INSPECTION_FORM_CODE);

if (existingFile || existingSource || existingScope) {
    if (!existingFile || !existingSource || !existingScope)
        throw new Error("RG01 partially registered: refuse to generate inconsistent manifest");
    if (existingFile.sha256 !== sha256(formText) || existingFile.bytes !== Buffer.byteLength(formText, "utf8"))
        throw new Error("RG01 form manifest does not match generated contract");
    if (existingSource.sha256 !== sha256(source))
        throw new Error("RG01 source checksum does not match");
} else {
    manifest.files.push({ path, sha256: sha256(formText), bytes: Buffer.byteLength(formText, "utf8") });
    manifest.files.sort((a,b) => a.path.localeCompare(b.path, "en"));
    manifest.scope.forms.push(MP3_INSPECTION_FORM_CODE);
    manifest.counts.forms += 1;
    manifest.counts.form_fields += definition.fields.length;
    manifest.generated_from.push({
        path: sourcePath, sha256: sha256(source), scope: `mp3-rg01-fields:${MP3_INSPECTION_FORM_CODE}`,
    });
}

const manifestText = JSON.stringify(manifest, null, 2) + "\n";

if (process.argv.includes("--check")) {
    for (const [p, expected] of [[path,formText],["manifest.json",manifestText]]) {
        if (!existsSync(seedDir + p) || readFileSync(seedDir + p, "utf8").replace(/\r\n/g,"\n") !== expected)
            throw new Error("RG01 generated file stale: " + p);
    }
    console.log(`MP3_RG01_BUNDLE_CHECK=PASS (${definition.fields.length} fields)`);
} else if (process.argv.includes("--emit")) {
    console.log("MP3_FORM_JSON_START" + JSON.stringify(form) + "MP3_FORM_JSON_END");
    console.log("MP3_MANIFEST_JSON_START" + JSON.stringify(manifest) + "MP3_MANIFEST_JSON_END");
} else {
    console.log("Use --emit or --check. This script never writes files.");
}
