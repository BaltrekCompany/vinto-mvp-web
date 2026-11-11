# CV-P111-RECETA-v3 — consumo de bobinas por receta de artículo (Conversión)

**Alcance aprobado:** tres posiciones horizontales, primera obligatoria, segunda/tercera opcionales, con materiales filtrados por el artículo de la OT. PR #177; **no autoriza merge ni despliegue**.

## Autoridad de datos
- Fuente proporcionada: INArticulo-MFMatrialOP (1)(2).xlsx. Hoja INInventario: columna A código y B descripción; hoja MFRutaMaterialOP: A RutaMaterial (código de artículo), C MaterialUso, D Material, E Descripcion. La hoja MFRutaMaterialOP (2) coincide con la primera.
- La aplicación ya contiene el catálogo lib/vinto/recipes.ts con 269 productos; se reutiliza como lista de opciones y se reproduce su whitelist de códigos en backend/app/p111_material_codes.json. Producto sin receta en ese catálogo: se bloquea el envío.
- Ejemplo 10327 (PERLITA HOJA DOBLE EXTRA 6*8): 9483, 9484, 9481, 9482, M3-3038, 9534, 9397, 9733, 9455, 9670. Excel: INInventario fila 19 y MFRutaMaterialOP filas 2–11 (operación Conversión).

### Fuente de verdad y alcance de la autorización (11/nov/2026)
- Archivo Excel entregado: INArticulo-MFMatrialOP (1)(2).xlsx; SHA-256 de sus bytes: `9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228`. El Excel prevalece para código, descripción, operación, materiales y receta; no usar el antiguo maestro como autoridad contradictoria.
- El Excel tiene 12 767 artículos de inventario y 719 códigos con rutas (160 en la operación Conversión). Estas cifras **no** autorizan crear artículos, recetas o relaciones de máquina de forma masiva: el piloto conserva su alcance controlado.
- La columna `Operacion=Conversion` solo identifica el sector. **El Excel no contiene máquina concreta**: la asociación `10327 + GAMBINI` es una autorización funcional explícita del usuario, distinta de la fuente documental. Se incorpora únicamente esa relación maestra; se conservan `10327 + SINCRO_II` y `10327 + SINCRO_III`.
- No se altera ningún otro par artículo–máquina, ni el nombre del artículo ni los diez materiales de su receta. La asociación nueva se importa como cambio aditivo en `vinto_master.article_machine`.

## Contrato funcional
1. Tres espacios visibles fijos, sin añadir ni borrar filas. Posición 1 obligatoria; posiciones 2 y 3 opcionales sin campos parciales.
2. Posición seleccionable: Superior / Inferior / No aplica.
3. Tipo según receta: exclusivamente materiales de la receta del código de producto de la línea activa de OT. Se valida de nuevo en backend en la misma transacción.
4. N.º bobina texto declarado; saldos inicial/ingreso/final como decimales manuales en kg.
5. Consumo calculado mostrado EN LA MISMA FILA: saldo inicial + ingreso - saldo final. No se envía como campo ni mueve inventario. La merma queda separada.
6. Conserva la idempotencia, el usuario autenticado de la sesión y lectura posterior del registro.

## Compatibilidad
- La definición VINTO-P1-11 v3 se crea como nueva versión publicada de modo aditivo. No altera las versiones históricas v1/v2 ni otras definiciones publicadas.
- La interfaz v3 omite Hora inicio/fin existentes en v2 porque no forman parte del diseño aprobado. Los registros de v2 siguen siendo legibles con su contrato de horas.
- No se necesita un nuevo archivo SQL de esquema; se requiere **importar la nueva versión de formulario** desde el bundle oficial.

## Puertas QA y despliegue futuro (NO EJECUTAR AUN)
1. GitHub QA PostgreSQL 17 aislado + referencia de formularios + API con filtro de producto, 1/2/3 filas, 422, idempotencia y v1/v2; Node, TypeScript, lint y build.
2. Merge únicamente con CI PASS, revisión formal y autorización.
3. VPS: backup/restauración verificable de PostgreSQL, instalar release candidato SHA exacto, backend y artefacto frontend Linux, sin activar.
4. IMPORTANTE: el script operativo deploy.sh import-reference lee CURRENT. Para preparar este release, ejecutar import_reference.py --target dev **desde el directorio backend del CANDIDATO**, primero dry-run sin escritura; comprobar que agregue **únicamente** la versión P1-11 v3 y sus campos/opciones **más** el par artículo 10327–máquina GAMBINI. Solo entonces aplicar --apply desde candidato con autorización y comprobar la versión 3 publicada para las tres máquinas.
5. preflight-startup, check-release, gate D2, activar candidato con deploy.sh activate, salud y QA visual en producción autorizada.
6. QA visual: el artículo 10327 en GAMBINI y en SINCRO_II/III ofrece diez opciones; fila 1 completa; 2/3 opcionales; consumo horizontal; historial; no acepta material ajeno.

**Rollback:** rollback.sh version <sha-previo> cambia código, NO revierte el catálogo de formulario importado; compatibilidad debe verificarse antes de cualquier reversión. No restaurar base ni forzar downgrade automáticamente.
