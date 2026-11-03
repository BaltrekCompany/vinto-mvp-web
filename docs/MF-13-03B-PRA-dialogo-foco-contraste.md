# MF13-03.B PR-A — foco y contraste del diálogo de activación masiva (DEF-1 y DEF-2)

Base: `origin/main` acb5335 (merge de PR #114). Solo frontend del diálogo de PR7 + pruebas + documentos. **Sin cambios de comportamiento de la activación masiva, contratos HTTP, permisos, backend, migraciones ni tema global.** No se desplegó nada ni se tocó la VPS, `vinto_piloto`, TVC, ETL, Nginx ni flags.

## 1. Causas confirmadas

### DEF-1 — el foco no vuelve al botón que abrió el diálogo
- **Medido, no supuesto.** Una sonda con eventos de foco reales (clic de ratón real) mostró: `focusin` en «Activar todas las líneas» → `focusin` en «Cerrar» → al pulsar Escape `focusout` de «Cerrar» y **ningún `focusin` posterior**; el botón invocador seguía conectado, habilitado y era el mismo nodo. Termina en `<body>`.
- **Causa:** en el código de Radix (`@radix-ui/react-dialog`, `DialogContentModal`) `onCloseAutoFocus` se compone con `event.preventDefault(); context.triggerRef.current?.focus()`. El diálogo de PR7 se abre **por estado** (sin `DialogTrigger`), así que `triggerRef.current` es `null`: se **cancela la restauración por defecto** de Radix y no se enfoca nada.
- **Descartado:** no era un artefacto de `element.click()` (el defecto se reproduce con clic de ratón real y con Enter de teclado real); y la documentación de PR7 afirmaba incorrectamente que Radix devolvía el foco (corregida).

### DEF-2 — contraste insuficiente con el tema oscuro del sistema
- El contenedor del diálogo usa `bg-background` / color de texto heredado (tokens que **cambian** con `prefers-color-scheme: dark`: fondo `#0a0a0a`, texto `#ededed`), mientras el contenido tenía colores **claros fijos**: `bg-slate-50` (resumen y encabezados de tabla) con texto heredado claro ⇒ **1,12:1**; `text-slate-600` (PV) sobre fondo oscuro ⇒ 2,6:1; el botón «Confirmar» (`bg-[#146b4f]`) con el color de texto del token `primary-foreground`, que en oscuro es `#171717`.
- Las capturas estáticas de PR7 lo ocultaron al forzar tema claro.

## 2. Cambios
- `lib/vinto/focus-return.ts` (nuevo, puro): `isFocusable` / `pickReturnTarget`. Un destino solo recibe el foco si está **conectado, habilitado, visible y no `aria-hidden`/`aria-disabled`**.
- `components/vinto/activate-all-dialog.tsx`: `onCloseAutoFocus` de Radix (el gancho nativo) devuelve el foco al primer destino aprovechable de `returnFocusTargets()`; **solo cancela el comportamiento por defecto si hay un destino real**. Los destinos se evalúan **al cerrar** (el invocador pudo desaparecer o quedar deshabilitado). Colores: tokens existentes (`bg-muted`, `text-foreground`, `text-muted-foreground`), variantes `dark:` para las alertas roja y verde, y `text-white` explícito en «Confirmar».
- `components/vinto/bobinas-programming.tsx`: recuerda el invocador (`event.currentTarget`) y ofrece como alternativas su **tarjeta de OT** y el **panel** (ambos `tabIndex={-1}`, sin outline) si el invocador ya no sirve (cambió la OT, los permisos, la sesión o las capacidades).
- **Sin tocar:** el tema global (`globals.css`), el hook de la activación, el cliente HTTP, el reductor, las garantías de PR7 (probadas igual que antes: Escape/clic fuera bloqueados con la confirmación en vuelo, X oculta, foco inicial en «Cerrar», doble clic = una confirmación).

## 3. Resultados de QA

### E2E en navegador real (Chrome 156 por CDP, frontend y backend reales, PostgreSQL 17 efímero; `scripts/e2e/pra-run.mjs`)
Entradas **reales** (ratón, teclado), no `element.click()`; el clic programático se ensaya aparte (equivale a Safari/Firefox en macOS y a un toque, donde el botón no recibe foco).

| | Antes (acb5335) | Después |
|---|---|---|
| Comprobaciones | 44 | 44 |
| OK | 29 | **44** |
| Fallos | 15 | **0** |

Cubierto (después, todo OK): foco inicial dentro del diálogo y nunca sobre «Confirmar»; Escape, «Cerrar» y la X devuelven el foco al invocador (abriendo con ratón, con teclado y con clic programático); trampa de foco con Tab/Mayús+Tab (orden Cerrar → Actualizar → Confirmar → X); invocador **deshabilitado** u **oculto** al cerrar ⇒ el foco cae en la tarjeta de la OT (nunca en `<body>` ni en el elemento deshabilitado); **confirmación en vuelo** (latencia de red): Escape no cierra, la X no se ofrece, «Cerrar» y «Confirmar» deshabilitados, y al terminar el cierre devuelve el foco; **doble clic real** ⇒ una sola confirmación y 3 asignaciones en PostgreSQL; estado «incierto» sin red ⇒ nada se activó y el cierre devuelve el foco; escritorio y móvil de 390 px (sin desplazamiento horizontal, diálogo dentro de la pantalla).
**Contraste medido en el navegador** sobre **todo** el texto visible del diálogo (color efectivo contra fondo efectivo, umbral 4.5:1 y 3:1 para texto grande) en vista previa, resultado, conflicto, estado «incierto» y móvil, con tema claro y oscuro emulados: **0 elementos bajo el umbral**. Mínimos medidos: claro 6,20:1; oscuro 6,47:1 (7,66:1 en alertas). Antes: 1,12:1 en el resumen y los encabezados.

### Pruebas Node (`scripts/pra-dialog-a11y.test.mjs`, 14, OK)
Ayudante de foco (invocador válido, ausente, deshabilitado, oculto, `aria-*`, sin destino ⇒ nada), garantías de fuente (gancho de Radix, destinos evaluados al cerrar, `tabIndex`, garantías de PR7 intactas, sin `slate-*` fijos, variantes `dark:` en todas las alertas, tema global intacto) y matemática WCAG de los pares de color usados (claro y oscuro ≥ 4.5:1; los pares antiguos fallan).

### Suites frente a `origin/main` (mismo entorno)
- **Frontend:** `origin/main` 962 pruebas / 930 OK / **32** fallos; rama 976 / 944 / **32**, con **los mismos 32 nombres** (14 pruebas nuevas, 0 regresiones). `tsc` y `eslint` (`app components lib scripts`) limpios. No se declara la suite limpia: los 32 son heredados.
- **Backend:** no se modificó ni se reejecutó (este PR no toca backend).

## 4. Evidencias (`docs/MF-13-03B-PRA-evidencia/`)
`resultados-antes.json` / `resultados-despues.json` (con SHA, base efímera y cada comprobación), `entorno-despues.json`, capturas **tomadas por el navegador** en tema claro y oscuro (vista previa, resultado, conflicto, estado «incierto», móvil) y tres capturas «antes» del defecto (`antes-*.png`).
Nota: ambos JSON registran el SHA base acb5335 con el árbol de trabajo modificado (el arreglo aún no estaba commiteado al ejecutarlos).

## 5. Riesgos residuales
1. **Fuera del diálogo, el tema oscuro del sistema sigue teniendo botones de la aplicación con texto oscuro sobre verde** (p. ej. «Activar» y «Activar todas las líneas» en la tarjeta de la OT, detrás del velo en las capturas oscuras): usan `bg-[#146b4f]` sin texto explícito. Es preexistente y está fuera de alcance (no se toca el tema global); conviene un PR aparte que revise el modo oscuro de toda la aplicación, que hoy es un diseño solo claro con superficies de Radix que sí cambian.
2. Otros diálogos de la aplicación abiertos por estado sin `DialogTrigger` pueden tener la misma pérdida de foco (no se auditaron aquí).
3. Solo Chrome (headless, Windows); sin Firefox/Safari ni lector de pantalla real. El comportamiento de Safari (el botón no recibe foco al clic) se simuló con clic programático.
4. La alternativa de foco depende de que existan `data-work-order` y el panel con `tabIndex={-1}`; si se reestructura el panel hay que mantenerlos (hay prueba de fuente que lo exige).

## 6. Recomendación de merge
**GO**: corrige los dos defectos con causa medida, sin cambiar el comportamiento funcional, con E2E real 44/44, contraste medido en ambos temas y sin regresiones frente a `main`. Sigue pendiente la validación manual con lector de pantalla y otros navegadores.
