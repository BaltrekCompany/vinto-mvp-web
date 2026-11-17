/* OFF-02: synthetic canary only. Not a production capture or identity store. */
(() => {
  "use strict";
  const target = document.getElementById("offline-probe-status");
  const retry = document.getElementById("retry");
  if (retry) retry.addEventListener("click", () => window.location.assign("/"));
  if (!target) return;
  if (!("indexedDB" in window)) {
    target.textContent = "IndexedDB no está disponible en este navegador.";
    return;
  }
  try {
    const request = indexedDB.open("vinto-off02-probe", 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("canary")) request.result.createObjectStore("canary");
    };
    request.onerror = () => { target.textContent = "No se pudo abrir el almacenamiento. No captures información real."; };
    request.onblocked = () => { target.textContent = "El almacenamiento está bloqueado por otra pestaña."; };
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction("canary", "readwrite");
      const store = tx.objectStore("canary");
      const read = store.get("probe");
      let existed = false;
      read.onsuccess = () => {
        existed = read.result === "OFF02";
        store.put("OFF02", "probe");
      };
      tx.oncomplete = () => {
        target.textContent = existed
          ? "Persistencia técnica verificada: la marca de prueba sobrevivió a la reapertura."
          : "Marca técnica almacenada. Cierra y reabre el navegador sin conexión para comprobar persistencia.";
        db.close();
      };
      tx.onerror = () => { target.textContent = "No se pudo guardar la marca técnica."; db.close(); };
      tx.onabort = () => { target.textContent = "La prueba de almacenamiento fue cancelada."; db.close(); };
    };
  } catch {
    target.textContent = "El almacenamiento local no está disponible.";
  }
})();
