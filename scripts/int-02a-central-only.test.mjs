// node --test scripts/int-02a-central-only.test.mjs
// INT-02A · la interfaz operativa es EXCLUSIVAMENTE central. Pruebas de COMPORTAMIENTO: se empaqueta con Vite y se RENDERIZA (react-dom/server) la pantalla real app/page.tsx y los shells centrales de Rebobinado y
// Conversión, sustituyendo solo los hooks de sesión y de recursos (scripts/int-02a-stubs) para fijar cada escenario (cargando, error, 401/403, publicado o no por el backend, otra cuenta). Un localStorage
// ESPÍA con datos legacy precargados comprueba que la interfaz no lee, escribe, borra ni muestra esos bytes. Los hooks/efectos no corren en el render del servidor: la lógica de claves y de guardas de sesión
// (INT-01) se prueba en int-01-*.test.mjs; aquí se verifica además que cada clave pedida por la pantalla lleva la sesión. Sin red, sin PostgreSQL, sin navegador.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-int02a-test-${process.pid}`);
const OVERRIDES = {
  "@/lib/vinto/use-session": `${root}/scripts/int-02a-stubs/use-session.ts`,
  "@/lib/vinto/use-central": `${root}/scripts/int-02a-stubs/use-central.ts`,
};
const aliasPlugin = {
  name: "at-alias", enforce: "pre",
  resolveId(source) {
    if (OVERRIDES[source]) return OVERRIDES[source];
    if (!source.startsWith("@/")) return null;
    const base = `${root}/${source.slice(2)}`;
    for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (existsSync(candidate)) return candidate;
    return null;
  },
};
async function bundle(entry, name) {
  const output = await build({
    configFile: false, root, logLevel: "error", mode: "production", plugins: [aliasPlugin], oxc: { jsx: { runtime: "automatic" } },
    build: { write: false, ssr: join(root, entry), minify: false, target: "node22", rollupOptions: { output: { format: "es" } } },
  });
  const chunk = (Array.isArray(output) ? output[0] : output).output.find((item) => item.type === "chunk");
  const file = join(workDir, `${name}.mjs`);
  writeFileSync(file, chunk.code);
  return import(pathToFileURL(file).href);
}

let Page, Rebobinado, Conversion, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [Page, Rebobinado, Conversion] = await Promise.all([bundle("app/page.tsx", "page"), bundle("components/vinto/rebobinado-central.tsx", "rebobinado"), bundle("components/vinto/conversion-central.tsx", "conversion")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

// ---- escenario ------------------------------------------------------------------------------------------------------------------------------------------------
const ID_A = "11111111-1111-4111-8111-111111111111", ID_B = "22222222-2222-4222-8222-222222222222";
const PERMISSIONS = {
  operacion: ["production.capture", "assignment.read", "work_order.read"],
  calidad: ["quality.capture"],
  jefatura: ["work_order.read", "work_order.manage", "assignment.read"],
};
const userOf = (profile, id = ID_A, name = "Usuario A") => ({ id, username: `u.${id.slice(0, 4)}`, display_name: name, profiles: [profile.toUpperCase()], permissions: PERMISSIONS[profile], must_change: false });
const ready = (data) => ({ status: "ready", data, refreshing: false });
const failed = (kind) => ({ status: "error", kind, refreshing: false });
const LOADING = { status: "loading" };
const form = (code, name = code) => ({ code, name, version_number: 1 });
const availability = (sectors) => ({ sectors });
const sector = (code, machines) => ({ code, name: code, machines: machines.map(([c, forms]) => ({ code: c, name: c, forms })) });
const BOBINAS_REAL = availability([sector("BOBINAS", [["MP1", [form("VINTO-P1-06", "Registro de control de fardos")]], ["MP3", [form("VINTO-P1-06", "Registro de control de fardos")]]])]);
const inboxItem = (machine = "MP1") => ({
  bobbin: { id: "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", code: "12", machine: { code: machine, name: machine }, management_start_year: 2026, sequence_number: 12, start_time: "07:00:00", end_time: "08:00:00", diameter_mm: "1200", weight_kg: "800", grammage_g_m2: "20", number_of_cuts: "1", notes: null },
  production: { capture_id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", captured_at: "2026-10-06T16:00:00Z", operating_date: "2026-10-06", shift: { code: "DIA", name: "Día" }, work_order: { id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", number: "OT-1" },
    line: { id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "Artículo 1" } } },
  quality: { status: "pending" },
});

function run(Component, props, { user, resources = {}, online = true, storage } = {}) {
  const state = { session: user ? { status: "authenticated", user } : { status: "anonymous" }, hooks: [], resource: (key, enabled) => {
    for (const [prefix, view] of Object.entries(resources)) if (key.startsWith(prefix)) return typeof view === "function" ? view(key, enabled) : view;
    return enabled ? LOADING : { status: "idle" };
  } };
  globalThis.__INT02A = state;
  const previous = { navigator: Object.getOwnPropertyDescriptor(globalThis, "navigator"), storage: Object.getOwnPropertyDescriptor(globalThis, "localStorage") };
  Object.defineProperty(globalThis, "navigator", { value: { onLine: online }, configurable: true, writable: true });
  if (storage) Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true, writable: true });
  try { return { html: server.renderToStaticMarkup(React.createElement(Component, props)), hooks: state.hooks }; }
  finally {
    if (previous.navigator) Object.defineProperty(globalThis, "navigator", previous.navigator); else delete globalThis.navigator;
    if (storage) { if (previous.storage) Object.defineProperty(globalThis, "localStorage", previous.storage); else delete globalThis.localStorage; }
  }
}

// localStorage ESPÍA con bytes legacy precargados: registra TODA llamada y expone los bytes para compararlos.
const LEGACY = { "vinto-ot": JSON.stringify([{ id: "OT-PRUEBA-LEGACY-A", sector: "Bobinas", machine: "MP1", status: "Publicada", baseline: 1, lines: [] }]), "vinto-asg": JSON.stringify([{ id: "ASG-LEGACY-A", ot: "OT-PRUEBA-LEGACY-A" }]),
  "vinto-p1-records": JSON.stringify([{ id: "REG-LEGACY-DE-A", formName: "Registro legacy de la cuenta A", machine: "MP1", values: { orden_trabajo: "OT-PRUEBA-LEGACY-A" } }]) };
function spyStorage() {
  const data = { ...LEGACY }, calls = [];
  const storage = { getItem: (k) => { calls.push(["getItem", k]); return data[k] ?? null; }, setItem: (k, v) => { calls.push(["setItem", k]); data[k] = String(v); }, removeItem: (k) => { calls.push(["removeItem", k]); delete data[k]; },
    clear: () => { calls.push(["clear"]); for (const k of Object.keys(data)) delete data[k]; }, key: (i) => { calls.push(["key", i]); return Object.keys(data)[i] ?? null; }, get length() { calls.push(["length"]); return Object.keys(data).length; } };
  return { storage, calls, data };
}
const LEGACY_MARKERS = ["REG-LEGACY-DE-A", "Registro legacy de la cuenta A", "OT-PRUEBA-LEGACY-A", "ASG-LEGACY-A"];
const LEGACY_CARD_TEXT = ["Contexto OT–PV–producto heredado", "Enviar registro trazable", "Buscar formato", "Registros locales", "Descargas de registros locales", "Guardado local", "Registro guardado con vínculo OT–PV–producto"];
const legacyCardIds = (html) => [...html.matchAll(/data-form="(form_[^"]+)"/g)].map((m) => m[1]);

// ---- Bobinas ----------------------------------------------------------------------------------------------------------------------------------------------------

test("Bobinas · Ejecución solo ofrece los formularios CENTRALES F3 y P1-06 y ninguna tarjeta local; sin publicación central no hay fichas candidatas", () => {
  const { html } = run(Page.default, {}, { user: userOf("operacion"), resources: { "availability:": ready(BOBINAS_REAL) } });
  assert.deepEqual(legacyCardIds(html).sort(), ["form_3_registro_de_produccion_de_bobinas", "form_6_registro_de_control_de_fardos"]);
  for (const text of LEGACY_CARD_TEXT) assert.equal(html.includes(text), false, text);
  for (const legacy of ["Operación e inspección de máquina", "Parámetros de operación", "Registro de tubetes", "Consumo de químicos", "Registro de consumo de fibra"]) assert.equal(html.includes(legacy), false, `${legacy}: no hay tarjeta legacy ni candidata sin publicación`);
  assert.match(html, /Captura central \(PostgreSQL\) con la asignación activa/);
  assert.equal(html.includes('data-section="candidate-forms"'), false);
});

test("Bobinas · una ficha candidata aparece solo si el backend la publica para la máquina; sin disponibilidad (cargando, error, 401, 403) no se ofrece ni se sustituye por nada local", () => {
  const published = availability([sector("BOBINAS", [["MP1", [form("VINTO-P1-06"), form("VINTO-P1-05")]], ["MP3", [form("VINTO-P1-06")]]])]);
  const withCandidate = run(Page.default, {}, { user: userOf("operacion"), resources: { "availability:": ready(published) } }).html;
  assert.match(withCandidate, /data-form="VINTO-P1-05"/);
  for (const [name, view] of [["cargando", LOADING], ["no disponible", failed("unavailable")], ["sesión (401)", failed("session")], ["sin permiso (403)", failed("forbidden")]]) {
    const { html } = run(Page.default, {}, { user: userOf("operacion"), resources: { "availability:": view } });
    assert.equal(html.includes('data-form="VINTO-P1-05"'), false, `${name}: no se ofrece la ficha`);
    assert.equal(html.includes('data-section="candidate-forms"'), false, name);
    assert.deepEqual(legacyCardIds(html).sort(), ["form_3_registro_de_produccion_de_bobinas", "form_6_registro_de_control_de_fardos"], `${name}: solo los centrales, nunca un sustituto local`);
    for (const text of LEGACY_CARD_TEXT) assert.equal(html.includes(text), false, `${name}: ${text}`);
  }
});

test("Bobinas · sin asignación activa o con error de la API el contexto se informa como tal: ningún contexto local ni OT demo de respaldo", () => {
  for (const [name, view] of [["cargando", LOADING], ["error de red", failed("unavailable")], ["403", failed("forbidden")], ["sesión", failed("session")]]) {
    const { html } = run(Page.default, {}, { user: userOf("operacion"), resources: { "availability:": ready(BOBINAS_REAL), "active:": view } });
    assert.match(html, name === "cargando" ? /Consultando la asignación activa de MP1/ : /No se pudo consultar la asignación activa/, name);
    for (const marker of ["OT-PRUEBA", "OT-2026", "BOBINA-FICTICIA", ...LEGACY_MARKERS]) assert.equal(html.includes(marker), false, `${name}: ${marker}`);
  }
});

test("Bobinas · sin conexión se informa que no se puede registrar y que no se guarda nada en el navegador", () => {
  const offline = run(Page.default, {}, { user: userOf("operacion"), online: false, resources: { "availability:": ready(BOBINAS_REAL) } }).html;
  assert.match(offline, /data-section="offline"/);
  assert.match(offline, /Sin conexión: no es posible registrar capturas\. Nada se guarda en este navegador/);
  const online = run(Page.default, {}, { user: userOf("operacion"), online: true, resources: { "availability:": ready(BOBINAS_REAL) } }).html;
  assert.equal(online.includes('data-section="offline"'), false);
});

test("Bobinas · Programación (Jefatura) es la programación CENTRAL: lee las OT del backend por clave de sesión y no muestra OT ni asignaciones locales", () => {
  const { html, hooks } = run(Page.default, {}, { user: userOf("jefatura"), resources: { "work-orders:": ready([]) } });
  assert.ok(hooks.some((h) => h.key === `work-orders:user:${ID_A}` && h.enabled), "las OT salen de la API central (clave con sesión, habilitada)");
  for (const marker of ["OT-PRUEBA", "OT-2026-001", ...LEGACY_MARKERS]) assert.equal(html.includes(marker), false, marker);
  assert.deepEqual(legacyCardIds(html), []);
});

// ---- Calidad ----------------------------------------------------------------------------------------------------------------------------------------------------

test("Calidad · Ejecución muestra el inbox central y ninguna tarjeta legacy editable; el inbox con error, 403 o cargando no genera sustitutos locales", () => {
  const ok = run(Page.default, {}, { user: userOf("calidad"), resources: { "quality-bobbin-inbox:": ready([inboxItem()]), "quality-bobbin-forms:": ready(availability([])), "quality-machine-forms:": LOADING } }).html;
  assert.match(ok, /Bobinas pendientes de Calidad/);
  assert.match(ok, /Registrar humedad/);
  assert.match(ok, /Registrar propiedades/);
  assert.deepEqual(legacyCardIds(ok), [], "ninguna tarjeta de formulario legacy en Calidad");
  for (const text of LEGACY_CARD_TEXT) assert.equal(ok.includes(text), false, text);
  for (const [name, view] of [["cargando", LOADING], ["error", failed("unavailable")], ["403", failed("forbidden")], ["401", failed("session")]]) {
    const { html } = run(Page.default, {}, { user: userOf("calidad"), resources: { "quality-bobbin-inbox:": view } });
    assert.deepEqual(legacyCardIds(html), [], name);
    for (const text of LEGACY_CARD_TEXT) assert.equal(html.includes(text), false, `${name}: ${text}`);
    for (const marker of LEGACY_MARKERS) assert.equal(html.includes(marker), false, `${name}: ${marker}`);
  }
});

test("Calidad · los candidatos por bobina se ofrecen solo si el backend los publica; P1-28 se presenta como ficha documental, sin acciones de rechazar / liberar", () => {
  const published = availability([sector("BOBINAS", [["MP1", [form("VINTO-P1-21"), form("VINTO-P1-28")]], ["MP3", []]])]);
  const { html } = run(Page.default, {}, { user: userOf("calidad"), resources: { "quality-bobbin-inbox:": ready([inboxItem("MP1"), inboxItem("MP3")]), "quality-bobbin-forms:": ready(published) } });
  assert.match(html, /Registrar ficha documental P1-28 \(candidato\)/);
  assert.match(html, /Perfil de gramaje y humedad \(candidato\)/);
  assert.equal((html.match(/Registrar ficha documental P1-28 \(candidato\)/g) ?? []).length, 2, "solo la fila de la máquina publicada (aria-label + texto), no la de MP3");
  for (const text of ["Rechazar bobina", "Aprobar rechazo", "Confirmar disposición", "Liberar bobina", "Bloquear bobina"]) assert.equal(html.includes(text), false, text);
  const none = run(Page.default, {}, { user: userOf("calidad"), resources: { "quality-bobbin-inbox:": ready([inboxItem("MP1")]), "quality-bobbin-forms:": failed("unavailable") } }).html;
  assert.equal(none.includes("ficha documental P1-28"), false);
  assert.equal(none.includes("Perfil de gramaje"), false);
});

// ---- Rebobinado y Conversión ------------------------------------------------------------------------------------------------------------------------------------

const SHELL = { canManageOrders: false, canManageAssignments: false, canCapture: true, canReadOrders: true, canReadAssignments: true, refreshKey: 0, scope: `user:${ID_A}`, onOpenForm: () => undefined, onSessionLost: () => undefined };
const SHELLS = () => [["Rebobinado", Rebobinado.RebobinadoCentral, /Rebobinado no está habilitado/], ["Conversión", Conversion.ConversionCentral, /Conversión no está habilitado/]];

test("Rebobinado y Conversión · si el backend no habilita el sector se informa «no está habilitado» y NO hay formulario, OT ni asignación locales de sustitución", () => {
  for (const [name, Shell, message] of SHELLS()) for (const moduleName of ["programacion", "ejecucion", "seguimiento"]) {
    const { html } = run(Shell, { ...SHELL, module: moduleName }, { user: userOf("operacion"), resources: { "availability:": ready(BOBINAS_REAL) } });
    assert.match(html, message, `${name}/${moduleName}`);
    assert.match(html, /no se registran capturas centrales ni se usan datos de demostración/i, `${name}/${moduleName}`);
    assert.equal(/Abrir captura central|Ficha candidata|data-form=/.test(html), false, `${name}/${moduleName}: ningún formulario`);
    for (const marker of [...LEGACY_MARKERS, "OT-PRUEBA", ...LEGACY_CARD_TEXT]) assert.equal(html.includes(marker), false, `${name}/${moduleName}: ${marker}`);
  }
});

test("Rebobinado y Conversión · carga, error, 401 y 403 de la disponibilidad no generan datos locales ni formularios; con el sector publicado solo salen los formularios del backend con pantalla", () => {
  for (const [name, Shell] of SHELLS()) {
    for (const [state, view] of [["cargando", LOADING], ["error", failed("unavailable")], ["403", failed("forbidden")], ["401", failed("session")]]) {
      const { html } = run(Shell, { ...SHELL, module: "ejecucion" }, { user: userOf("operacion"), resources: { "availability:": view } });
      assert.equal(/Abrir captura central|Ficha candidata|data-form=/.test(html), false, `${name}/${state}`);
      for (const marker of [...LEGACY_MARKERS, "OT-PRUEBA"]) assert.equal(html.includes(marker), false, `${name}/${state}: ${marker}`);
    }
  }
  const published = availability([sector("REBOBINADO", [["COPASA", [form("VINTO-P1-10", "Registro de fardos"), form("VINTO-P1-99", "Formulario sin pantalla")]]])]);
  const { html } = run(Rebobinado.RebobinadoCentral, { ...SHELL, module: "ejecucion" }, { user: userOf("operacion"), resources: { "availability:": ready(published), "active:": failed("unavailable") } });
  assert.match(html, /data-form="VINTO-P1-10"/);
  assert.match(html, /data-form="VINTO-P1-99"[^>]*disabled/); // sin pantalla central: no se abre
  assert.match(html, /Sin pantalla central/);
});

// ---- datos legacy y cuentas -------------------------------------------------------------------------------------------------------------------------------------

test("los datos legacy del navegador permanecen intactos: renderizar cualquier pantalla NO lee, escribe, borra ni muestra vinto-ot / vinto-asg / vinto-p1-records", () => {
  const { storage, calls, data } = spyStorage();
  const before = JSON.stringify(data);
  const scenes = [
    [Page.default, {}, { user: userOf("operacion"), resources: { "availability:": ready(BOBINAS_REAL) } }],
    [Page.default, {}, { user: userOf("operacion"), online: false, resources: { "availability:": failed("forbidden"), "active:": failed("unavailable") } }],
    [Page.default, {}, { user: userOf("calidad"), resources: { "quality-bobbin-inbox:": ready([inboxItem()]) } }],
    [Page.default, {}, { user: userOf("jefatura"), resources: { "work-orders:": ready([]) } }],
    [Page.default, {}, { user: null }],
    ...SHELLS().flatMap(([, Shell]) => ["programacion", "ejecucion", "seguimiento"].map((moduleName) => [Shell, { ...SHELL, module: moduleName }, { user: userOf("operacion"), resources: { "availability:": ready(BOBINAS_REAL) } }])),
  ];
  for (const [Component, props, options] of scenes) {
    const { html } = run(Component, props, { ...options, storage });
    for (const marker of LEGACY_MARKERS) assert.equal(html.includes(marker), false, marker);
  }
  assert.deepEqual(calls, [], "la interfaz no toca localStorage (ni lectura ni escritura)");
  assert.equal(JSON.stringify(data), before, "los bytes históricos no cambian");
  assert.deepEqual(Object.keys(data).sort(), ["vinto-asg", "vinto-ot", "vinto-p1-records"]);
});

test("una cuenta B en el mismo navegador no ve los registros locales de A ni su estado: no existe un visor de datos legacy", () => {
  const { storage, calls } = spyStorage(); // el navegador conserva los bytes de A
  for (const [profile, expectedFront] of [["operacion", "Bobinas"], ["calidad", "Calidad"]]) {
    const b = userOf(profile, ID_B, "Usuario B");
    const { html, hooks } = run(Page.default, {}, { user: b, resources: { "availability:": ready(BOBINAS_REAL), "quality-bobbin-inbox:": ready([inboxItem()]) }, storage });
    assert.match(html, new RegExp(`${expectedFront} · Ejecucion`)); // (el encabezado de la pantalla escribe el módulo sin tilde)
    for (const marker of LEGACY_MARKERS) assert.equal(html.includes(marker), false, marker);
    assert.ok(html.includes("Usuario B") && !html.includes("Usuario A"), "la pantalla es la de B");
    assert.ok(hooks.length > 0 && hooks.every((h) => h.key.includes(`user:${ID_B}`) || /quality-(bobbin|machine)-forms:user:/.test(h.key) ), "cada recurso pedido por la pantalla lleva la identidad de B");
    assert.ok(hooks.every((h) => !h.key.includes(ID_A)), "ninguna clave contiene la identidad de A");
  }
  assert.deepEqual(calls, []);
});

test("INT-01 sigue vigente en la pantalla renderizada: TODAS las claves de recursos que pide Home llevan la sesión (ninguna constante)", () => {
  for (const profile of ["operacion", "calidad", "jefatura"]) {
    const { hooks } = run(Page.default, {}, { user: userOf(profile), resources: {} });
    assert.ok(hooks.length >= 8, `${profile}: ${hooks.length} recursos`);
    for (const { key } of hooks) assert.ok(key.includes(`user:${ID_A}`), `${profile}: clave sin sesión → ${key}`);
  }
  for (const [name, Shell] of SHELLS()) for (const moduleName of ["programacion", "ejecucion", "seguimiento"]) {
    const { hooks } = run(Shell, { ...SHELL, module: moduleName }, { user: userOf("operacion"), resources: { "availability:": ready(availability([sector(name === "Conversión" ? "CONVERSION" : "REBOBINADO", [["M1", []]])])) } });
    for (const { key } of hooks) assert.ok(key.includes(`user:${ID_A}`), `${name}/${moduleName}: ${key}`);
  }
});

test("sin sesión o sin perfil operativo no se abre ninguna pantalla operativa ni se lee almacenamiento local", () => {
  const { storage, calls } = spyStorage();
  const anonymous = run(Page.default, {}, { user: null, storage }).html;
  assert.equal(/Bobinas ·|Calidad ·|data-form=/.test(anonymous), false);
  const noRole = run(Page.default, {}, { user: { ...userOf("operacion"), profiles: ["DATA_BALTREK"], permissions: [] }, storage }).html;
  assert.equal(/data-form=|Captura central/.test(noRole), false);
  assert.deepEqual(calls, []);
});
