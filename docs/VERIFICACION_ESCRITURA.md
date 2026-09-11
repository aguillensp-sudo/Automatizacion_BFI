# Verificación contra la base real de Ninox

Todo lo que hay aquí está **medido**, no deducido. Cada afirmación indica la
sonda que la produjo (en `tools/`) para poder repetirla.

Fecha de las pruebas: **11/09/2026**. Base: JULSA INDUSTRIAL (Ninox, API v1).
Tablas usadas para escribir: **`DF` «BFI 61021 (TEST)»**, la única vacía y con
campos escribibles. Ninguna prueba escribió en `OD`, `PD` ni `TD`.

---

## 0. Correcciones a versiones anteriores de este informe

Dos errores de la primera entrega, corregidos aquí para que quede constancia en
el mismo sitio donde se afirmaron:

1. **«El CSV no tiene ninguna línea con crédito»** — falso. Tiene **tres**
   (19.102,86 / 7.992,00 / 8,00). Salió de un recuento a mano, no de una
   comprobación. Ver §5-bis.
2. **El mensaje del commit `7052116` presenta la aceptación de ids de campo como
   un hallazgo de este proyecto.** No lo es: ya estaba documentado y verificado
   en `Automatizacion JI` → `docs/ninox/README.md` §7. No se ha reescrito la
   historia de un repositorio ya publicado; la corrección queda aquí.

---

## 0-bis. Aviso sobre el alcance de esta verificación

Este informe **no descubre** cómo funciona la API de escritura de Ninox: eso ya
estaba documentado, y verificado contra la base real, en el proyecto hermano
`Automatizacion JI`:

> `docs/ninox/README.md` §0 (reglas de actuación) y **§7 (Escritura), verificado
> el 11/09/2026** con `tools/verify_write_api.py`.

La guía indica además el orden de lectura correcto: quien vaya a escribir debe
leer §0 y §7 **enteros antes de tocar nada**. Aquí se distinguen tres cosas:

| | |
|---|---|
| **Ya documentado y confirmado** | La forma del cuerpo (`{"fields": {...}}`), que los ids de campo funcionan, que el `PUT` hace *merge*, y que un nombre de campo inexistente devuelve HTTP 500. Está en §7. |
| **Específico de este proyecto** | El mapeo cuenta → tabla y columna → campo (documento funcional `AppWindows_BFI.md`), y el comportamiento particular de `Saldo inicial`, `Secuencial` y `Conciliado` en `OD`/`PD`/`TD`/`DF`. |
| **Medido aquí, sin documentar en ninguna parte** | La cadena de saldos de los extractos reales y el recuento de líneas e ingresos. |

Las sondas de esta carpeta se conservan para poder repetir cada medición, no
porque sustituyan a la guía.

---

## 1. ¿La API acepta el *id* de campo (`R1`, `G1`…) o exige el nombre?

**Acepta el id de campo.** Es el punto que decidía si el mapeo del documento
funcionaba tal cual, así que se comprobó antes de escribir nada.

`tools/probe_df.py --execute` — se creó un registro enviando:

```json
{"fields": {"R1": "BFI-PROBE-ID-VS-NOMBRE", "G1": "detalle prueba",
            "D": 111.11, "O": 222.22, "F": true, "Q1": "No"}}
```

y el registro guardado quedó así:

| Enviado | Campo en que quedó | Nombre real |
|---|---|---|
| `R1` | ✅ | `Factura` |
| `G1` | ✅ | `Conciliado` (en `DF`, `G1` es un `choice`) |
| `D` | ✅ | `Importe USD` |
| `O` | ✅ | `Saldo inicial` |
| `F` | ✅ | `Egreso/Ingreso` |
| `Q1` | ✅ | `Oper. en tránsito` |

**Consecuencia para el diseño.** Aun aceptando ids, la aplicación resuelve el
mapeo a **nombres** contra los metadatos de la tabla destino y aborta el lote
entero si algún id no existiera. Motivo: un nombre de campo inexistente devuelve
**HTTP 500**, indistinguible de una caída del servidor. Traducir antes convierte
un fallo opaco en un mensaje claro. `tests/test_mapping.py`
(`test_un_id_inexistente_en_la_tabla_destino_aborta`) cubre este camino.

---

## 2. ¿Qué campos se rellenan solos al crear un registro?

`tools/probe_td_defaults.py --execute` (sobre `DF`, que es estructuralmente
idéntico a `TD`: mismos ids de campo `B, D, F, J, C1, K1, R1, S1, O, Q1, G1`).

Enviando `{"B","S1","K1","D","O","F","Q1","J","C1"}`, el registro quedó:

| Campo | Enviado | Guardado | Resultado |
|---|---|---|---|
| `Fecha Bancaria` | `2026-07-01` | `2026-07-01` | OK |
| `Referencia` | marcador | marcador | OK |
| `Detalles` | `detalle de prueba` | `detalle de prueba` | OK |
| `Importe USD` | `12.34` | `12.34` | OK |
| `Egreso/Ingreso` | `true` | `true` | OK |
| `Oper. en tránsito` | `No` | `No` | OK |
| `Tipo de Cambio CUP-USD` | `24` | `24` | OK |
| `Tipo de Cambio USD-EUR` | `""` | *(ausente)* | equivalente a vacío |
| **`Saldo inicial`** | **`999.99`** | **`23226.13`** | **DIFIERE — valor por defecto** |

**Auto-rellenados sin enviarlos:** `Secuencial` (contador) y `Conciliado` (`No`).

---

## 3. ¿`Saldo inicial` es un campo calculado?

En las tablas reales tiene **un valor distinto por registro** (OD: 1.457 valores
distintos en 1.458 filas; PD: 319 en 321; TD: 862 en 866). Un campo calculado no
se comporta así, y los valores coinciden con el saldo real de cada línea del
extracto. Por tanto, **es almacenado**, y el valor por defecto sólo gana **en el
alta**.

`tools/probe_saldo_put.py` lo confirmó:

```
POST -> 200   tras POST, Saldo inicial = 23226.13   (se envió 111.11)
PUT  -> 200   tras PUT,  Saldo inicial = 222.22     (se envió 222.22)
```

**Consecuencia para el diseño.** El escritor relee cada registro creado y, si un
campo no se guardó como se envió, lo **reintenta con un `PUT`**. Sin este paso el
saldo de cada línea se perdía en silencio. La opción «Corregir los campos que
Ninox descarte» controla esta conducta y viene activada.

---

## 4. Ensayo del circuito completo

`tools/ensayo_df.py movimientos_bfi.csv --execute` — 44 líneas del CSV de
ejemplo, todas redirigidas a `DF`:

```
Lineas por tabla segun cuenta_no: {'OD': 37, 'PD': 2, 'TD': 5}
Insercion terminada
  • DF — BFI 61021 (TEST): 44 insertada(s), 0 omitida(s), 0 con error
Corregidos con un segundo envio (44):   (todas por 'Saldo inicial')
Campos que Ninox no dejo escribir (0)
Borrando los 44 registros creados... Limpieza terminada. Fallos: 0
```

`DF` volvió a quedar con **0 registros**, verificado leyendo la tabla después.

---

## 5. Prueba de punta a punta con los PDFs reales

`python tools/validar_extraccion.py .` sobre los **20 extractos PDF reales**:

```
=== 1. LINEAS POR CUENTA ===
   0300000005399610   ->  37 lineas  (tabla OD)
   0300000006102035   ->   5 lineas  (tabla TD)
   0300000006074740   ->   2 lineas  (tabla PD)
   TOTAL              ->  44 lineas

=== 2. IMPORTES (debito XOR credito) ===
   solo debito    : 41
   solo credito   : 3  <-- ingresos
   ninguno        : 0
   los dos a la vez: 0

=== 3. CADENA DE SALDOS (saldo[i] = saldo[i-1] +/- importe[i]) ===
   0300000005399610: 36/36 movimientos encadenan
   0300000006074740: 1/1 movimientos encadenan
   0300000006102035: 4/4 movimientos encadenan

=== 4. SIGNO ESCRITO EN NINOX (Egreso/Ingreso) ===
   lineas con Egreso/Ingreso = False (ingresos): 3
   lineas con Egreso/Ingreso = True  (egresos) : 41
```

La comprobación **3** es la fuerte: reconstruye la cadena de saldos de cada
cuenta y exige que cada saldo sea el anterior más o menos el importe. Que encajen
las 41 transiciones descarta a la vez un movimiento perdido, un importe mal leído
y un signo invertido.

### Los tres ingresos, insertados de verdad y releídos de Ninox

`python main.py insertar <carpeta> --confirmar --tabla-test` con los 20 PDFs
(redirigido a `DF`), y después lectura de lo que quedó guardado:

```
registros insertados en DF: 44

=== VERIFICACION DE SIGNOS ===
   Egreso/Ingreso = False (INGRESOS/creditos): 3
   Egreso/Ingreso = True  (EGRESOS/debitos) : 41

=== LOS INGRESOS, tal como quedaron en Ninox ===
   fecha=2026-07-20 ref=85522010001246   importe=19102.86  saldo=127648.18
   fecha=2026-07-08 ref=FT2619151273     importe=7992      saldo=31218.13
   fecha=2026-08-19 ref=52542310006746   importe=8         saldo=28026.13
```

**44 insertadas, 0 omitidas, 0 errores.** Cada crédito con su importe en el campo
`D` de su tabla (`Importe CUP` en PD, `Importe USD` en TD) y
`Egreso/Ingreso = False`. `DF` se limpió después: **0 registros restantes**.

---

## 5-bis. Corrección de un error de este mismo informe

**En la primera versión de este documento se afirmó que el CSV no tenía ninguna
línea con crédito. Era falso: tiene tres.** La afirmación salió de un recuento
hecho a mano en una consola, no de una comprobación, y contradecía el propio
fichero que estaba delante. El extractor siempre las trató bien; el error fue
exclusivamente del informe.

La lección no es «mirar mejor», es que **un recuento a ojo no es una
verificación**. Por eso ahora existen:

* `tools/validar_extraccion.py`, que recalcula los totales desde los PDFs y
  valida además la cadena de saldos de cada cuenta;
* tres pruebas de regresión en `tests/test_mapping.py` que fijan los tres
  ingresos concretos y el signo que se escribe para cada línea.

---

## 5-ter. Prueba con un extracto sintético

`tools/prueba_extractor_sintetico.py` genera un PDF con el mismo formato de texto
del banco y comprueba cabecera, importes y mapa de cuentas. Permite verificar el
parser sin depender de tener los extractos reales a mano:

```
Cabecera detectada:
   cuenta_no       = '0300000006102035'
   moneda          = 'USD'
   saldo_anterior  = 27251.15
Movimientos: 3
   2026-06-30 | FT2619000001 | debito=1.0     credito=None     saldo=27250.15
   2026-06-30 | FT2619000002 | debito=None    credito=4019.99  saldo=31270.14
   2026-07-01 | DC2618000003 | debito=2500.0  credito=None     saldo=28770.14
Cuenta -> tabla Ninox: TD
```

Estos tres registros también se insertaron en `DF` y se releyeron: los tres con
`Tipo de Cambio CUP-USD = 24` (regla del apartado 5.2 para `TD`) y `Factura` en
blanco, y con `Egreso/Ingreso` correcto (`true`, `false`, `true`).

---

## 6. Decisiones que la verificación provocó

| Hallazgo | Decisión |
|---|---|
| La API acepta ids, pero un nombre mal escrito da HTTP 500 | Se traduce el mapeo a nombres contra los metadatos reales y se aborta el lote si algo no cuadra. |
| `Saldo inicial` se queda con el valor por defecto en el alta, pero acepta `PUT` | Relectura de cada registro + reenvío opcional de los campos descartados. |
| `Secuencial` y `Conciliado` se auto-rellenan | No se envían y no se interpretan como datos propios. |
| El documento dice «Tipo de Cambio en blanco» en OD y PD | Se **omite** el campo en lugar de enviarlo vacío: el `PUT` hace *merge* y enviarlo vacío podría borrar un valor calculado por otro proceso. |
| No hay campo `cuenta` en ninguna de las tres tablas | La cuenta **no se escribe**; sirve para enrutar la línea a su tabla. La referencia del banco queda en `Referencia`. |
| El campo `Factura` puede heredar valores de otras operaciones | Se envía **explícitamente vacío**. |
| El documento del ERP prohíbe borrar en tablas de negocio | Los ensayos se hacen sobre `DF`; nunca se creó ni borró nada en `OD`, `PD` ni `TD`. |

---

## 7. Cómo repetir estas pruebas

```bat
python tools\validar_extraccion.py .        ::  CSV vs PDFs reales + cadena de saldos
                                            ::  (la comprobacion mas fuerte; no usa Ninox)

python tools\probe_df.py                    ::  simulación (no escribe)
python tools\probe_df.py --execute          ::  id de campo vs nombre

python tools\probe_td_defaults.py           ::  simulación
python tools\probe_td_defaults.py --execute ::  campos por defecto (sobre DF)

python tools\probe_saldo_put.py             ::  ¿Saldo inicial acepta PUT?

python tools\ensayo_df.py movimientos_bfi.csv --execute
                                            ::  las 44 líneas del CSV, sobre DF

python tools\prueba_extractor_sintetico.py  ::  PDF sintético -> parser

python main.py insertar <carpeta> --confirmar --tabla-test
                                            ::  punta a punta, escribiendo en DF
```

Todas las sondas que escriben **crean en `DF` y borran lo que crean en un
`finally`**. `DF` estaba vacía antes de empezar y quedó vacía al terminar: se
comprobó después de cada ensayo.

> **Aviso para quien repita esto.** `DF` es la tabla auxiliar del ERP; si otro
> proceso la usa como banco de pruebas, comprobar su contenido antes y después.
> Las sondas identifican lo que crean por el `id` de la respuesta del `POST`.
