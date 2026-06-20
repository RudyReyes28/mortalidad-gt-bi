import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mspas_covid -> dw.fact_mortalidad_covid_gt
Grano: día / municipio (MSPAS COVID Guatemala)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
Causa fija: U071 (COVID-19 identificado)
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact, destino):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_covid_gt (
                id_fact         BIGSERIAL PRIMARY KEY,
                id_tiempo       INTEGER REFERENCES dw.dim_tiempo(id_tiempo) ON DELETE CASCADE,
                id_geografia    INTEGER REFERENCES dw.dim_geografia_gt(id_geografia) ON DELETE CASCADE,
                id_causa        INTEGER REFERENCES dw.dim_causa_cie10(id_causa) ON DELETE CASCADE,
                id_fuente       INTEGER REFERENCES dw.dim_fuente(id_fuente) ON DELETE CASCADE,
                fallecidos      BIGINT,
                tasa_por_100k   NUMERIC(10,4),
                periodo         VARCHAR(20),
                fecha_carga     VARCHAR(30)
            )
        """))
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_mortalidad_covid_gt RESTART IDENTITY"))
    print_log(f"  [{destino}] Tabla dw.fact_mortalidad_covid_gt truncada.")
    df_fact.to_sql(
        name="fact_mortalidad_covid_gt",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_mortalidad_covid_gt.")
    engine_dw.dispose()


def load_fact_mortalidad_covid_gt(sandbox_url, dw_local_url, dw_cloud_url=None):
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    print_log("Leyendo stage.stage_mspas_covid...")
    df = pd.read_sql("SELECT * FROM stage.stage_mspas_covid", engine_sandbox)
    print_log(f"  -> {len(df):,} filas.")

    dim_tiempo = pd.read_sql("SELECT * FROM dw.dim_tiempo",       engine_dw_local)
    dim_geo    = pd.read_sql("SELECT * FROM dw.dim_geografia_gt", engine_dw_local)
    dim_causa  = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",  engine_dw_local)
    dim_fuente = pd.read_sql("SELECT * FROM dw.dim_fuente",       engine_dw_local)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").astype("Int16")
    df = df.merge(dim_tiempo[["id_tiempo","anio","mes"]], on=["anio","mes"], how="left")
    df = df.merge(dim_geo[["id_geografia","nombre_departamento","nombre_municipio"]],
                  left_on=["departamento","municipio"],
                  right_on=["nombre_departamento","nombre_municipio"], how="left")

    id_u071 = int(dim_causa[dim_causa["codigo_cie10"]=="U071"]["id_causa"].iloc[0])
    df["id_causa"]  = id_u071
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"]=="MSPAS_COVID"]["id_fuente"].iloc[0])

    df_fact = pd.DataFrame({
        "id_tiempo":    df["id_tiempo"],
        "id_geografia": df["id_geografia"],
        "id_causa":     df["id_causa"],
        "id_fuente":    df["id_fuente"],
        "fallecidos":   pd.to_numeric(df["fallecidos"], errors="coerce").fillna(0).astype(int),
        "tasa_por_100k":df.get("tasa_por_100k", None),
        "periodo":      df["periodo"],
        "fecha_carga":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    print_log(f"Cargando {len(df_fact):,} registros...")
    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")
    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — omitiendo nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — fact_mortalidad_covid_gt")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_mortalidad_covid_gt")
    print_log("=" * 60)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): env_path = Path(".env")
    load_dotenv(env_path)
    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")
    load_fact_mortalidad_covid_gt(sandbox_url, dw_local_url, dw_cloud_url)