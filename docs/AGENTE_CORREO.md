# Agente de correo BFI

Revisa **una carpeta del Outlook de este equipo**, descarga los adjuntos PDF de
los estados de cuenta, los procesa con el mismo pipeline que usa la aplicación
de escritorio (`bfi.extractor` → `bfi.mapping` → `bfi.ninox_writer`) y envía un
correo de resumen con lo que ha pasado.

Está pensado para ejecutarse **solo los lunes**, desde el Programador de tareas
de Windows.

---

## 1. Por qué COM y no Microsoft Graph

La vía «moderna» sería Microsoft Graph con permisos de aplicación, y es la que
está descartada por una razón que no se puede rodear:

* La suscripción de Microsoft es **personal**, así que **no hay inquilino de
  Entra ID** donde registrar una aplicación (el error «la cuenta no existe en el
  inquilino *Microsoft Services*» es exactamente eso), y una cuenta personal
  **no admite consentimiento de administrador**.
* El plan B clásico, IMAP/SMTP, tampoco: Microsoft **desactivó la autenticación
  básica en las cuentas personales** (septiembre de 2024), y OAuth2 para IMAP
  exigiría justamente el registro de aplicación que no se puede hacer.

COM sobre el Outlook de escritorio no necesita nada de eso: usa la sesión de
correo que el equipo ya tiene abierta.

> Si algún día el buzón pasa a un Microsoft 365 Business (inquilino propio, con
> administrador), se puede añadir una `fuente_graph.py` que cumpla la misma
> interfaz `FuenteCorreos` y **nada más del sistema cambia**.

---

## 2. Puesta en marcha

```bat
:: 1. Dependencia (una sola)
pip install pywin32

:: 2. Configuracion
copy agente_correo.ejemplo.json agente_correo.json
notepad agente_correo.json

:: 3. Averiguar como se llama de verdad la carpeta que hay que vigilar
python -m bfi_agente --listar-carpetas

:: 4. Comprobar que todo esta en su sitio (Outlook, carpeta, Ninox, permisos)
python -m bfi_agente --comprobar

:: 5. Ensayo general, sin escribir nada en Ninox
python -m bfi_agente --dry-run
```

El paso 3 es el que se salta todo el mundo y el que más tiempo ahorra: los
nombres reales de las carpetas de Outlook no siempre son los que uno recuerda.

### Ensayo con correos de ejemplo, sin tocar el buzón

Se puede probar el pipeline completo sin Outlook y sin correo real: cada
subcarpeta de la carpeta indicada es un correo, y los ficheros que contiene son
sus adjuntos. `asunto.txt` y `remitente.txt` (opcionales) describen el mensaje.

```
pruebas/correos_bfi/
    01_extractos/
        asunto.txt          <- "Estado de cuenta BFI - septiembre 2026"
        remitente.txt       <- "avisos@bancofinanciero.cu"
        estado_053996-522.pdf
    02_ruido/
        remitente.txt       <- "otro@ejemplo.com"
        notas.txt           <- no es PDF: se ignora
```

```bat
python -m bfi_agente --dry-run --simulado pruebas\correos_bfi
```

Esta carpeta **no se versiona** (contiene extractos reales): está en
`.gitignore`.

### Probar contra una base de datos de pruebas, sin tocar la de producción

El agente lee el identificador de la base de Ninox de la variable de entorno
`NINOX_DB_ID`. Para una prueba, se cambia **solo en ese proceso**: no hace falta
tocar la configuración del usuario.

```bat
:: 1. Averiguar el identificador de la base de pruebas
python tools\listar_bases_ninox.py pruebas

:: 2. Comprobar que esa base tiene las tablas OD, PD y TD
python tools\comprobar_tablas_ninox.py <id-de-la-base> "JI-PRUEBAS-CLAUDE"

:: 3. Ensayo contra el buzon real, sin escribir nada
set NINOX_DB_ID=<id-de-la-base>
python -m bfi_agente --config agente_correo.prueba.json --dry-run --desde 2020-01-01

:: 4. Insercion real en la base de pruebas, sin tocar los correos
python -m bfi_agente --config agente_correo.prueba.json --real --no-marcar --desde 2020-01-01
```

Cuatro detalles que hacen que la prueba no ensucie nada:

* `agente_correo.prueba.json` usa un **fichero de estado aparte**
  (`logs/agente_bfi_prueba.sqlite3`), así que la ejecución real de los lunes no
  se ve afectada por lo que se haya probado.
* `--no-marcar` deja los correos **intactos**: ni categoría, ni leído, ni
  movimiento de carpeta. El estado sí se registra, así que una segunda pasada no
  los vuelve a insertar.
* `--desde 2020-01-01` amplía la ventana para coger correos antiguos que sigan
  en la carpeta.
* La base de producción no se toca en ningún momento; para comprobarlo,
  `bfi_agente/../tools/comprobar_tablas_ninox.py` sin argumentos apunta a la base
  configurada.

> Orden recomendada: **primero siempre `--dry-run`**. Ahí se ve cuántos
> movimientos hay, a qué tabla van y cuántos son duplicados, sin escribir nada.


---

## 3. Configuración (`agente_correo.json`)

| Campo | Para qué sirve |
|---|---|
| `carpeta_outlook` | Carpeta a vigilar, como `Buzón/Subcarpeta`. Se admite `Bandeja de entrada/...`. |
| `carpeta_procesados` | A dónde se mueve el correo ya procesado. **Vacío = no se mueve**, solo se le pone la categoría. |
| `categoria_procesada` | Categoría de Outlook que se aplica al correo procesado. |
| `remitentes_permitidos` | Direcciones o dominios (`@bancofinanciero.cu`) de los que se aceptan correos. **Vacío = cualquiera**: funciona, pero es lo primero que conviene restringir, porque por aquí entran datos bancarios. |
| `patron_adjunto` | Expresión regular del nombre del adjunto. Por defecto, cualquier `.pdf`. |
| `patron_asunto` | Expresión regular sobre el asunto. Vacío = cualquiera. |
| `dias_atras` | Cuántos días hacia atrás se revisan (8 por defecto: la semana más un día de margen). |
| `max_correos` | Tope de correos por ejecución. 0 = sin tope. |
| `evitar_adjuntos_repetidos` | Si el mismo PDF (mismo contenido) ya se procesó, se ignora aunque venga en otro correo. |
| `carpeta_trabajo` | Aquí van los PDFs descargados, los CSV y los informes. Se conserva todo: es la prueba de lo que se hizo. |
| `ruta_estado` | Base SQLite con lo ya procesado. **Borrar este fichero hace que el agente lo reprocese todo.** |
| `resumen_activo` | Si se envía el correo de resumen. |
| `resumen_para` | Destinatarios del resumen. |
| `resumen_solo_simular` | Deja preparado el envío pero no llega a enviarlo nunca. |
| `responder_al_remitente` | Si el agente **contesta al correo original** cuando lo ha procesado bien. |
| `texto_respuesta` | El texto de esa respuesta. Por defecto: `Los registros han sido insertados en Ninox`. |

> **`responder_al_remitente` escribe a terceros.** Es la única parte del agente
> que sale del equipo hacia fuera, así que viene **desactivada** por defecto y las
> pruebas deben dejarla en `false`. Con `--no-marcar` tampoco se responde: ese
> modificador deja el buzón intacto en todos los sentidos. Antes de activarla en
> producción, `tools/probar_respuesta_outlook.py` comprueba que Outlook puede
> preparar la respuesta (y la descarta sin enviarla).

Las claves desconocidas (una errata, por ejemplo `remitentes_permitdo`) **hacen
fallar el arranque** a propósito: en un proceso desatendido que corre los lunes,
una errata silenciosa es peor que un error.

---

## 4. Qué hace exactamente cada lunes

El trabajo va en **tres fases**, y el orden es lo que garantiza que los saldos no
se descuadren:

1. Calcula la ventana de revisión: desde `hoy - dias_atras`.
2. Pide a Outlook los correos de la carpeta, **del más nuevo al más antiguo**, y
   se detiene al salir de la ventana.
3. Aplica el filtro: asunto, remitente y adjuntos que interesan.
4. **Fase 1 — preparación, correo a correo.** Descarta los correos cuyo `EntryID`
   (o `InternetMessageID`) ya esté en el estado y los adjuntos cuyo contenido ya
   se procesara antes; copia los adjuntos a
   `logs/trabajo/<fecha_hora>/<asunto>/` y genera `movimientos_bfi.csv` ahí.
5. **Fase 2 — un único envío para todo el lote.** Junta las líneas de **todos**
   los correos, las agrupa por tabla y las ordena por `fecha_valor` de la más
   antigua a la más reciente antes de insertar. Comprueba duplicados contra
   Ninox una sola vez e inserta.
6. **Fase 3 — cierre, correo a correo.** Registra el estado, responde al
   remitente (si está configurado) y marca el correo: categoría, como leído y, si
   procede, movimiento a la carpeta de procesados.
7. Escribe el informe en `logs/trabajo/resumen_<fecha>.txt` y, si está activado,
   lo envía por correo.

### Por qué el envío es un único lote (fallo detectado el 24/09/2026)

La fórmula de Ninox que calcula **Saldo inicial** encadena cada registro con el
**anterior por Secuencial**, es decir, con el último que se insertó. Insertando
correo a correo, si un correo trae movimientos del día 18 y otro trae uno del día
15, el del 15 acaba **al final de la cadena** y todos los saldos posteriores
quedan descuadrados: la cadena es coherente consigo misma, pero ya no sigue el
orden cronológico real.

Por eso el envío es único y ordenado. En la prueba contra `JI-PRUEBAS-CLAUDE` se
vio el fallo (los tres movimientos del 18 entraron antes que el del 15) y, tras la
corrección, el orden de inserción quedó
`07/09 → 15/09 → 18/09 → 18/09 → 18/09` con la cadena de saldos cuadrando.

Como contrapartida, al ir todo en un lote hay que descartar también las líneas
repetidas **dentro del propio lote** (dos PDFs distintos con el mismo movimiento),
cosa que `marcar_duplicados` no hacía porque solo compara con lo que ya hay en
Ninox: de eso se encarga `procesador.marcar_repetidas_del_lote`.

### Reglas de la casa

| Situación | Qué hace | Por qué |
|---|---|---|
| Un correo falla | Se anota y **se sigue con el siguiente** | Un PDF raro no debe impedir procesar el resto |
| Un PDF no produce ninguna línea | Se trata como **error**, no como «sin movimientos» | Casi siempre significa que el formato del extracto cambió |
| Hubo errores al insertar | Ese correo **no se marca ni se registra**: se reintenta el lunes siguiente | Reenviar es barato (Ninox descarta duplicados); perder movimientos, no |
| No hay credenciales de Ninox | Se extrae y se dejan los CSV, pero **nada se da por procesado** | Si no se envió, no puede darse por hecho: se reintenta |
| El mismo PDF llega dos veces | Se ignora el segundo | Ya está en el ERP |
| Dos PDFs distintos traen la misma línea | La segunda se descarta dentro del lote | Evita duplicar el mismo movimiento |
| `--dry-run` | No escribe en Ninox, no responde, no mueve ni marca correos y **no registra estado** | Una prueba no debe condicionar la ejecución real |
| `--no-marcar` | Procesa e inserta de verdad, pero deja el buzón intacto: ni categoría, ni leído, ni movimiento, ni respuesta | Permite una prueba real sin efectos sobre el correo |

> `--dry-run` **sí lee** de Ninox (necesita comparar para detectar duplicados),
> pero no escribe nada. Sin credenciales de Ninox, el agente extrae los PDFs,
> deja los CSV y avisa de que se ha omitido el envío.

---

## 5. Programar los lunes

```bat
programar_agente.bat
```

Crea (o reemplaza) una tarea semanal llamada `BFI Agente de correo` para los
**lunes a las 11:00**. El modo está en `ejecutar_agente.cmd`: hoy `--real`
(inserta en Ninox y responde al remitente). Ponlo en `--dry-run` para una pasada
de comprobación, o ejecútalo a mano con otro modo:

```bat
ejecutar_agente.cmd --dry-run
```

Si `schtasks` se queja (algunos equipos tienen el Programador de tareas
restringido por política), la tarea se puede crear desde PowerShell:

```powershell
$raiz = "C:\ruta\al\proyecto"
Register-ScheduledTask -TaskName "BFI Agente de correo" `
  -Action (New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
            -Argument "/c `"$raiz\ejecutar_agente.cmd`"") `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "11:00") `
  -Principal (New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive) -Force
```

`-LogonType Interactive` es el equivalente a `/IT`: «ejecutar solo cuando el
usuario haya iniciado sesión». **No se puede usar `-LogonType S4U` ni
`Password`**, por lo que se explica abajo.

### La limitación que hay que entender antes de programar nada

**Outlook por COM necesita una sesión interactiva de Windows con el perfil de
correo abierto.** Por eso la tarea se crea con `/IT` («ejecutar solo cuando el
usuario haya iniciado sesión») y no como SYSTEM o con «ejecutar tanto si el
usuario inició sesión como si no»: en esos modos **no funciona**, aunque el
comando sea correcto.

Consecuencias prácticas:

* El equipo debe tener la sesión iniciada los lunes a las 11:00 (login
  automático si nadie lo enciende a mano, y que la máquina no se suspenda).
* Si aparece un diálogo de Outlook pidiendo credenciales o confirmación para
  enviar, la ejecución se queda esperando y el resumen no llega: eso es la señal
  de alarma (mira el apartado de diagnóstico). El envío de la respuesta al
  remitente es la operación con más probabilidad de disparar ese aviso.
* La «nueva» aplicación de Outlook (la de la Store) **no expone COM**. Hay que
  usar el Outlook clásico (`OUTLOOK.EXE`).

Comprobar la tarea:

```bat
schtasks /query /tn "BFI Agente de correo" /v /fo LIST
schtasks /run   /tn "BFI Agente de correo"     :: ejecutarla ahora mismo
schtasks /delete /tn "BFI Agente de correo" /f :: quitarla
```

---

## 6. Diagnóstico

Códigos de salida de `python -m bfi_agente`:

| Código | Significado |
|---|---|
| 0 | Todo correcto |
| 1 | Terminó, pero con incidencias (mira el informe) |
| 2 | No se pudo completar (configuración, Outlook o carpeta) |

Dónde mirar:

* `logs/bfi_agente_AAAAMMDD.log` — traza completa de la ejecución.
* `logs/trabajo/resumen_AAAAMMDD_HHMM.txt` — informe de cada pasada.
* `logs/trabajo/<fecha>/<asunto>/` — PDFs descargados y CSV generado.
* `logs/agente_bfi.sqlite3` — qué correos y adjuntos ya están procesados
  (tablas `correos`, `adjuntos` y `ejecuciones`).

| Síntoma | Causa habitual |
|---|---|
| «No existe la carpeta X» | El nombre no coincide: usa `--listar-carpetas` y copia el nombre exacto |
| «No se pudo abrir Outlook por COM» | Outlook clásico no está instalado, o no hay perfil abierto en esa sesión |
| «faltan las credenciales» | `NINOX_API_KEY` / `NINOX_TEAM_ID` / `NINOX_DB_ID` sin definir para ese usuario |
| No llega el resumen | `resumen_activo` en false, o el envío falló (queda anotado en el informe) |
| El lunes no pasa nada | La tarea no se ejecutó: revisa que la sesión estuviera iniciada |
| «no se pudo responder al remitente» | Outlook no dejó crear o enviar la respuesta: pruébalo con `tools/probar_respuesta_outlook.py` |
| Los saldos salen mal en Ninox | Se insertó algo a mano o desde la app de escritorio entre medias: el orden de la cadena es global por tabla |

---

## 7. Pruebas

```bat
python -m pytest tests/test_agente_correo.py -q
```

No necesitan Outlook, ni red, ni credenciales: usan una fuente de correo
simulada y un procesador de mentira.

> En entornos donde la carpeta temporal del sistema está restringida, el plugin
> `tmpdir` de pytest no puede crear su carpeta base. Las pruebas de este módulo
> **no usan `tmp_path`** por ese motivo: crean su carpeta bajo `tests/_tmp/`.
> Si el conjunto completo falla al recolectar `test_gui.py` con un
> `PermissionError` sobre `.pytest_cache`, borra esa carpeta y vuelve a probar.

---

## 8. Mapa del código

```
bfi_agente/
    cli.py                    linea de comandos (--dry-run, --real, --no-marcar...)
    config.py                 lectura y validacion de agente_correo.json
    pipeline.py               orquesta una pasada completa
    procesador.py             puente con bfi.extractor / bfi.mapping / bfi.ninox_writer
    estado.py                 SQLite: correos y adjuntos ya procesados
    resumen.py                informe de la pasada y envio del correo de resumen
    correo/
        modelo.py             MensajeCorreo, Adjunto, FiltroMensajes
        fuente.py             interfaz FuenteCorreos (COM hoy, Graph manana)
        fuente_outlook_com.py implementacion sobre Outlook clasico
        fuente_simulada.py    correos de mentira, para pruebas y ensayos
tools/
    listar_bases_ninox.py     lista las bases del equipo (para encontrar una de pruebas)
    comprobar_tablas_ninox.py valida OD/PD/TD en una base concreta
    probar_respuesta_outlook.py  prepara una respuesta y la descarta (no envia nada)
programar_agente.bat          registra la tarea semanal del lunes
ejecutar_agente.cmd           lo que ejecuta esa tarea
agente_correo.json            configuracion real
agente_correo.prueba.json     configuracion de pruebas (estado aparte)
agente_correo.ejemplo.json    plantilla
```
