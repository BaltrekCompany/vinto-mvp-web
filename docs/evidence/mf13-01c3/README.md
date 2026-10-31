# Capturas de la interfaz · MF-13-01C.3

Seis capturas de la sección «Máquinas y formularios» de `/admin`. **No son una prueba manual ni usan datos reales**: se generaron renderizando los **componentes reales** (`AdminConsoleView`, `AdminGrantsSection`, `GrantDialogBody`) con datos de ejemplo
(usuarios «de ejemplo», formularios y máquinas con los códigos del bundle vigente) y el CSS del build de producción, y fotografiándolos con Edge en modo headless y esquema claro. No hubo backend ni base de datos. El QA manual integral se hará después, en la VPS.

| Captura | Qué muestra |
|---|---|
| `01-mp1-formularios-e-historial.png` | Sección A (sectores, sin cambios) y B: máquinas por sector con «ofrecidos · concedidos», formularios de MP1 con publicado / ofrecido / habilitado / concedido, y el historial |
| `02-mp3-independiente-de-mp1.png` | MP3: `VINTO-P1-01` concedido en MP3 (Revocar) mientras en MP1 sigue sin concederse; P1-31 solo se ofrece aquí |
| `03-rebobinadora-copasa-p1-10.png` | COPASA con `VINTO-P1-10` v3 (una de las cinco rebobinadoras) |
| `04-concesion-inerte-revocable.png` | Una concesión cuyo par ya no se ofrece: «Concedido · inerte», **Revocar** disponible y **sin** Conceder; aviso de sector no concedido (no se concede solo) |
| `05-resultado-incierto-acciones-bloqueadas.png` | Tras un fallo de red/503: resultado incierto, acciones bloqueadas hasta releer el estado real |
| `06-confirmacion-de-cambio.png` | Confirmación con usuario, máquina, formulario y operación, y las advertencias (sector, inercia, efecto aún no aplicado). El título usa ranuras simples: en la app real los aporta el diálogo de Radix |

Notas: la fila oscura de la tabla de usuarios es el estilo de «seleccionada» que ya tenía la consola. Los textos de ejemplo no son datos de producción.
