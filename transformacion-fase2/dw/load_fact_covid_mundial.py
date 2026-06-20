import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_covid_mundial -> dw.fact_covid_mundial
Grano: mes / país (OMS COVID Mundial)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
Usa dim_geografia_mundial con ISO2 para el mapeo
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact, destino):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_covid_mundial (
                id_fact              BIGSERIAL PRIMARY KEY,
                id_tiempo            INTEGER REFERENCES dw.dim_tiempo(id_tiempo) ON DELETE CASCADE,
                id_geografia_mundial INTEGER REFERENCES dw.dim_geografia_mundial(id_geografia_mundial) ON DELETE CASCADE,
                id_fuente            INTEGER REFERENCES dw.dim_fuente(id_fuente) ON DELETE CASCADE,
                new_cases_mes        BIGINT,
                new_deaths_mes       BIGINT,
                cum_cases_fin        BIGINT,
                cum_deaths_fin       BIGINT,
                semanas_reporte      INTEGER,
                periodo              VARCHAR(20),
                fecha_carga          VARCHAR(30)
            )
        """))
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_covid_mundial RESTART IDENTITY"))
    print_log(f"  [{destino}] Tabla dw.fact_covid_mundial truncada.")
    df_fact.to_sql(
        name="fact_covid_mundial",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_covid_mundial.")
    engine_dw.dispose()


def load_fact_covid_mundial(sandbox_url, dw_local_url, dw_cloud_url=None):
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    print_log("Leyendo stage.stage_covid_mundial...")
    df = pd.read_sql("SELECT * FROM stage.stage_covid_mundial", engine_sandbox)
    print_log(f"  -> {len(df):,} filas.")

    dim_tiempo = pd.read_sql("SELECT * FROM dw.dim_tiempo",            engine_dw_local)
    dim_geo    = pd.read_sql("SELECT * FROM dw.dim_geografia_mundial", engine_dw_local)
    dim_fuente = pd.read_sql("SELECT * FROM dw.dim_fuente",            engine_dw_local)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").astype("Int16")
    dim_t = dim_tiempo[dim_tiempo["mes"].notna()][["id_tiempo","anio","mes"]].copy()
    dim_t["mes"] = dim_t["mes"].astype("Int16")
    df = df.merge(dim_t, on=["anio","mes"], how="left")

    # Mapear por ISO2 (country_code en stage_covid_mundial)
    df["country_code"] = df["country_code"].astype(str).str.strip().str.upper()
    df = df.merge(dim_geo[["id_geografia_mundial","iso2"]],
                  left_on="country_code", right_on="iso2", how="left")

    id_oms = dim_fuente[dim_fuente["nombre"]=="OMS_COVID_MUNDIAL"]
    df["id_fuente"] = int(id_oms["id_fuente"].iloc[0]) if len(id_oms) > 0 else 6

    df_fact = pd.DataFrame({
        "id_tiempo":           df["id_tiempo"],
        "id_geografia_mundial":df["id_geografia_mundial"],
        "id_fuente":           df["id_fuente"],
        "new_cases_mes":       pd.to_numeric(df["new_cases_mes"],  errors="coerce").fillna(0).astype(int),
        "new_deaths_mes":      pd.to_numeric(df["new_deaths_mes"], errors="coerce").fillna(0).astype(int),
        "cum_cases_fin":       pd.to_numeric(df["cum_cases_fin"],  errors="coerce").fillna(0).astype(int),
        "cum_deaths_fin":      pd.to_numeric(df["cum_deaths_fin"], errors="coerce").fillna(0).astype(int),
        "semanas_reporte":     pd.to_numeric(df["semanas_reporte"],errors="coerce").fillna(0).astype(int),
        "periodo":             df["periodo"],
        "fecha_carga":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    print_log(f"Cargando {len(df_fact):,} registros...")
    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")
    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — omitiendo nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — fact_covid_mundial")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_covid_mundial")
    print_log("=" * 60)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): env_path = Path(".env")
    load_dotenv(env_path)
    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")
    load_fact_covid_mundial(sandbox_url, dw_local_url, dw_cloud_url)