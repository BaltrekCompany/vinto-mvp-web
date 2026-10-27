# MF-09 · Bobinas y Operación: P1-01 (versión 3) y P1-06 (versión 2)

Observaciones MD_Ejec 10, 12, 13, 15 y 18 del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`). El Excel original **no se modifica**.

## P1-01 · Operación e inspección de máquina (v3, MD_Ejec 10, 12, 13 y 15)

Se retiran de las capturas nuevas exactamente estos **11 campos** (lista definitiva autorizada; 84 → 73 campos):

| Obs. | Campos retirados (clave técnica) |
|---|---|
| 10 | `presion_cocedores` (tampoco queda como encabezado) |
| 12 | `nivel_tanque_h_20_aguas`, `nivel_tanque_h_20_aguas_2`, `nivel_tanque_h_20_accionamientos`, `opertado`, `produccion` |
| 13 | `presion_pope`, `apertura_campana`, `presion_regaderas` |
| 15 | `limpieza_sala_de_control`, `limpieza_mezzanine` |

- No se retira ningún otro campo, aunque aparezca marcado en otras imágenes del Excel. Los demás conservan clave, etiqueta, tipo, obligatoriedad, unidad y orden; los grupos visuales de la pantalla siguen siendo los mismos 7 (ninguno queda vacío).
- En la v3 los 11 campos no son obligatorios (no existen) y enviarlos es un campo desconocido (422).
- Las capturas v1 y v2 conservan sus valores; el historial muestra los 11 como «versión anterior».
- Alcance de máquinas: se mantienen los vínculos existentes (MP1 y MP3), sin cambios.

## P1-06 · Registro de control de fardos (v2, MD_Ejec 18)

- «Tipo de producto» suma **Toalla** (`toalla`) como cuarta y última opción: Servilleta, Hoja doble, Hoja simple, Toalla.
- Las opciones existentes conservan clave, etiqueta y orden; «Punto de merma» y los demás campos no cambian.
- Cómo se valida: el backend valida contra las opciones de la versión publicada (`field_option`), por eso hace falta la v2; la pantalla de fardos declara las opciones en `TIPO_PRODUCTO_OPTIONS`. No hay otro catálogo ni validador, ni migración. No se toca la creación de bobinas, asignaciones u OT.
- Las capturas v1 conservan sus valores y se leen igual; con la definición v1 «toalla» sigue sin existir.

## Importación (aditiva e idempotente, sin migraciones)
Sobre el estado actual de producción (en PostgreSQL efímero): 2 versiones, 78 campos (73 + 5), 4 vínculos de máquina y 6 opciones; sin conflictos; las versiones anteriores y los demás formularios quedan idénticos.

## Fuera de alcance
MD_Ejec 5, 9, 11, 14 (nombres/estructura sin definir), 16, 17, 19, 20, Rebobinado, Conversión, 33 y 51.
