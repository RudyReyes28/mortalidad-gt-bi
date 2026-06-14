# Pipeline de Ingesta

## Descripción general

El pipeline de ingesta es el primer eslabón de la plataforma analítica. Su responsabilidad es conectarse a cada fuente heterogénea, extraer los datos en su estado original y cargarlos al Sandbox de PostgreSQL sin transformaciones destructivas.

El pipeline está implementado en Python y se orquesta desde `main.py`, que ejecuta cada extractor en secuencia y reporta el resultado de la ejecución.

## Arquitectura del pipeline

```
main.py  (orquestador)
    ├── extract_gdrive.py                       -> Google Drive    -> sandbox_ine
    ├── extract_world_mortality_s3.py           -> AWS S3          -> sandbox_centroamerica
    ├── extract_centroamerica_rds.py            -> RDS PostgreSQL  -> sandbox_mspas_covid
    ├── extract_mspas_mec.py                    -> Google Drive    -> sandbox_mspas_mec
    ├── extract_mspas_covid.py                  -> Google Drive    -> sandbox_mspas_covid
    └── extract_sharepoint.py -> SharePoint     -> sandbox_oms     -> sandbox_oms
                |
         load_sandbox.py
                |
    sandbox.* (PostgreSQL RDS)
```

## Cómo ejecutar el pipeline

=== "Todas las fuentes"

    Ejecuta todos los extractores activos en secuencia:

    ```bash
    # Activar entorno virtual
    source .venv/bin/activate

    # Correr pipeline completo
    python ingesta-fase1/main.py
    ```

=== "Una fuente específica"

    Útil para pruebas o para recargar solo una fuente:

    ```bash
    # Solo INE
    python ingesta-fase1/main.py --fuente ine

    # Solo Centroamérica
    python ingesta-fase1/main.py --fuente centroamerica

    # Solo fuente DB
    python ingesta-fase1/main.py --fuente fuente_db
    ```

=== "Desde GitHub Actions"

    Ir al repositorio -> pestaña **Actions** -> **Pipeline de Ingesta - Fase 1** -> **Run workflow**:

    - **Fuente**: escribir el nombre de la fuente o dejar vacío para todas
    - **Ambiente**: seleccionar `produccion`

    El pipeline corre en la EC2 y los logs aparecen en tiempo real en GitHub Actions.

---

## Loader - load_sandbox.py

Recibe el DataFrame de cualquier extractor y lo carga a la tabla Sandbox correspondiente.

**Estrategia anti-duplicados:** `if_exists='replace'` — cada ejecución trunca y recarga la tabla completa. Garantiza cero duplicados sin importar cuántas veces se ejecute el pipeline.

```python
# Firma de la función principal
load_sandbox(
    df      : pd.DataFrame,   # DataFrame del extractor
    fuente  : str,            # 'ine' | 'centroamerica' | 'oms' | 'fuente_db'
    db_url  : str,            # SANDBOX_DB_URL del .env
) -> dict                     # reporte de la ejecución
```

**Tablas que crea automáticamente:**

| Fuente | Tabla en Sandbox |
|---|---|
| `ine` | `sandbox.sandbox_ine` |
| `centroamerica` | `sandbox.sandbox_centroamerica` |
| `oms` | `sandbox.sandbox_oms` |
| `world mortality` | `sandbox.world_mortality` |
| `mspas_mec` | `sandbox.sandbox_mspas_mec` |
| `mspas_covid` | `sandbox.sandbox_mspas_covid`

---

## Reporte de ejecución

Cada corrida del pipeline genera un archivo JSON en `ingesta-fase1/reportes/`:

```json
{
  "execution_id": "2026-06-09 19:14:10",
  "fuentes": {
    "ine": {
      "filas_cargadas": 674064,
      "tabla": "sandbox.sandbox_ine",
      "duracion_seg": 142.3,
      "status": "SUCCESS"
    }
  },
  "resumen": {
    "exitosas": 1,
    "con_error": 0,
    "total_filas": 674064,
    "duracion_seg": 142.3
  }
}
```

Este archivo forma parte del **data lineage** — evidencia de cada ejecución del pipeline.

---

## Orquestador Principal (main.py)

El archivo `main.py` actúa como el **cerebro de la Fase 1**. Se encarga de leer el entorno, validar credenciales, instanciar los extractores, y asegurar que el ciclo ETL completo llegue hasta su guardado final. Adicionalmente, cuenta con una interfaz de línea de comandos (CLI) administrada por `argparse` para flexibilizar la ejecución manual o automatizada.

::: main
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []