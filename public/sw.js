/* VINTO OFF-02: public, versioned app-shell assets only. NEVER cache auth/API/user data. */
const STATIC_CACHE = "vinto-off048-quality-static-v4";
const PUBLIC_ASSETS = ["/offline.html", "/offline-probe.js", "/offline-boot.js", "/offline-device-qa.js", "/manifest.webmanifest", "/favicon.svg"];
const PUBLIC_PATHS = new Set(PUBLIC_ASSETS);
// OFF-04.1 laboratory (exists only in lab builds). Never precached here; the lab page caches itself.
const LAB_PATHS = new Set(["/offline-lab.html", "/offline-draft-lab.js", "/offline-sync-lab.html", "/offline-sync-lab.js", "/offline-e2e-lab.html", "/offline-e2e-lab.js"]);
// Operational Quality mobile shell is a PUBLIC, unauthenticated static asset
// only when opt-in build produces it. Never cache /api or personal payloads.
const QUALITY_MOBILE = new Set(["/offline-calidad.html", "/offline-calidad.js"]);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PUBLIC_ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => (name.startsWith("vinto-off02-") || name.startsWith("vinto-off03b-") || name.startsWith("vinto-off03b3-") || name.startsWith("vinto-off03c2-") || name.startsWith("vinto-off03c3-") || name.startsWith("vinto-off03c4-") || name.startsWith("vinto-off048-")) && name !== STATIC_CACHE).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Authentication, operational endpoints, RSC requests and admin always use network.
  if (url.pathname === "/api" || url.pathname.startsWith("/api/") ||
      url.pathname === "/admin" || url.pathname.startsWith("/admin/")) return;

  if (request.mode === "navigate") {
    // A direct navigation to the public fallback must also work offline.
    if (url.pathname === "/offline.html") {
      event.respondWith(caches.match("/offline.html").then((page) => page || fetch(request)));
      return;
    }
    if (url.pathname === "/offline-calidad.html") {
      event.respondWith((async()=>{
        const cache=await caches.open(STATIC_CACHE);
        const cached=await cache.match(url.pathname);
        if(cached)return cached;
        const response=await fetch(request);
        if(response.ok&&response.type==="basic")
          await cache.put(url.pathname,response.clone()).catch(()=>{});
        return response;
      })());
      return;
    }
    if (url.pathname === "/offline-lab.html" || url.pathname === "/offline-sync-lab.html" || url.pathname === "/offline-e2e-lab.html") {
      event.respondWith(caches.match(url.pathname).then((page) => page || fetch(request)));
      return;
    }
    // Do not cache the authenticated app's root HTML or its server components.
    // An offline navigation to the root gets a separate PUBLIC, non-operational shell.
    if (url.pathname !== "/") return;
    event.respondWith(fetch(request).catch(async () => {
      const page = await caches.match("/offline.html");
      return page || Response.error();
    }));
    return;
  }

  if (QUALITY_MOBILE.has(url.pathname)) {
    event.respondWith((async()=>{
      const cache=await caches.open(STATIC_CACHE);
      const cached=await cache.match(url.pathname);
      if(cached)return cached;
      const response=await fetch(request);
      if(response.ok&&response.type==="basic")
        await cache.put(url.pathname,response.clone()).catch(()=>{});
      return response;
    })());
    return;
  }
  if (PUBLIC_PATHS.has(url.pathname) || LAB_PATHS.has(url.pathname)) {
    event.respondWith(caches.match(url.pathname).then((cached) => cached || fetch(request)));
    return;
  }

  // Next.js immutable static chunks only; never cache application JSON or server payloads.
  if (url.pathname.startsWith("/_next/static/") && !url.search) {
    event.respondWith((async () => {
      const cache = await caches.open(STATIC_CACHE);
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === "basic") {
        event.waitUntil(cache.put(request, response.clone()).catch(() => {}));
      }
      return response;
    })());
  }
});
