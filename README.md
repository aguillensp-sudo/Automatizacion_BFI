# BFI Extractor

Aplicación de escritorio para Windows que **extrae los movimientos de los
estados de cuenta en PDF del Banco Financiero (BFI)** y los **inserta en el ERP
Ninox**, cada línea en su tabla correspondiente.

Está pensada para usuarios de ofimática: se instala con un doble clic, no pide
instalar Python ni abrir una terminal, y **no escribe nada en el ERP hasta que
el usuario lo confirma**.

---

## 1. Qué hace, paso a paso

1. El usuario elige la carpeta donde están los PDFs.
2. La aplicación extrae los movimientos y genera `movimientos_bfi.csv` **en esa
   misma carpeta**.
3. Agrupa las líneas por número de cuenta y resuelve la tabla Ninox destino.
4. Compara con la tabla destino y avisa de las líneas que **ya existen**.
5. Inserta las líneas nuevas (o simula la inserción).
6. **Relee cada registro creado** y corrige los campos que Ninox haya descartado.
7. Si la inserción fue real y correcta, **borra el CSV**.
8. Informa al usuario de cuántas líneas se insertaron y en qué tablas.

---

## 2. Mapa de negocio: cuenta → tabla Ninox

| `cuenta_no` del CSV | Tabla | Nombre en Ninox |
|---|---|---|
| `0300000005399610` | `OD` | BFI 05399610 |
| `0300000006074740` | `PD` | BFI 06074740 |
| `0300000006102035` | `TD` | BFI 61020 |

Columnas del CSV que se leen y campo Ninox que reciben, **por id de campo** tal
y como los especifica el documento funcional:

| Columna del CSV | `OD` | `PD` | `TD` |
|---|---|---|---|
| `fecha_valor` | `B` Fecha Bancaria | `B` Fecha Bancaria | `B` Fecha Bancaria |
| `referencia` | `R1` Referencia | `P1` Referencia | `S1` Referencia |
| `detalle` | `G1` Detalles | `G1` Detalles | `K1` Detalles |
| `debito` / `credito` | `D` Importe CUP | `D` Importe CUP | `D` Importe USD |
| `saldo` | `O` Saldo inicial | `O` Saldo inicial | `O` Saldo inicial |

Reglas adicionales (apartado 5.2, aplican a las tres tablas):

| Regla | Implementación |
|---|---|
| `debito` informado → Egreso/Ingreso = Sí | `F` = `True` |
| `credito` informado → Egreso/Ingreso = No | `F` = `False` |
| Las dos columnas van al **mismo** campo de importe | `D` = débito si existe, si no crédito |
| Oper. en tránsito = No | `O1` (OD) / `M1` (PD) / `Q1` (TD) = `"No"` |
| Tipo de Cambio en blanco en OD y PD | el campo se **omite** (ver §6) |
| `TD`: `J` = 24 y `C1` = blanco | `J` = `24`, `C1` = `""` |

---

## 3. Instalación para el usuario final

El usuario final **no necesita Python**. Solo recibe un fichero:

```
Instalar BFI Extractor.exe     ← doble clic
```

El instalador hace todo solo:

* cierra la aplicación si estaba abierta (para poder actualizarla),
* copia el programa en `%LOCALAPPDATA%\Programs\BFI Extractor`
  (**no pide permisos de administrador**, igual que Chrome o VS Code),
* crea el acceso directo en el escritorio y en el menú Inicio,
* instala su propio desinstalador,
* detecta si faltan las credenciales de Ninox y **ofrece abrir la aplicación
  justo en la pantalla donde se configuran**.

### Configurar el acceso a Ninox (una sola vez por equipo)

La aplicación necesita tres datos:

| Variable | Contenido |
|---|---|
| `NINOX_API_KEY` | clave de la API de Ninox |
| `NINOX_TEAM_ID` | identificador del equipo |
| `NINOX_DB_ID` | identificador de la base de datos |

Hay dos formas, y **ninguna exige una terminal**:

1. **Desde la aplicación** (recomendado): botón **«Configurar acceso a
   Ninox…»**. Los valores quedan guardados en el perfil de Windows del usuario y
   no hay que volver a escribirlos.
2. **Por adelantado**, en el equipo antes de instalarlo, para que el usuario no
   tenga que hacer nada:
   ```bat
   setx NINOX_API_KEY "tu_clave"
   setx NINOX_TEAM_ID "tu_equipo"
   setx NINOX_DB_ID   "tu_base_de_datos"
   ```

> **Para el administrador:** el reparto más cómodo es configurar las tres
> variables en el equipo de referencia **antes** de clonar la imagen, o
> entregarlas por un canal aparte del instalador (no las metas dentro del
> `.exe`, que acabaría circulando por correo).

---

## 4. Uso diario

El trabajo va **en dos pasos separados**, y esa separación es deliberada: así el
usuario ve lo que hay antes de que nada se escriba en el ERP.

### Paso 1 — Leer (no escribe nada)

1. Doble clic en **BFI Extractor**.
2. **«Elegir carpeta…»** → la carpeta con los PDFs del banco.
   Nada más elegirla, la aplicación **lee los PDFs y rellena la tabla**.
3. La tabla *Contenido detectado* muestra, por tabla: líneas, cuántas son nuevas
   y cuántas **ya existen** en Ninox.

### Paso 2 — Volcar

4. El botón **«Volcar a Ninox»** se habilita cuando el contenido está leído.
   Pulsarlo inserta (o simula) esas líneas.

> Con la carpeta elegida, el botón «Volcar a Ninox» está **deshabilitado** hasta
> que se lee el contenido. Es intencionado: evita que alguien intente volcar una
> carpeta que aún no se ha leído, o la carpeta anterior.

Opciones de la ventana:

| Opción | Por defecto | Para qué |
|---|---|---|
| **Modo simulación** | Activado | Construye y muestra los envíos, pero **no escribe** en Ninox. |
| Omitir las líneas que ya existen | Activado | Evita duplicar al reprocesar un PDF. |
| Comprobar cada registro tras insertarlo | Activado | Relee y verifica lo guardado. |
| Corregir los campos que Ninox descarte | Activado | Reenvía con un `PUT` los campos que el alta dejó con su valor por defecto. |

**El primer volcado real conviene hacerlo con la simulación desactivada pero
sobre pocas líneas**, para que el usuario vea el resultado en el ERP antes de
lanzar un extracto completo.

El botón **«Solo extraer a CSV (sin Ninox)»** genera el CSV y no toca el ERP
(útil sin conexión o para revisar antes). Ese CSV se escribe **en la carpeta
elegida**, junto a los PDFs.

> **Recomendación de organización:** guarda los extractos en una carpeta aparte
> (por ejemplo `Documentos\Extractos BFI`), no junto al programa. Mezclar los
> PDFs con `BFI Extractor.exe` y `_internal` funciona, pero acaba siendo un lío y
> el CSV generado aparece en medio del programa.

---

## 5. Instalación para el desarrollador (compilar)

Requisitos: Python 3.8 o superior y 7-Zip (para empaquetar el instalador).

```bat
build_exe.bat            ::  instala dependencias, genera el icono y compila
crear_instalador.bat     ::  empaqueta todo en un unico .exe
```

Resultado:

```
dist\BFI Extractor\              ← la aplicación compilada
Instalar BFI Extractor.exe       ← esto es lo que se entrega al usuario
```

En desarrollo, sin compilar:

```bat
python main.py                   ::  abre la interfaz grafica
python -m pytest tests/ -q       ::  pruebas (no necesitan red ni credenciales)
```

Línea de comandos, para depurar o programar tareas:

```bat
python main.py extraer  "C:\ruta\a\pdfs"    ::  solo genera el CSV
python main.py simular  "C:\ruta\a\pdfs"    ::  muestra que enviaria a Ninox
python main.py insertar "C:\ruta\a\pdfs" --confirmar
python main.py insertar "C:\ruta\a\pdfs" --confirmar --tabla-test
                                            ::  ensayo: escribe en DF (tabla de
                                                prueba) en vez de en datos reales
```

---

## 6. Detalles que no son evidentes (y por qué están así)

Todo lo que sigue está **verificado contra la base real**, no deducido. Las
trazas están en `docs/VERIFICACION_ESCRITURA.md` y en `tools/`.

* **La API acepta el id de campo** (`R1`, `D`…) y lo traduce al nombre. Aun así
  la aplicación resuelve el mapeo a **nombres** contra los metadatos de la tabla
  destino y **aborta el lote entero** si algún id no existiera. Motivo: escribir
  un nombre de campo inexistente en Ninox devuelve **HTTP 500**, no un 400, y es
  indistinguible de una caída del servidor.

* **`Saldo inicial` (`O`) ignora lo que se envía en el alta.** Se comprobó
  enviando `999.99` y quedándose el registro en `23226.13` (valor por defecto de
  la tabla). Pero un `PUT` posterior **sí** lo guarda. Por eso la aplicación
  relee cada registro y, si procede, reenvía con un `PUT` los campos que el alta
  descartó. Sin este paso, el saldo de cada línea se perdería en silencio.

* **`Secuencial` y `Conciliado` se rellenan solos.** No se envían y no se
  interpretan como datos escritos por la aplicación.

* **El Tipo de Cambio se omite, no se envía vacío, en OD y PD.** El documento
  dice que va «en blanco». El `PUT` de Ninox hace *merge*, así que omitir el
  campo deja intacto lo que ya hubiera; enviarlo vacío lo borraría. En `TD` sí se
  escribe (`J` = 24, `C1` = `""`) porque así lo pide el documento.

* **Una línea con `debito` y `credito` a la vez aborta esa línea.** No hay regla
  de negocio escrita para ese caso y adivinar sería peor que parar.

* **Una cuenta desconocida aborta el proceso entero.** Es preferible a insertar
  en la tabla equivocada.

* **La detección de duplicados usa referencia + fecha + importe.** La fecha y el
  importe entran en la clave porque hay extractos con la misma referencia
  repetida en varias líneas de una misma operación.

* **Los ingresos (`credito`) se escriben con `Egreso/Ingreso = False`.** En el
  extracto de ejemplo hay **3 ingresos de 44 líneas**. La comprobación que los
  cubre no es un recuento a mano: `tools/validar_extraccion.py` reconstruye la
  cadena de saldos de cada cuenta y exige que cada saldo sea el anterior más o
  menos el importe. Si esa cadena encaja en las 41 transiciones, no falta ningún
  movimiento ni hay ningún signo invertido.

* **El CSV se escribe con BOM UTF-8** para que Excel lo abra con los acentos
  correctos, y se borra solo tras un volcado real correcto **y sin errores**: si
  alguna línea falla, el CSV se conserva porque es la única prueba de qué no se
  insertó.

* **La tabla `DF` «BFI 61021 (TEST)» es estructuralmente idéntica a `TD`.** Por
  eso los ensayos se hacen contra ella: allí se validó el circuito completo de 44
  líneas (insertar, verificar, corregir y borrar) sin tocar datos de negocio.

---

## 7. Estructura del proyecto

```
bfi/
  config.py                  cuentas, mapeo de campos, endpoints, tiempos
  extractor.py               parser de los PDFs (pdfplumber) y escritura del CSV
  mapping.py                 CSV -> campos Ninox (puro, con tests)
  ninox_client.py            cliente REST de Ninox (solo biblioteca estandar)
  ninox_writer.py            insercion, verificacion y correccion
  credentials.py             lectura de credenciales (entorno y Registro)
  configuracion_usuario.py   guardado de credenciales desde la ventana
  dialogo_credenciales.py    cuadro de dialogo de acceso a Ninox
  gui.py                     ventana principal (tkinter)
  logging_setup.py           registro a fichero y a la ventana
main.py                      interfaz grafica y linea de comandos
build_exe.bat                compila la aplicacion (desarrollador)
crear_instalador.bat         empaqueta el instalador unico (desarrollador)
instalar.bat                 lo que ejecuta el instalador en el equipo destino
tools/                       sondas de verificacion contra la API (ver docs)
  bfi_extractor_original.py  el extractor de partida, conservado como referencia
tests/                       pruebas de la logica de negocio
docs/VERIFICACION_ESCRITURA.md   que se comprobo contra la base real
```

> **Los `.bat` van en ASCII con finales de línea CRLF**, y no es un capricho: con
> finales LF, `cmd.exe` se comió la primera letra de cada línea y los scripts
> dejaron de funcionar. El `.gitattributes` lo fuerza al clonar. Si editas un
> `.bat`, guárdalo en CRLF.

---

## 8. Registro y diagnóstico

Cada ejecución deja un registro en `logs\bfi_AAAAMMDD.log`, junto al ejecutable.
Si el usuario informa de un problema, **ese fichero es lo primero que hay que
mirar**: contiene cada línea enviada, cada error HTTP y cada corrección.

---

## 9. Requisitos

* Windows 10 o superior (probado en Windows 11).
* Conexión a Internet para el volcado a Ninox (que es un servicio en la nube).
* Credenciales de la API de Ninox con permiso de escritura sobre `OD`, `PD` y
  `TD`.
