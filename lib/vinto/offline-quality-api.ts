/** OFF-03C.2: authenticated, HTTPS-only read-only definition package fetch. */
import { apiBaseUrl } from "./api";
import type { SignedOfflineScope } from "./offline-scope-verify.ts";

export class OfflineQualityFetchError extends Error {
    constructor(){super("Paquete offline de Calidad no disponible o no autorizado.");}
}
export async function fetchOnlineQualityPackage(
    deviceKey:string,machineCode:string,formCode:string,signedScope:SignedOfflineScope):Promise<unknown>{
    const url=new URL(apiBaseUrl()+"/api/offline/quality-package");
    const loopback=process.env.NODE_ENV==="development"&&url.protocol==="http:"&&
        ["localhost","127.0.0.1","[::1]"].includes(url.hostname);
    if(!window.isSecureContext&& !loopback)throw new OfflineQualityFetchError();
    if(url.protocol!=="https:"&&!loopback)throw new OfflineQualityFetchError();
    let response:Response;
    try{
      response=await fetch(url,{
        method:"POST",cache:"no-store",credentials:"include",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({device_key:deviceKey,machine_code:machineCode,
                             form_code:formCode,signed_scope:signedScope})
      });
    }catch{throw new OfflineQualityFetchError();}
    if(!response.ok||response.headers.get("Cache-Control")?.toLowerCase().includes("no-store")!==true)
        throw new OfflineQualityFetchError();
    try{return await response.json();}catch{throw new OfflineQualityFetchError();}
}
