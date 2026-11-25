/* VINTO Quality offline shell (NOT a separate UI).
 * Cache only the generic root document and hashed Next static assets.
 * Never cache API responses, session data, form values or offline vault records.
 */
const CACHE="vinto-quality-offline-shell-v1";
const PREFIX="vinto-quality-offline-shell-";
const allowed = (request) => {
 const u=new URL(request.url);
 return u.origin===self.location.origin &&
   (u.pathname.startsWith("/_next/static/") ||
    (u.pathname==="/" && request.mode==="navigate"));
};
self.addEventListener("install",event=>event.waitUntil(self.skipWaiting()));
self.addEventListener("activate",event=>event.waitUntil((async()=>{
 const keys=await caches.keys();
 await Promise.all(keys.filter(k=>k.startsWith(PREFIX)&&k!==CACHE).map(k=>caches.delete(k)));
 await self.clients.claim();
})()));
self.addEventListener("fetch",event=>{
 const request=event.request;
 if(request.method!=="GET"||!allowed(request))return;
 if(new URL(request.url).pathname.startsWith("/_next/static/")){
  event.respondWith((async()=>{
   const cache=await caches.open(CACHE);
   const found=await cache.match(request);
   if(found)return found;
   const result=await fetch(request);
   if(result.ok&&result.type==="basic")await cache.put(request,result.clone());
   return result;
  })());
  return;
 }
 event.respondWith((async()=>{
  const cache=await caches.open(CACHE);
  try{
   const result=await fetch(request);
   if(result.ok&&result.type==="basic")await cache.put(request,result.clone());
   return result;
  }catch(error){
   const saved=await cache.match(request,{ignoreSearch:true});
   if(saved)return saved;
   throw error;
  }
 })());
});
self.addEventListener("message",event=>{
 const data=event.data;
 if(!data||data.type!=="CACHE_QUALITY_SHELL"||!Array.isArray(data.assets))return;
 event.waitUntil((async()=>{
  const cache=await caches.open(CACHE);
  // No client-specified arbitrary URLs may be cached.
  const assets=data.assets.slice(0,120).filter(url=>{
   if(typeof url!=="string")return false;
   try{
    const u=new URL(url,self.location.origin);
    return u.origin===self.location.origin&&u.pathname.startsWith("/_next/static/");
   }catch{return false;}
  });
  await Promise.all(assets.map(async url=>{
   try{
    const request=new Request(url,{credentials:"omit",cache:"reload"});
    const result=await fetch(request);
    if(result.ok&&result.type==="basic")await cache.put(request,result);
   }catch{/* Individual missing chunks never create a false readiness claim. */}
  }));
  try{
   const req=new Request("/",{credentials:"omit",cache:"reload"});
   const result=await fetch(req);
   if(result.ok&&result.type==="basic")await cache.put("/",result);
  }catch{/* During network loss, previously cached root is preserved. */}
 })());
});
