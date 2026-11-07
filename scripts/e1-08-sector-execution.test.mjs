// E1-08: sector-neutral UI execution selector contract via Vite SSR.
// Reinforces that the same started-line choice applies to Rebobinado and
// Conversión without guessing a product or granting permission in the UI.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { before, after, test } from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const tmp = join(root, ".tmp-e108-test-" + process.pid);
const alias = { name: "at-alias", enforce: "pre", resolveId(source) {
    if (!source.startsWith("@/")) return null;
    const base = root + "/" + source.slice(2);
    for (const ext of [".tsx", ".ts", "/index.tsx", "/index.ts"]) {
        if (existsSync(base + ext)) return base + ext;
    }
    return null;
} };
async function bundle(component) {
    const buildResult = await build({
        configFile: false, root, logLevel: "error", plugins: [alias],
        build: { write: false, ssr: join(root, component), minify: false,
            target: "node22", rollupOptions: { output: { format: "es" } } },
    });
    const chunk = (Array.isArray(buildResult) ? buildResult[0] : buildResult)
        .output.find(x => x.type === "chunk");
    writeFileSync(join(tmp, "selector.mjs"), chunk.code);
    return import(pathToFileURL(join(tmp, "selector.mjs")).href);
}

let React, server, selector;
before(async () => {
    mkdirSync(tmp, { recursive: true });
    [React, server, selector] = await Promise.all([
        import("react"), import("react-dom/server"),
        bundle("components/vinto/line-selector.tsx"),
    ]);
});
after(() => rmSync(tmp, { recursive: true, force: true }));

const a = JSON.parse(readFileSync(new URL("./fixtures/activate-all/applied.json", import.meta.url), "utf8")).body.activated;
const assigned = a.slice(0, 2);
const machine = (code, order) => {
    const items = assigned.map(item => ({
        assignment: { ...structuredClone(item),
            machine: { code, name: code }, work_order: { ...item.work_order, number: order } },
        stale: false,
    }));
    const lines = { current_shift: { code: "DIA", name: "Día", operating_date: a[0].operating_date }, items };
    return lines;
};
function render(code, state, verified = true, selectedId = null) {
    const lines = machine(code, "OT-2026-0099");
    return server.renderToStaticMarkup(React.createElement(selector.LineSelector, {
        machine: code, lines, selectedId, onChoose: () => {},
        onRefresh: () => {}, verified,
        execution: state === null ? null : {
            line_execution: true,
            assignments: assigned.map((item, i) => ({ assignment_id: item.id, status: state[i] })),
        },
    }));
}

test("Rebobinado: first started line is the only selectable radio", () => {
    const html = render("BELOIT", ["in_production", "enabled"]);
    assert.match(html, /Líneas habilitadas en BELOIT/);
    assert.match(html, /En producción/);
    assert.match(html, /Habilitada · pendiente de inicio/);
    const radios = [...html.matchAll(/<input[^>]*type="radio"[^>]*>/g)].map(x => x[0]);
    assert.equal(radios.length, 2);
    assert.ok(!radios[0].includes("disabled"), radios[0]);
    assert.ok(radios[1].includes("disabled"), radios[1]);
});

test("Conversión: no initiated line => no radio is selectable", () => {
    const html = render("GAMBINI", ["enabled", "enabled"]);
    const radios = [...html.matchAll(/<input[^>]*type="radio"[^>]*>/g)].map(x => x[0]);
    assert.equal(radios.length, 2);
    assert.ok(radios.every(x => x.includes("disabled")));
});

test("no valid backend reply blocks all sectors' line selectors", () => {
    const html = render("BELOIT", null, false);
    const radios = [...html.matchAll(/<input[^>]*type="radio"[^>]*>/g)].map(x => x[0]);
    assert.ok(radios.every(x => x.includes("disabled")));
    assert.match(html, /Verificando ejecución/);
});

test("UI wiring includes capability gate and safe mutation refresh", () => {
    const sector = readFileSync(new URL("../components/vinto/sector-central.tsx", import.meta.url), "utf8");
    const candidate = readFileSync(new URL("../components/vinto/candidate-form-capture.tsx", import.meta.url), "utf8");
    for (const required of ["getLineExecutionCapability", "executionEnabled={executionEnabled}", "useMachineExecution(",
                            "useOperationSelection(", "selectedContextAllowed(", "<LineSelector", "scope={scope}"])
        assert.ok(sector.includes(required), required);
    assert.match(candidate, /reason === "line_not_producing"/);
});

test("Rebobinado and Conversion programming use the same fail-closed multi-machine capability as Bobinas", () => {
    const sector = readFileSync(new URL("../components/vinto/sector-central.tsx", import.meta.url), "utf8");
    const programming = sector.split("function Programming(")[1]?.split("function Execution(")[0];
    assert.ok(programming, "shared Programming implementation");
    for (const required of [
        "useWorkOrderCapabilities(", "canManageOrders || canManageAssignments",
        "capabilitiesOf(multiMachineResource.view)",
        "creation={creation}", "catalog={catalog}",
        "capabilities={multiMachine.capabilities}", "capabilityStatus={multiMachine.status}",
        "onCapabilitiesStale={multiMachineResource.refresh}",
        "executionEnabled={executionEnabled}",
    ]) assert.ok(programming.includes(required), required);
    assert.match(programming, /const creation = canManageOrders\s*\?/);
    assert.match(programming, /machines: sector\.machines\.map/);
    // The same programming shell is selected by BOTH sector codes.
    assert.match(sector, /REBOBINADO: \{/);
    assert.match(sector, /CONVERSION: \{/);
    assert.match(sector, /module === "programacion"\) return <Programming/);
});
