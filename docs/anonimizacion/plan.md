# Gobernanza Inicial y Ética

## Plan de Anonimización y Agregación (Alineación EU Data Act)

El diseño arquitectónico de la Plataforma Analítica de Mortalidad garantiza el cumplimiento ético y la protección de datos personales mediante la implementación del principio de **Privacidad por Diseño (Privacy by Design)**. 

En lugar de aplicar transformaciones destructivas de anonimización en la capa de ingesta, el pipeline delega esta responsabilidad a la capa de origen, garantizando que ninguna Información Personal Identificable (PII) ingrese a la base de datos del Sandbox.

### 1. Naturaleza Agregada de los Datos
El sistema está diseñado para ingerir exclusivamente datos de carácter estadístico y epidemiológico. Las fuentes conectadas al pipeline (INE, MSPAS, OMS, INEC) publican la información bajo un esquema de agregación previa. 

Los niveles de granularidad máxima que maneja el sistema son:
* **Dimensión Geográfica:** Agregación a nivel de municipio o departamento.
* **Dimensión Temporal:** Agregación diaria, semanal, mensual o anual.
* **Dimensión Demográfica:** Agrupación por rangos etarios y sexo.

Al no existir registros nominales (nombres, documentos de identificación o direcciones exactas), el riesgo de re-identificación de un individuo es nulo.

### 2. Cumplimiento de Estándares Internacionales
Bajo los lineamientos de normativas internacionales de protección de datos (tales como el EU Data Act y el GDPR europeo), el tratamiento de información de salud requiere que los datos sean irreversibles hacia el sujeto original. 

La plataforma cumple con este estándar al trabajar sobre "microdatos anonimizados" y estadísticas consolidadas. Esto permite que el equipo de investigación realice cruces analíticos (por ejemplo, evaluar el impacto del COVID-19 frente a enfermedades crónicas) sin comprometer el secreto estadístico ni la confidencialidad del paciente.

### 3. Gobernanza de la Capa Sandbox
Dado que los datos ya son anónimos, la política de gobernanza en la Fase 1 (Ingesta) prohíbe estrictamente la alteración u ofuscamiento de las métricas durante la carga a PostgreSQL. El Sandbox actúa como una bóveda inmutable de la verdad pública, asegurando que las cifras extraídas coincidan exactamente con las cifras reportadas por los gobiernos e instituciones de salud.