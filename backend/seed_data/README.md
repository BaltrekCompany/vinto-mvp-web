# Bundle de datos de referencia (piloto Bobinas)

Datos canónicos en JSON que consumirá el importador Python. **Se generan, no se
editan a mano**, desde las fuentes TypeScript del repositorio:

```powershell
node scripts/export-seed-data.mjs           # regenera backend/seed_data/
node scripts/export-seed-data.mjs --check   # falla si el bundle versionado está desactualizado
node --test scripts/export-seed-data.test.mjs
docker compose exec backend python -B -m unittest tests.test_seed_bundle -v
```

Requiere Node con type stripping activado por defecto (>= 22.18 o 24). El
exportador no escribe en PostgreSQL ni incluye usuarios, contraseñas, OT,
asignaciones ni capturas.

## Contenido

`manifest.json` (versión, fuentes con SHA-256, archivos con SHA-256 y tamaño,
conteos, advertencias), `units`, `material_classes`, `sectors`, `machines`,
`articles` (con su versión 1), `article_machines`, `profiles`, `workflows`,
`shifts` y `forms/VINTO-P1-06.json` (Formulario 6, 5 campos y 5 opciones).
Los archivos usan UTF-8, LF y orden estable; `.gitattributes` fuerza LF para
que los bytes coincidan con el manifest.

## Reglas de autoridad

| Atributo | Fuente autoritativa |
|---|---|
| descripción y unidad del artículo | `PRODUCTS_BY_MACHINE` |
| `is_material` y clase de material | `MATERIALS` |
| `nominal_weight_kg` | `product-weights.ts` (null si no existe) |
| sector y máquinas | `GROUPS` en `app/page.tsx` |
| etiquetas, unidad y opciones del F6 | `app/page.tsx` (override y `BobbinBales`) |

Si `MATERIALS` y `PRODUCTS_BY_MACHINE` discrepan en nombre o unidad, se conserva
`PRODUCTS_BY_MACHINE` y el manifest registra `MATERIAL_CONFLICT`. Un código de
artículo repetido con datos incompatibles detiene la exportación.

## Datos provisionales

Las etiquetas de unidad, el nombre de máquina y el nombre de workflow repiten
el código de la fuente: no existe otro dato. `valid_from` (2026-01-01) y la zona
horaria de los turnos son datos técnicos provisionales; producción debe recibir
la vigencia funcional real. No se define `valid_to`.
