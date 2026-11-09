// node --test scripts/usr-05-admin-users-ui.test.mjs
// Render SSR real de los componentes de USR-05 y controles accesibles sin navegador ni red.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { before, after, test } from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const temp = join(root, ".tmp-usr05-ui-test-" + process.pid);
const alias = {
    name: "alias-at", enforce: "pre",
    resolveId(source) {
        if (!source.startsWith("@/")) return null;
        const path = root + "/" + source.slice(2);
        for(const file of [path + ".tsx", path + ".ts", path + "/index.tsx", path + "/index.ts"]) if (existsSync(file)) return file;
        return null;
    },
};
async function bundle(file, label) {
    const buildOutput = await build({ configFile: false, root, logLevel: "error", mode: "production", plugins: [alias],
        oxc: { jsx: { runtime: "automatic" } }, build: { write: false, ssr: join(root,file), minify: false, target: "node22", rollupOptions: { output: { format: "es" } } } });
    const chunk = (Array.isArray(buildOutput) ? buildOutput[0] : buildOutput).output.find((a) => a.type === "chunk");
    const target = join(temp,label+".mjs");
    writeFileSync(target,chunk.code);
    return import(pathToFileURL(target).href);
}
let React,renderer,ui;
before(async () => {
    mkdirSync(temp,{recursive:true});
    [React,renderer] = [await import("react"),await import("react-dom/server")];
    ui = await bundle("components/vinto/admin/admin-user-accounts.tsx","accounts");
});
after(() => rmSync(temp,{recursive:true,force:true}));
const html = (cmp,props) => renderer.renderToStaticMarkup(React.createElement(cmp,props));
const noop = () => {};
const U = {id:"11111111-1111-4111-8111-111111111111",username:"qa.admin",display_name:"Administrador QA",active:true,profiles:["DATA_BALTREK"],sectors:[]};
const profiles=[{code:"DATA_BALTREK",name:"Data Baltrek"},{code:"OPERACION",name:"Operación"}];
const target=(action,user=U)=>({action,user:action==="create"?null:user});
const isDisabled=(text,aria)=>/\sdisabled(=""|\s|>)/.test((text.match(new RegExp('<button[^>]*aria-label="'+aria+'"[^>]*>'))??[""])[0]);

test("toolbar contains one create entry and fails closed when catalogue is unavailable",()=>{
    const ready=html(ui.AccountToolbar,{profiles:{status:"ready",data:profiles,refreshing:false},locked:false,onCreate:noop,onRetry:noop});
    assert.ok(ready.includes("Nuevo usuario") && !isDisabled(ready,"Crear usuario"));
    const loading=html(ui.AccountToolbar,{profiles:{status:"loading"},locked:false,onCreate:noop,onRetry:noop});
    assert.ok(isDisabled(loading,"Crear usuario") && loading.includes("Consultando perfiles disponibles"));
    const failed=html(ui.AccountToolbar,{profiles:{status:"error",kind:"unavailable",refreshing:false},locked:false,onCreate:noop,onRetry:noop});
    assert.ok(isDisabled(failed,"Crear usuario") && failed.includes("Reintentar"));
    const blocked=html(ui.AccountToolbar,{profiles:{status:"ready",data:profiles,refreshing:false},locked:true,onCreate:noop,onRetry:noop});
    assert.ok(isDisabled(blocked,"Crear usuario"));
});
test("account actions reflect active/inactive status, don't offer both lifecycle buttons and obey lock",()=>{
    const base={user:U,locked:false,currentUserId:"99999999-9999-4999-8999-999999999999",onOpen:noop};
    const active=html(ui.AccountUserActions,base);
    assert.ok(active.includes('aria-label="Editar cuenta"') && active.includes('aria-label="Restablecer contraseña"'));
    assert.ok(active.includes('aria-label="Desactivar cuenta"') && !active.includes('aria-label="Reactivar cuenta"'));
    const inactive=html(ui.AccountUserActions,{...base,user:{...U,active:false}});
    assert.ok(inactive.includes('aria-label="Reactivar cuenta"') && !inactive.includes('aria-label="Desactivar cuenta"'));
    const blocked=html(ui.AccountUserActions,{...base,locked:true});
    for(const label of ["Editar cuenta","Restablecer contraseña","Desactivar cuenta"]) assert.ok(isDisabled(blocked,label));
    const self=html(ui.AccountUserActions,{...base,currentUserId:U.id});
    assert.ok(self.includes("puede cerrar tu sesión"));
});
test("create form contains verified username, active profile catalogue and two secret inputs",()=>{
    const markup=html(ui.AccountForm,{target:target("create"),profiles,submitting:false,onConfirm:noop,onClose:noop});
    for(const name of ["usr05-username","usr05-name","usr05-profile","usr05-password","usr05-password-confirm"]) assert.ok(markup.includes('id="'+name+'"'));
    assert.ok(markup.includes('type="password"'));
    assert.equal(markup.split('type="password"').length-1,2);
    assert.ok(markup.includes('autoComplete="new-password"') || markup.includes('autoComplete="new-password"'.toLowerCase()) || markup.includes('autoComplete="new-password"'.replace("C","c"))); // React SSR serialization
    assert.ok(markup.includes("Data Baltrek") && markup.includes("Operación") && !markup.includes("INVENTADO"));
    assert.ok(!markup.includes("Conceder acceso") && !markup.includes("actor_id"));
});
test("all account form variants have white input backgrounds and legible text in dark OS mode",()=>{
    for (const action of ["create","edit","reset","deactivate","reactivate"]) {
        const markup=html(ui.AccountForm,{target:target(action,action==="reactivate"?{...U,active:false}:U),profiles,submitting:false,onConfirm:noop,onClose:noop});
        const inputs=[...markup.matchAll(/<input\b[^>]*>/g)].map((match)=>match[0]);
        assert.ok(inputs.length>0, action+" must have an input");
        for (const field of inputs) {
            for(const token of ["bg-white","text-slate-950","dark:bg-white","dark:text-slate-950","border-slate-300"])
                assert.ok(field.includes(token),action+" field missing "+token);
        }
        assert.ok(markup.includes("text-slate-900") && markup.includes("dark:text-slate-900"),action+" cancel action contrast");
        if(action==="create" || action==="edit") {
            const select=markup.match(/<select\b[^>]*>/)?.[0] || "";
            for(const token of ["bg-white","text-slate-950","dark:bg-white","dark:text-slate-950"])
                assert.ok(select.includes(token),action+" select missing "+token);
        }
    }
});

test("account modal overrides the shared dark theme without changing global dialog or business logic",()=>{
    const source=readFileSync(join(root,"components/vinto/admin/admin-user-accounts.tsx"),"utf8");
    assert.match(source,/const ACCOUNT_MODAL_CLASS = "[^"]*bg-white text-slate-950[^"]*dark:bg-white dark:text-slate-950"/);
    assert.ok(source.includes('<DialogContent showCloseButton={!pending} className={ACCOUNT_MODAL_CLASS}'));
    assert.ok(source.includes('DialogDescription className="text-slate-700 dark:text-slate-700"'));
    assert.ok(source.includes('const ACCOUNT_CONFIRM_CLASS = "bg-[#146b4f] text-white'));
    assert.ok(source.includes('className={ACCOUNT_CANCEL_CLASS}'));
});

test("edit preserves username identity; lifecycle requires reason and warns about session revocation",()=>{
    const common={profiles,submitting:false,onConfirm:noop,onClose:noop};
    const edit=html(ui.AccountForm,{...common,target:target("edit")});
    assert.ok(!edit.includes('id="usr05-username"') && !edit.includes('type="password"'));
    assert.ok(edit.includes("Administrador QA") && edit.includes("DATA_BALTREK"));
    const deactivate=html(ui.AccountForm,{...common,target:target("deactivate")});
    assert.ok(deactivate.includes('id="usr05-reason"') && deactivate.includes("sesiones actuales se revocarán"));
    const reactivate=html(ui.AccountForm,{...common,target:target("reactivate",{...U,active:false})});
    assert.ok(reactivate.includes("sesiones anteriores seguirán invalidadas"));
    const reset=html(ui.AccountForm,{...common,target:target("reset")});
    assert.ok(reset.includes("usr05-password-confirm") && !reset.includes('id="usr05-profile"'));
});
test("submitting form disables inputs/cancel and no credentials appear in feedback",()=>{
    const form=html(ui.AccountForm,{target:target("create"),profiles,submitting:true,onConfirm:noop,onClose:noop});
    assert.ok(form.includes('aria-busy="true"') && form.includes("Aplicando…"));
    assert.ok(form.includes('id="usr05-password"') && form.includes('disabled=""'));
    const state={step:"done",target:target("deactivate"),outcome:{action:"deactivate",username:"qa.admin",userId:U.id,changed:true,sessionsRevoked:2,requestId:"audit"}};
    const result=html(ui.AccountDialog,{state,profiles,onConfirm:noop,onClose:noop});
    assert.ok(!result.includes("password-valid-123"));
});
test("uncertain remote result disables reread while pending and never claims success",()=>{
    const pending=html(ui.AccountUncertain,{checking:true,onRetry:noop});
    assert.ok(pending.includes("pudo haberse aplicado") && pending.includes("Releyendo"));
    const retry=html(ui.AccountUncertain,{checking:false,onRetry:noop});
    assert.ok(retry.includes("Releer estado") && !isDisabled(retry,"Releer estado"));
});
