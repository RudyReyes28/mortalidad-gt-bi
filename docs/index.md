# Plataforma Analítica de Mortalidad GT

Documentación de la **Fase 1: Extracción y Carga a Sandbox** del proyecto de análisis de mortalidad Pre/Post COVID-19 en Guatemala.

Este sitio centraliza toda la información técnica, arquitectónica y operativa del pipeline de datos construido para consolidar registros históricos de mortalidad provenientes de múltiples fuentes heterogéneas.

---

## Objetivo de la Fase 1

El propósito principal de esta fase es la **ingesta de datos crudos**. El sistema está diseñado para conectarse a las distintas fuentes oficiales (INE, MSPAS, OMS, INEC), extraer los registros originales sin aplicar transformaciones destructivas, y centralizarlos en un entorno relacional seguro (PostgreSQL Sandbox). 

Esto garantiza una base de datos inmutable y auditable para la posterior fase de transformación y análisis.

## Estructura de la Documentación

Navega por el menú lateral para explorar los detalles técnicos del proyecto:

* **Fuentes de Datos:** Contexto, metadatos y diccionarios de las fuentes originales.
* **Pipeline:** Detalles de la arquitectura ETL, diagramas de despliegue y documentación de los extractores generada automáticamente desde el código fuente en Python.
* **Trazabilidad:** Reglas de Data Lineage y bitácoras de ejecución.
* **Diccionario de Datos:** Estructura final de las tablas dentro del esquema Sandbox.
* **Gobernanza:** Políticas de manejo de datos y cumplimiento de privacidad.

---

## Equipo de Desarrollo

Este proyecto fue desarrollado por el **Grupo 6** del curso de **Seminario de Sistemas 2**:

| Carné / CUI | Nombre Completo |
|:---:|---|
| **3150529020901** | William Alexander Miranda Santos |
| **3249400331332** | Elier Rigoberto Gómez Figueroa |
| **2958915561001** | Rudy Alessandro Reyes Oxláj |

