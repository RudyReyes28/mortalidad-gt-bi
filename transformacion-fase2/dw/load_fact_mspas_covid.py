import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Script de carga de hechos: stage_mspas_covid -> dw.fact_defunciones
(load_fact_mspas_covid.py)

Carga dual: DW local (DW_DB_URL) y DW nube (DW_CLOUD_URL) opcional.
IMPORTANTE: Ejecutar create_dimensions.py antes de este script.

Consideraciones:
  - Causa fija: U071 (COVID-19 identificado)
  - Sexo fijo: No especificado (id=3)
  - Grupo etario fijo: No especificado (id=8)
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact: pd.DataFrame, destino: str):
    """Crea la tabla si no existe y carga df_fact en dw.fact_defunciones."""
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_defunciones (
                id_defuncion    BIGSERIAL PRIMARY KEY,
                id_tiempo       INTEGER,
                id_geografia    INTEGER,
                id_causa        INTEGER,
                id_sexo         INTEGER,
                id_grupo_etario INTEGER,
                id_fuente       INTEGER,
                total_casos     BIGINT,
                periodo         VARCHAR(20),
                fecha_carga     VARCHAR(30)
            )
        """))
    df_fact.to_sql(
        name="fact_defunciones",
        con=engine_dw,
        schema="dw",
        if_exists="append",
        index=False,
        chunksize=2000,
        method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros cargados en dw.fact_defunciones.")
    engine_dw.dispose()


def load_fact_mspas_covid(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    # 1. Leer Stage
    print_log("Leyendo stage.stage_mspas_covid...")
    df = pd.read_sql("SELECT * FROM stage.stage_mspas_covid", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leidas.")

    # 2. Cargar dimensiones desde DW local como lookup
    print_log("Cargando dimensiones para lookup...")
    dim_tiempo    = pd.read_sql("SELECT * FROM dw.dim_tiempo",      engine_dw_local)
    dim_geografia = pd.read_sql("SELECT * FROM dw.dim_geografia",   engine_dw_local)
    dim_causa     = pd.read_sql("SELECT * FROM dw.dim_causa_cie10", engine_dw_local)
    dim_fuente    = pd.read_sql("SELECT * FROM dw.dim_fuente",      engine_dw_local)

    # 3. Resolver id_tiempo (mensual)
    print_log("Resolviendo id_tiempo...")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").astype("Int16")
    dim_t = dim_tiempo[["id_tiempo", "anio", "mes"]].copy()
    df = df.merge(dim_t, on=["anio", "mes"], how="left")

    # 4. Resolver id_geografia
    print_log("Resolviendo id_geografia...")
    dim_geo = dim_geografia[["id_geografia", "departamento", "municipio"]].copy()
    df = df.merge(dim_geo, on=["departamento", "municipio"], how="left")

    # 5. Causa fija: U071 — COVID-19 identificado
    print_log("Asignando causa fija U071 (COVID-19 identificado)...")
    id_causa_covid = int(dim_causa[dim_causa["codigo_cie10"] == "U071"]["id_causa"].iloc[0])
    df["id_causa"] = id_causa_covid

    # 6. Sexo fijo: No especificado = 3
    df["id_sexo"] = 3

    # 7. Grupo etario fijo: No especificado = 8
    df["id_grupo_etario"] = 8

    # 8. id_fuente: MSPAS_COVID = 3
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"] == "MSPAS_COVID"]["id_fuente"].iloc[0])

    # 9. Construir fact
    print_log("Ensamblando fact_defunciones...")
    df_fact = pd.DataFrame({
        "id_tiempo":        df["id_tiempo"],
        "id_geografia":     df["id_geografia"],
        "id_causa":         df["id_causa"],
        "id_sexo":          df["id_sexo"],
        "id_grupo_etario":  df["id_grupo_etario"],
        "id_fuente":        df["id_fuente"],
        "total_casos":      pd.to_numeric(df["fallecidos"], errors="coerce").fillna(0).astype(int),
        "periodo":          df["periodo"],
        "fecha_carga":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    nulos = df_fact[["id_tiempo", "id_geografia"]].isna().sum()
    print_log(f"  Nulos en claves FK: {nulos.to_dict()}")

    # 10. Cargar a DW local y DW nube
    print_log(f"Cargando {len(df_fact):,} registros a dw.fact_defunciones...")
    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")

    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — se omite carga en nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — MSPAS COVID -> fact_defunciones")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_mspas_covid")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")

    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")

    load_fact_mspas_covid(sandbox_url, dw_local_url, dw_cloud_url)