// Browser checks for the actual RBE React components, against a synthetic HTTP contract.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { createServer } from "vite";
import { chromium } from "playwright";

const root = resolve(import.meta.dirname, "..");
const tmp = join(root, ".tmp-rbe05-" + process.pid);
const id = "11111111-1111-4111-8111-111111111111";
const article = "33333333-3333-4333-8333-333333333333";
const child = "55555555-5555-4555-8555-555555555555";
const date = "2026-11-28T20:10:00Z";
const pdf = "%PDF-1.4\n% fixture transport\n%%EOF";
const item = {
  id, status: "generated", pv_reference: "PV-ENSAYO", article_code_snapshot: "ART-1",
  machine_code: "COPASA", truck_number: "CAM-1", order_number: "ORD-1", generated_at: date,
};
const mother = {
  mother_capture_id: id, mother_bobbin_id: null, mother_label: "MADRE-1", pv_reference: item.pv_reference,
  article_id: article, article_code: item.article_code_snapshot, article_description: "Ensayo",
  machine: { code: "COPASA", name: "Copasa" }, work_order: { id, number: "OT-1" }, operating_date: "2026-11-28",
  destination: "Perú", formato_1: "120", formato_2: null, formato_3: "0",
  diametro: "1.20", tubete: "Ensayo", ayudante: null, operator: { user_id: id, display_name: "Ensayo" },
};
const draft = {
  ...item, status: "draft", created_at: date, observations: "",
  article: { id: article, code: item.article_code_snapshot, description: "Ensayo" },
  packages: [{
    id, package_number: 1, mother_capture_id: id, mother_label_snapshot: mother.mother_label, mother,
    children: [{ bobbin_id: child, package_slot: "A", position: 1, weight_kg: "12.50" }],
  }],
};
let server, browser, base;
before(async () => {
  mkdirSync(tmp);
  writeFileSync(join(tmp, "index.html"), '<!doctype html><html lang="es"><div id="root"></div><script type="module" src="./entry.tsx"></script></html>');
  writeFileSync(join(tmp, "entry.tsx"), `
    import {useState} from "react";
    import {createRoot} from "react-dom/client";
    import {RewindingExportWorkspace} from "@/components/vinto/rewinding-export-workspace";
    import {RewindingExportHistory} from "@/components/vinto/rewinding-export-history";
    function App() {
      const [lost, setLost] = useState(false);
      const onSessionLost = () => setLost(true);
      const role = new URLSearchParams(location.search).get("role");
      if (lost) return <p>Sesión vencida</p>;
      if (role === "lead" || role === "super") return <RewindingExportHistory scope={role}
          canAnnul={role === "lead"} onSessionLost={onSessionLost}/>;
      return <RewindingExportWorkspace scope={role ?? "operator"} canCreate={role !== "quality"}
        canReadOwn={role !== "quality"} onSessionLost={onSessionLost}/>;
    }
    createRoot(document.getElementById("root")!).render(<App/>);
  `);
  server = await createServer({
    root, configFile: false, logLevel: "error", server: { host: "127.0.0.1", port: 0 },
    resolve: { alias: { "@": root } },
    define: { "process.env.NEXT_PUBLIC_API_URL": "globalThis.location.origin" },
    oxc: { jsx: { runtime: "automatic" } },
  });
  await server.listen();
  base = `http://127.0.0.1:${server.httpServer.address().port}/${tmp.slice(root.length + 1)}/`;
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  await server?.close();
  rmSync(tmp, { recursive: true, force: true });
});

async function scenario(run, role = "operator") {
  const page = await browser.newPage({ acceptDownloads: true });
  page.setDefaultTimeout(6000);
  try {
    await run(page, base + "?role=" + role);
  } finally {
    await page.close();
  }
}

async function setup(page, { initialStatus = null, generation, previewValid = true } = {}) {
  let status = initialStatus;
  const keys = [];
  const counts = { annex: 0, pvs: 0, history: 0, preview: 0 };
  await page.route("**/api/reports/rewinding-export/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.split("/rewinding-export")[1];
    if (path === "/pvs") {
      counts.pvs++;
      return route.fulfill({ json: { items: status === "generated" ? [] : [{ pv_reference: item.pv_reference, eligible_mothers: 1 }] } });
    }
    if (path === "/products") return route.fulfill({ json: { items: [{ article_id: article, code: "ART-1", description: "Ensayo" }] } });
    if (path === "/mothers") return route.fulfill({ json: { items: [mother] } });
    if (path === "/drafts") return route.fulfill({ json: { items: status ? [] : [{
      id, created_at: date, pv_reference: item.pv_reference, article_code: "ART-1", machine_code: "COPASA", package_count: 1,
    }] } });
    if (path === `/drafts/${id}`) return route.fulfill({ json: { ...draft, ...(request.postDataJSON?.() ?? {}) } });
    if (path.endsWith("/preview")) {
      counts.preview++;
      return route.fulfill({ json: {
        valid: previewValid, package_count: 1, child_count: 1, warnings: [{ code: "SOURCE_TIME_INVERTED", message: "Hora invertida." }],
        blocking_errors: previewValid ? [] : [{ code: "V05", message: "La cría ya no está disponible." }],
      } });
    }
    if (path.endsWith("/generate")) {
      const body = request.postDataJSON();
      assert.deepEqual(Object.keys(body), ["idempotency_key"]);
      keys.push(body.idempotency_key);
      if (generation) return generation(route, keys.length, () => { status = "generated"; });
      status = "generated";
      return route.fulfill({ contentType: "application/pdf", body: pdf });
    }
    if (path === "/history") {
      counts.history++;
      return route.fulfill({ json: status ? [{ ...item, status }] : [] });
    }
    if (path.endsWith("/pdf")) return route.fulfill({ contentType: "application/pdf", body: pdf });
    if (path.endsWith("/annul")) {
      counts.annex++;
      assert.deepEqual(request.postDataJSON(), { reason: "Motivo del ensayo sintético" });
      status = "annulled";
      return route.fulfill({ json: { report_id: id, released_reservations: 1 } });
    }
    if (path === `/reports/${id}`) return route.fulfill({ json: {
      report: { ...item, status, observations: "Observación sintética", destination_snapshot: "Perú",
        annulled_reason: status === "annulled" ? "Motivo del ensayo sintético" : null, report_snapshot: { warnings: [] } },
      packages: [{ package_number: 1, mother_label_snapshot: "MADRE-1", operator_display_name_snapshot: "Ensayo",
        package_slot: "A", source_position: 1, weight_kg_snapshot: "12.50" }],
    } });
    return route.fulfill({ status: 404, json: {} });
  });
  return { keys, counts };
}

async function preview(page, url) {
  await page.goto(url);
  await page.getByRole("button", { name: "Abrir borrador" }).click();
  const generateButton = page.getByRole("button", { name: "Generar PDF", exact: true });
  await generateButton.waitFor();
  assert.equal(await generateButton.isDisabled(), true);
  await page.getByLabel("N.° camión *").fill("CAM-2");
  await page.getByRole("button", { name: "Vista previa", exact: true }).click();
  await page.getByText("Hora invertida.", { exact: true }).waitFor();
  return generateButton;
}

test("confirma una vez, reutiliza la clave tras perder la respuesta y descarga el original del historial", async () => {
  await scenario(async (page, url) => {
    const { keys, counts } = await setup(page, { generation: async (route, attempt, accepted) => {
      accepted();
      if (attempt === 1) return route.abort("failed");
      return route.fulfill({ contentType: "application/pdf", body: pdf });
    } });
    await (await preview(page, url)).click();
    // Invoke twice during the same event loop tick, before React's disabled state is rendered.
    await page.getByRole("button", { name: "Confirmar generación" }).evaluate(button => { button.click(); button.click(); });
    await page.getByRole("button", { name: "Reintentar generación" }).waitFor();
    assert.equal(keys.length, 1);
    await page.getByText("PV-ENSAYO · ART-1 · Generado").waitFor();
    const download = page.waitForEvent("download");
    const availability = page.waitForResponse(response => response.url().endsWith("/rewinding-export/pvs"));
    await page.getByRole("button", { name: "Reintentar generación" }).click();
    assert.equal(readFileSync(await (await download).path(), "utf8"), pdf);
    assert.equal(keys.length, 2);
    assert.equal(keys[0], keys[1]);
    assert.equal((await availability).status(), 200);
    assert.ok(counts.pvs > 1);
    await page.reload();
    await page.getByRole("button", { name: "Descargar PDF original" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Abrir borrador" }).count(), 0);
    const fromHistory = page.waitForEvent("download");
    await page.getByRole("button", { name: "Descargar PDF original" }).click();
    assert.equal(readFileSync(await (await fromHistory).path(), "utf8"), pdf);
  });
});

test("presenta bloqueantes e inhabilita generar", async () => {
  await scenario(async (page, url) => {
    const { keys } = await setup(page, { previewValid: false });
    const generateButton = await preview(page, url);
    await page.getByText("La cría ya no está disponible.", { exact: true }).waitFor();
    assert.equal(await generateButton.isDisabled(), true);
    assert.equal(keys.length, 0);
  });
});

test("recupera la sesión ante HTTP 401 y muestra el conflicto HTTP 409", async () => {
  for (const status of [409, 401]) {
    await scenario(async (page, url) => {
      await setup(page, { generation: route => route.fulfill({ status, json: {} }) });
      await (await preview(page, url)).click();
      await page.getByRole("button", { name: "Confirmar generación" }).click();
      const feedback = status === 401 ? page.getByText("Sesión vencida") : page.getByRole("alert").filter({ hasText: "El estado cambió" });
      await feedback.waitFor();
    });
  }
});

test("Supervisión consulta Observado y Jefatura confirma la anulación con motivo", async () => {
  await scenario(async (page, url) => {
    await setup(page, { initialStatus: "observed" });
    await page.goto(url);
    await page.getByRole("button", { name: "Ver detalle" }).click();
    await page.getByRole("heading", { name: "ORD-1 · Observado" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Anular reporte" }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "Generar PDF" }).count(), 0);
  }, "super");
  await scenario(async (page, url) => {
    const { counts } = await setup(page, { initialStatus: "observed" });
    await page.goto(url);
    await page.getByRole("button", { name: "Ver detalle" }).click();
    await page.getByRole("button", { name: "Anular reporte" }).click();
    const confirm = page.getByRole("button", { name: "Confirmar anulación" });
    assert.equal(await confirm.isDisabled(), true);
    await page.getByLabel("Motivo de anulación (10 a 300 caracteres)").fill("Motivo del ensayo sintético");
    await confirm.click();
    await page.getByRole("heading", { name: "ORD-1 · Anulado" }).waitFor();
    assert.equal(counts.annex, 1);
    assert.ok(counts.history > 1);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Descargar PDF original" }).click();
    assert.equal(readFileSync(await (await download).path(), "utf8"), pdf);
  }, "lead");
  await scenario(async (page, url) => {
    let requests = 0;
    await page.route("**/api/reports/rewinding-export/**", route => { requests++; return route.abort(); });
    await page.goto(url);
    assert.equal(await page.locator("[data-rewinding-export]").count(), 0);
    assert.equal(requests, 0);
  }, "quality");
});
