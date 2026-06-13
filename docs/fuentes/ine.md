# INE — Estadísticas Vitales de Defunciones
 
## Descripción
 
Las estadísticas vitales resultan de los registros administrativos de nacimientos, defunciones fetales y no fetales, matrimonios y divorcios, que permiten contar con información sobre los cambios en los patrones de mortalidad, fecundidad y nupcialidad, proporcionando una visión dinámica de la población, como complemento al enfoque estático que proveen los censos poblacionales.
 
Estas son ampliamente utilizadas para el cálculo de indicadores demográficos de gran importancia para el sector salud.
 
## Metadatos de la Fuente
 
| Campo | Detalle |
|---|---|
| **Institución** | Instituto Nacional de Estadística — INE Guatemala |
| **Dataset** | Estadísticas Vitales — Defunciones |
| **URL** | [datos.ine.gob.gt](https://datos.ine.gob.gt/dataset/estadisticas-vitales-defunciones) |
| **Formato** | XLSX |
| **Separador** | N/A (formato binario Excel) |
| **Cobertura temporal** | 2018 — 2024 |
| **Cobertura geográfica** | República de Guatemala |
| **Total de registros** | 674,064 |
| **Codificación de causas** | CIE-10 |
| **Servicio de ingesta** | Google Drive |
| **Tabla Sandbox** | `sandbox.sandbox_ine` |
 
## Archivos Disponibles
 
| Archivo | Registros | Observaciones |
|---|---|---|
| defunciones-2018.xlsx | 83,071 | Schema completo |
| defunciones-2019.xlsx | 85,600 | Schema completo |
| defunciones-2020.xlsx | 96,001 | Schema completo |
| defunciones-2021.xlsx | 118,465 | Schema completo |
| defunciones-2022.xlsx | 95,386 | Schema completo |
| defunciones-2023.xlsx | 95,948 | Schema completo |
| defunciones-2024.xlsx | 99,593 | Columnas `Escodif` y `Ciuodif` ausentes |
 
## Columnas y Descripciones
 
| Columna | Descripción |
|---|---|
| `Depreg` | Departamento de registro de la defunción |
| `Mupreg` | Municipio de registro de la defunción |
| `Mesreg` | Mes de registro |
| `Añoreg` | Año de registro |
| `Depocu` | Departamento de ocurrencia de la defunción |
| `Mupocu` | Municipio de ocurrencia de la defunción |
| `Sexo` | Sexo del fallecido (1=Masculino, 2=Femenino) |
| `Diaocu` | Día de ocurrencia de la defunción |
| `Mesocu` | Mes de ocurrencia de la defunción |
| `Añoocu` | Año de ocurrencia de la defunción |
| `Edadif` | Edad del fallecido |
| `Perdif` | Período de la edad (1=Días, 2=Meses, 3=Años) |
| `Puedif` | Pueblo de pertenencia del fallecido |
| `Ecidif` | Estado civil del fallecido |
| `Escodif` | Escolaridad del fallecido |
| `Ciuodif` | Ciudad de ocurrencia del fallecido |
| `Pnadif` | País de nacimiento del fallecido |
| `Dnadif` | Departamento de nacimiento del fallecido |
| `Mnadif` | Municipio de nacimiento del fallecido |
| `Nacdif` | Nacionalidad del fallecido |
| `Predif` | País de residencia del fallecido |
| `Dredif` | Departamento de residencia del fallecido |
| `Mredif` | Municipio de residencia del fallecido |
| `Caudef` | Causa de defunción codificada en CIE-10 |
| `Asist` | Asistencia médica recibida |
| `Ocur` | Lugar de ocurrencia de la defunción |
| `Cerdef` | Certificación de la defunción |