# APLICACION WINDOWS PARA EXTRACCION Y PROCESAMIENTO DE PDFS DEL BFI

## 1.OBJETIVO
La aplicación a desarrollar tiene como objetivo extraer y procesar los PDFs de los estados de cuenta del Banco Financiero, para obtener un archivo CSV con la información de las transacciones. Posteriormente este fichero csv será procesado y las líneas serán insertadas en el ERP Ninox cada una dentro de su tabla correspondiente.

## 2. REQUISITOS
La aplicación a desarrollar será instalada en una laptop del director administrativo de la empresa Julsa Industrial, por tanto en su configuración debe salvaguardarse que funcione en el pc que se instale pudiendo ser instalada en unos o varios dispositivos y funcionará siempre en local. La aplicación debe ser desarrollada en Python 3.8 y debe utilizar las librerías de Python necesarias para el desarrollo de la aplicación.
Es importante por tanto, generar también un archivo que proceda a instalar en cada laptop la aplicación y las librerías necesarias para su funcionamiento y todo esto deberá ser realizado sin intervención del usuario dado que se trata de usuarios de ofimatica sin conocimiento de terminales ni programación.

## 3. FUNCIONAMIENTO
La aplicación se ejecutará en un entorno de escritorio windows/mac y su funcionamiento será el siguiente:
1. El usuario seleccionará el directorio donde se encuentran los PDFs a procesar.
2. La aplicación extraerá la información de los PDFs y generará un fichero CSV con la información de las transacciones.
3. Ya tenemos un fichero python generado que está realizando dicha extracción de manera exitosa. Puedes comprobarlo en esta ruta: "C:\Users\admin\proyectos\Utilidades\Automatizacion_BFI\bfi_extractor.py".
4. Una vez se hayan procesado los pdf´s, deberás guardar el fichero generado en la misma carpeta local que el usuario seleccionó.
5. Una vez se haya generado el fichero csv, se procederá a su procesamiento para insertar las líneas en el ERP Ninox.
6. Para ello, se utilizará un fichero python (u otro que consideres oportuno) que se encargará de realizar la conexión con el ERP Ninox y la inserción de las líneas en las tablas correspondientes.
7. Una vez se haya realizado la inserción de las líneas en el ERP Ninox, se procederá a la eliminación del fichero csv generado en la carpeta local.
8. Una vez el proceso concluya de manera exitosa, se lanzará un mensaje al usuario indicando cuantas lineas se han insertado y en que tablas se han insertado.

## 4. REPOSITORIOS Y PERMISOS
Para el desarrollo de la aplicación se utilizará el repositorio de github: https://github.com/aguillensp-sudo/Automatizacion_BFI.git. Este repositorio está creado pero vacío y en el git local no ha sido creado.
En la siguiente ruta local: "C:\Users\admin\proyectos\Utilidades\Automatizacion_BFI" se encuentra el fichero python que realiza la extracción de los pdf´s así como unos pdfs que se pueden usar de prueba del test de la aplicación.
Las credenciales de acceso a NINOX están cargadas como Variables en el entorno de windows:
- `NINOX_API_KEY`
- `NINOX_TEAM_ID`
- `NINOX_DB_ID`
** En la carpeta "C:\Users\admin\proyectos\Utilidades\Automatizacion JI\docs\ninox" hay documentación importante para no andar a ciegas en Ninox. Revísala antes de hacer nada pues contiene el mapeo de tablas y campos de cada una así como relaciones en la BBDD relacional. **

## 5. MAPEO DEL CSV A NINOX E INSERCION DE REGISTROS

### 5.1. Identificar la Tabla Ninox a tocar

5.1.1 Lee el CSV y en la columna "cuenta_no" identificar el valor que contiene. Este valor se corresponde con el ID de la tabla Ninox a la que se deben insertar los registros:
0300000005399610 --> Id Tabla: OD
0300000006074740 --> Id Tabla: PD
0300000006102035 --> Id Tabla: TD

5.1.2. Una vez identificada la tabla, del csv deberás leer siempre las mismas columnas, desestimando las que no estén en la siguientes tablas:

***Si la tabla es OD:
Columna CSV | Campo Ninox de la tabla identificada
--- | --- 
fecha_valor | `B` 
referencia | `R1`
detalle | `G1`
debito | `D`
credito | `D`
saldo | `O`***

***Si la tabla es PD:
Columna CSV | Campo Ninox de la tabla identificada
--- | --- 
fecha_valor | `B` 
referencia | `P1`
detalle | `G1`
debito | `D`
credito | `D`
saldo | `O`***

***Si la tabla es TD:
Columna CSV | Campo Ninox de la tabla identificada
--- | --- 
fecha_valor | `B` 
referencia | `S1`
detalle | `K1`
debito | `D`
credito | `D`
saldo | `O`***

### 5.2. Reglas para inserción de datos en campos que no están en el CSV. **Aplican a todas las tablas**

WHEN Campo debito con valor informado THEN Campo Ninox "Egreso/Ingreso" = Sí
WHEN Campo credito con valor informado THEN Campo Ninox "Egreso/Ingreso" = No
Campo Ninox Tipo de Cambio = Siempre en blanco para las Tablas OD y PD. Para la tabla TD hay dos campos a escribir:
    `J`: Valor numérico = 24 (harcodeado)
    `C1`: Valor en blanco
Campo Ninox Oper. en tránsito = No


