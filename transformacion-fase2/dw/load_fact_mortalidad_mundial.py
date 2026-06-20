import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mortalidad_mundial -> dw.fact_mortalidad_mundial
Grano: mes / país (World Mortality + Centroamérica)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
Usa dim_geografia_mundial (no dim_geografia_gt)

Columnas de stage_mortalidad_mundial (versión actualizada):
    iso3c, country_name, region, anio, mes, semana,
    deaths, time_unit, periodo, fuente, fuente_origen, fecha_carga
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact: pd.DataFrame, destino: str):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_mundial (
                id_fact              BIGSERIAL PRIMARY KEY,
                id_tiempo            INTEGER,
                id_geografia_mundial INTEGER,
                id_fuente            INTEGER,
                deaths               BIGINT,
                time_unit            VARCHAR(20),
                semana               INTEGER,
                periodo              VARCHAR(20),
                fecha_carga          VARCHAR(30)
            )
        """))
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_mortalidad_mundial RESTART IDENTITY"))
    print_log(f"  [{destino}] Tabla dw.fact_mortalidad_mundial truncada.")

    # Convertir Int64 nullable a Python nativo para evitar problemas con psycopg2
    df_insert = df_fact.copy()
    df_insert["id_tiempo"]            = df_insert["id_tiempo"].where(df_insert["id_tiempo"].notna(), other=None).astype(object)
    df_insert["id_geografia_mundial"] = df_insert["id_geografia_mundial"].where(df_insert["id_geografia_mundial"].notna(), other=None).astype(object)
    df_insert["semana"]               = df_insert["semana"].where(df_insert["semana"].notna(), other=None).astype(object)

    df_insert.to_sql(
        name="fact_mortalidad_mundial",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000,
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_mortalidad_mundial.")
    engine_dw.dispose()


def load_fact_mortalidad_mundial(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    # 1. Leer Stage
    print_log("Leyendo stage.stage_mortalidad_mundial...")
    df = pd.read_sql("SELECT * FROM stage.stage_mortalidad_mundial", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leidas.")
    print_log(f"  Columnas: {list(df.columns)}")

    # 2. Cargar dimensiones
    print_log("Cargando dimensiones para lookup...")
    dim_tiempo = pd.read_sql("SELECT * FROM dw.dim_tiempo",            engine_dw_local)
    dim_geo    = pd.read_sql("SELECT * FROM dw.dim_geografia_mundial", engine_dw_local)
    dim_fuente = pd.read_sql("SELECT * FROM dw.dim_fuente",            engine_dw_local)

    # 3. Resolver id_tiempo
    # stage_mortalidad_mundial tiene: anio, mes (puede ser NULL para annual), semana
    print_log("Resolviendo id_tiempo...")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")

    # Para registros mensuales: merge por anio + mes
    dim_t_mes  = dim_tiempo[dim_tiempo["mes"].notna()][["id_tiempo","anio","mes"]].copy()
    dim_t_mes["mes"] = dim_t_mes["mes"].astype("Int16")
    # Para semanales/anuales: tomar UN solo id_tiempo por anio (mes=NULL)
    dim_t_anio = (dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo","anio"]]
                  .drop_duplicates(subset=["anio"])
                  .copy())

    df["mes_val"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int16")

    df_mensual = df[df["mes_val"].notna()].copy()
    df_anual   = df[df["mes_val"].isna()].copy()

    if len(df_mensual) > 0:
        df_mensual = df_mensual.merge(dim_t_mes,
                                      left_on=["anio","mes_val"],
                                      right_on=["anio","mes"], how="left")

    if len(df_anual) > 0:
        df_anual = df_anual.merge(dim_t_anio, on="anio", how="left")

    df = pd.concat([df_mensual, df_anual], ignore_index=True)
    total_orig = len(df_mensual) + len(df_anual)
    if len(df) != total_orig:
        print_log(f"  ADVERTENCIA: merge duplicó filas ({total_orig} -> {len(df)}). Eliminando duplicados...")
        df = df.drop_duplicates()
    print_log(f"  Filas tras merge tiempo: {len(df):,}")

    # 4. Resolver id_geografia_mundial por iso3c
    print_log("Resolviendo id_geografia_mundial...")
    df["iso3c"] = df["iso3c"].astype(str).str.strip().str.upper()
    df = df.merge(dim_geo[["id_geografia_mundial","iso3c"]], on="iso3c", how="left")

    # 5. Resolver id_fuente — columna 'fuente' en stage
    print_log("Resolviendo id_fuente...")
    mapa_fuente = {
        "WORLD_MORTALITY":   4,
        "CENTROAMERICA_RDS": 5,
    }
    df["id_fuente"] = df["fuente"].map(mapa_fuente).fillna(4).astype(int)

    # 6. Construir fact
    print_log("Ensamblando fact_mortalidad_mundial...")
    df_fact = pd.DataFrame({
        "id_tiempo":            df["id_tiempo"].astype("Int64"),
        "id_geografia_mundial": df["id_geografia_mundial"].astype("Int64"),
        "id_fuente":            df["id_fuente"].astype(int),
        "deaths":               pd.to_numeric(df["deaths"], errors="coerce").fillna(0).astype(int),
        "time_unit":            df["time_unit"].astype(str),
        "semana":               pd.to_numeric(df.get("semana", None), errors="coerce").where(
                                    pd.to_numeric(df.get("semana", None), errors="coerce").notna()
                                ).astype("Int64"),
        "periodo":              df["periodo"],
        "fecha_carga":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    nulos = df_fact[["id_tiempo","id_geografia_mundial"]].isna().sum()
    print_log(f"  Nulos FK: {nulos.to_dict()}")
    print_log(f"Cargando {len(df_fact):,} registros...")

    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")
    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — omitiendo nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — fact_mortalidad_mundial")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_mortalidad_mundial")
    print_log("=" * 60)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): env_path = Path(".env")
    load_dotenv(env_path)
    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")
    load_fact_mortalidad_mundial(sandbox_url, dw_local_url, dw_cloud_url)