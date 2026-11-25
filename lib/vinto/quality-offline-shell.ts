/** Explicit opt-in cache of the EXISTING VINTO app shell for offline reload.
 * The service worker never sees a vault key, user identity, API response,
 * capture, signed grant, or session token.
 */
export async function prepareQualityOfflineShell():Promise<void>{
 if(typeof window==="undefined"||!("serviceWorker" in navigator)||
    !window.isSecureContext||!navigator.onLine)
  throw new Error("offline_shell_requires_online_https");
 const registration=await navigator.serviceWorker.register(
  "/vinto-quality-offline-sw.js",{scope:"/"});
 const ready=await navigator.serviceWorker.ready;
 const worker=ready.active??registration.active;
 if(!worker)throw new Error("offline_shell_unavailable");
 const assets=[...document.querySelectorAll<HTMLScriptElement>("script[src]")].map(x=>x.src)
  .concat([...document.querySelectorAll<HTMLLinkElement>(
   'link[rel="stylesheet"],link[rel="modulepreload"],link[rel="preload"][as="script"]')]
   .map(x=>x.href)).filter(url=>{
    try{
     const u=new URL(url);
     return u.origin===window.location.origin&&u.pathname.startsWith("/_next/static/");
    }catch{return false;}
   });
 const channel=new MessageChannel();
 const result=await new Promise<boolean>((resolve,reject)=>{
  const timer=window.setTimeout(()=>{
   channel.port1.close();
   reject(new Error("offline_shell_cache_timeout"));
  },20000);
  channel.port1.onmessage=e=>{
   window.clearTimeout(timer);
   channel.port1.close();
   resolve(e.data?.ready===true);
  };
  worker.postMessage({type:"CACHE_QUALITY_SHELL",assets},[channel.port2]);
 });
 if(!result)throw new Error("offline_shell_not_cached");
}
