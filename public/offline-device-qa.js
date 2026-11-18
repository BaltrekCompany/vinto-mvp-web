/* VINTO OFF-03C.3: purely local read-only mobile readiness diagnostics.
 * Never prints identities, browser keys, grants, form names, ciphertext, cookies,
 * secrets, production data or any network request.
 */
(() => {
  "use strict";
  const DB = "vinto-off03a-profiles-v1";
  const VERSION = 3;
  const STATIC_CACHE = "vinto-off03c4-static-v1";
  const ASSETS = ["/offline.html", "/offline-probe.js", "/offline-boot.js",
                  "/offline-device-qa.js", "/manifest.webmanifest", "/favicon.svg"];
  const NAMES = ["profiles", "scopes", "quality_packages"];
  const button = document.getElementById("offline-qa-run");
  const result = document.getElementById("offline-qa-result");
  const list = document.getElementById("offline-qa-checks");
  if (!button || !result || !list) return;

  const checks = [];
  function add(label, status, detail) {
    checks.push({label, status, detail});
  }
  function render() {
    list.replaceChildren();
    for (const check of checks) {
      const li = document.createElement("li");
      li.textContent = (check.status === "pass" ? "OK" :
                        check.status === "warn" ? "REVISAR" : "BLOQUEADO") +
                       " · " + check.label + ": " + check.detail;
      list.appendChild(li);
    }
    const bad = checks.some(c => c.status === "block");
    const warn = checks.some(c => c.status === "warn");
    const label = bad ? "NO APTO" : warn ? "PENDIENTE DE REVISIÓN" : "PREPARACIÓN TÉCNICA OK";
    result.textContent = label + ". Este diagnóstico local NO prueba el reinicio físico," +
      " permisos actuales, conectividad real ni autorización para capturar.";
    result.dataset.status = bad ? "block" : warn ? "warn" : "pass";
    list.hidden = false;
  }
  function checkStores() {
    return new Promise((resolve, reject) => {
      // Opening is permitted only after enumeration confirmed the DB exists.
      // Never create a new DB or upgrade on behalf of an anonymous tester.
      const request = indexedDB.open(DB);
      request.onupgradeneeded = () => { request.transaction.abort(); };
      request.onerror = () => reject(new Error("db-unavailable"));
      request.onblocked = () => reject(new Error("db-blocked"));
      request.onsuccess = () => {
        const db = request.result;
        if (db.version !== VERSION || !NAMES.every(n => db.objectStoreNames.contains(n))) {
          db.close(); reject(new Error("db-schema")); return;
        }
        const tx = db.transaction(NAMES, "readonly");
        const counts = [];
        for (const name of NAMES) {
          const req = tx.objectStore(name).count();
          req.onsuccess = () => { counts[NAMES.indexOf(name)] = req.result; };
        }
        tx.oncomplete = () => { db.close(); resolve(counts); };
        tx.onerror = () => { db.close(); reject(new Error("db-read")); };
        tx.onabort = () => { db.close(); reject(new Error("db-abort")); };
      };
    });
  }
  async function run() {
    button.disabled = true;
    result.textContent = "Comprobando componentes locales en modo de solo lectura…";
    list.hidden = true;
    list.replaceChildren();
    checks.length = 0;
    try {
      add("Origen seguro", window.isSecureContext ? "pass" : "block",
          window.isSecureContext ? "Contexto seguro disponible" : "Se requiere HTTPS de ensayo");
      const controlled = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
      add("Service Worker", controlled ? "pass" : "block",
          controlled ? "Página bajo control offline" : "Sin controlador activo");
      if (!("caches" in window)) {
        add("Caché pública de app", "block", "CacheStorage no disponible");
      } else {
        try {
          const names = await caches.keys();
          if (!names.includes(STATIC_CACHE)) {
            add("Caché pública de app", "block", "Versión offline vigente no encontrada");
          } else {
            const outcomes = await Promise.all(ASSETS.map(path =>
              caches.match(path, {cacheName: STATIC_CACHE}).then(Boolean)));
            add("Recursos de apertura", outcomes.every(Boolean) ? "pass" : "block",
                outcomes.every(Boolean) ? "Shell público y verificador disponibles" :
                "Faltan recursos precargados; preparar online otra vez");
          }
        } catch {
          add("Caché pública de app", "block", "No se puede consultar el caché local");
        }
      }
      if (!("indexedDB" in window)) {
        add("IndexedDB", "block", "No disponible en este navegador");
      } else if (typeof indexedDB.databases !== "function") {
        add("IndexedDB", "warn", "Este navegador no permite inventariar bases sin abrirlas");
      } else {
        try {
          const dbs = await indexedDB.databases();
          const record = dbs.find(d => d.name === DB);
          if (!record) {
            add("Perfil cifrado", "block", "No existe preparación local");
          } else if (record.version !== VERSION) {
            add("Esquema local", "block", "Versión incompatible: requiere entrar online");
          } else {
            const counts = await checkStores();
            add("Perfil único por navegador", counts[0] === 1 ? "pass" : "block",
                counts[0] === 1 ? "Existe un perfil técnico local" : "No hay un perfil único");
            add("Alcance firmado almacenado", counts[1] === 1 ? "pass" : "block",
                counts[1] === 1 ? "Registro cifrado presente" : "Falta el registro de alcance");
            add("Paquete de Calidad almacenado", counts[2] >= 1 ? "pass" : "block",
                counts[2] >= 1 ? "Existe al menos una definición cifrada" :
                "Prepare el formulario online antes del ensayo");
          }
        } catch {
          add("Almacenamiento local", "block", "No se puede validar la estructura");
        }
      }
      if (navigator.storage && typeof navigator.storage.persisted === "function") {
        try {
          const persisted = await navigator.storage.persisted();
          add("Protección ante descarte de datos", persisted ? "pass" : "warn",
              persisted ? "Persistencia solicitada/concedida por el navegador" :
              "Persistencia no garantizada: el ensayo de reinicio es obligatorio");
        } catch {
          add("Protección ante descarte de datos", "warn", "Estado no verificable");
        }
      } else {
        add("Protección ante descarte de datos", "warn", "API no disponible");
      }
      add("Permisos industriales", "warn",
          "No comprobados sin Internet; consultar solo la definición firmada");
      render();
    } catch {
      add("Diagnóstico técnico", "block", "Falló la revisión local");
      render();
    } finally {
      button.disabled = false;
    }
  }
  button.addEventListener("click", run);
})();
