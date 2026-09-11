# Verificación contra la base real de Ninox

Todo lo que hay aquí está **medido**, no deducido. Cada afirmación indica la
sonda que la produjo (en `tools/`) para poder repetirla.

Fecha de las pruebas: **11/09/2026**. Base: JULSA INDUSTRIAL (Ninox, API v1).
Tablas usadas para escribir: **`DF` «BFI 61021 (TEST)»**, la única vacía y con
campos escribibles. Ninguna prueba escribió en `OD`, `PD` ni `TD`.

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

## 5. Prueba de punta a punta: PDF → CSV → Ninox

`tools/prueba_extractor_sintetico.py` genera un extracto **con el mismo formato
de texto** que produce el banco (el CSV de ejemplo salió de uno real) y
`main.py insertar … --tabla-test` lo procesa entero:

```
1 PDF(s) encontrados.
Procesando: extracto.pdf
   -> 3 movimiento(s) | cuenta 0300000006102035 | estado 522
CSV generado: movimientos_bfi.csv (3 filas)
TD — BFI 61020: 3 linea(s)
Mapeo validado para OD (9 campos comprobados).
Mapeo validado para PD (9 campos comprobados).
Mapeo validado para TD (10 campos comprobados).
Conexion correcta: OD OK, PD OK, TD OK
ENSAYO: se escribe en DF en lugar de en las tablas reales.
DF: 0 registros en Ninox, 0 linea(s) ya presentes.
   corregido: registro 97: 'Saldo inicial' se corrigio a 27250.15
   corregido: registro 98: 'Saldo inicial' se corrigio a 31270.14
   corregido: registro 99: 'Saldo inicial' se corrigio a 28770.14
   -> DF: 3 insertada(s), 0 omitida(s), 0 con error
CSV eliminado: movimientos_bfi.csv
```

Y los tres registros quedaron así en Ninox (leídos de vuelta antes de borrarlos):

| Fecha | Referencia | Detalle | Importe | Egreso/Ingreso | Saldo inicial |
|---|---|---|---|---|---|
| 2026-06-30 | FT2619000001 | COMISION BANCARIA | 1 | `true` | 27250.15 |
| 2026-06-30 | FT2619000002 | TRANSFERENCIA RECIBIDA: USD | 4019.99 | `false` | 31270.14 |
| 2026-07-01 | DC2618000003 | PAGO PROVEEDOR ACOREC S.A. | 2500 | `true` | 28770.14 |

`Tipo de Cambio CUP-USD` = 24 en los tres (regla del apartado 5.2 para `TD`) y
`Factura` en blanco en los tres.

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
