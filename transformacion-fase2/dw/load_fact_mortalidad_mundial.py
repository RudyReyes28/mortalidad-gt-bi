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
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact, destino):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_mundial (
                id_fact              BIGSERIAL PRIMARY KEY,
                id_tiempo            INTEGER,
                id_geografia_mundial INTEGER,
                id_causa             INTEGER,
                id_fuente            INTEGER,
                defunciones_total    BIGINT,
                defunciones_infantiles BIGINT,
                defunciones_maternas   BIGINT,
                poblacion_total        BIGINT,
                periodo              VARCHAR(20),
                fecha_carga          VARCHAR(30)
            )
        """))
    df_fact.to_sql(
        name="fact_mortalidad_mundial",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_mortalidad_mundial.")
    engine_dw.dispose()


def load_fact_mortalidad_mundial(sandbox_url, dw_local_url, dw_cloud_url=None):
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    print_log("Leyendo stage.stage_mortalidad_mundial...")
    df = pd.read_sql("SELECT * FROM stage.stage_mortalidad_mundial", engine_sandbox)
    print_log(f"  -> {len(df):,} filas.")

    dim_tiempo = pd.read_sql("SELECT * FROM dw.dim_tiempo",            engine_dw_local)
    dim_geo    = pd.read_sql("SELECT * FROM dw.dim_geografia_mundial", engine_dw_local)
    dim_causa  = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",       engine_dw_local)
    dim_fuente = pd.read_sql("SELECT * FROM dw.dim_fuente",            engine_dw_local)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes_lookup"] = df.apply(
        lambda r: int(r["periodo_tiempo"])
        if str(r.get("unidad_tiempo","")).strip().lower() == "monthly" and pd.notna(r.get("periodo_tiempo"))
        else None, axis=1
    )

    dim_t_mes  = dim_tiempo[dim_tiempo["mes"].notna()][["id_tiempo","anio","mes"]].copy()
    dim_t_mes["mes"] = dim_t_mes["mes"].astype("Int16")
    dim_t_anio = dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo","anio"]].copy()

    df_m = df[df["mes_lookup"].notna()].copy()
    df_m["mes_lookup"] = df_m["mes_lookup"].astype("Int16")
    df_m = df_m.merge(dim_t_mes, left_on=["anio","mes_lookup"], right_on=["anio","mes"], how="left")

    df_a = df[df["mes_lookup"].isna()].copy()
    df_a = df_a.merge(dim_t_anio, on="anio", how="left")

    df = pd.concat([df_m, df_a], ignore_index=True)

    df["iso3c"] = df["iso3c"].astype(str).str.strip().str.upper()
    df = df.merge(dim_geo[["id_geografia_mundial","iso3c"]], on="iso3c", how="left")

    id_zgen = int(dim_causa[dim_causa["codigo_cie10"]=="ZGEN"]["id_causa"].iloc[0])
    df["id_causa"] = id_zgen

    mapa_fuente = dict(zip(dim_fuente["nombre"], dim_fuente["id_fuente"]))
    df["id_fuente"] = df["fuente_dato"].map(mapa_fuente).fillna(4).astype(int)

    df_fact = pd.DataFrame({
        "id_tiempo":              df["id_tiempo"],
        "id_geografia_mundial":   df["id_geografia_mundial"],
        "id_causa":               df["id_causa"],
        "id_fuente":              df["id_fuente"],
        "defunciones_total":      pd.to_numeric(df["defunciones_total"],     errors="coerce").fillna(0).astype(int),
        "defunciones_infantiles": pd.to_numeric(df.get("defunciones_infantiles", 0), errors="coerce").fillna(0).astype(int),
        "defunciones_maternas":   pd.to_numeric(df.get("defunciones_maternas",   0), errors="coerce").fillna(0).astype(int),
        "poblacion_total":        pd.to_numeric(df.get("poblacion_total",         0), errors="coerce").fillna(0).astype(int),
        "periodo":                df["periodo"],
        "fecha_carga":            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

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
