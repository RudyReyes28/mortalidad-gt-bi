import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Script de carga de hechos: stage_mortalidad_mundial -> dw.fact_defunciones
(load_fact_mundial.py)

Lee stage.stage_mortalidad_mundial, resuelve los IDs de cada dimension
y carga los registros en dw.fact_defunciones.

Consideraciones especiales:
  - No tiene causa CIE-10 especifica: se asigna ZGEN (mortalidad general)
  - No tiene sexo disponible: se asigna No especificado
  - No tiene grupo etario: se asigna No especificado
  - Fuente_dato distingue WORLD_MORTALITY vs CENTROAMERICA_RDS

IMPORTANTE: Ejecutar create_dimensions.py antes de este script.
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def load_fact_mundial(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox = create_engine(sandbox_url, pool_pre_ping=True)
    engine_dw      = create_engine(dw_url,      pool_pre_ping=True)

    # 1. Leer Stage
    print_log("Leyendo stage.stage_mortalidad_mundial...")
    df = pd.read_sql("SELECT * FROM stage.stage_mortalidad_mundial", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leidas.")

    # 2. Cargar dimensiones del DW como lookup
    print_log("Cargando dimensiones para lookup...")
    dim_tiempo    = pd.read_sql("SELECT * FROM dw.dim_tiempo",       engine_dw)
    dim_geografia = pd.read_sql("SELECT * FROM dw.dim_geografia",    engine_dw)
    dim_causa     = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",  engine_dw)
    dim_fuente    = pd.read_sql("SELECT * FROM dw.dim_fuente",       engine_dw)

    # 3. Resolver id_tiempo
    # World Mortality tiene mes para datos mensuales, NULL para anuales
    print_log("Resolviendo id_tiempo...")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")

    # Intentar con mes primero (datos mensuales de World Mortality)
    df["mes_lookup"] = df.apply(
        lambda r: int(r["periodo_tiempo"])
        if str(r["unidad_tiempo"]).strip().lower() == "monthly" and pd.notna(r["periodo_tiempo"])
        else None,
        axis=1
    )

    # Merge para datos mensuales
    dim_t_mes = dim_tiempo[dim_tiempo["mes"].notna()][["id_tiempo", "anio", "mes"]].copy()
    dim_t_mes["mes"] = dim_t_mes["mes"].astype("Int16")
    df_mensual = df[df["mes_lookup"].notna()].copy()
    df_mensual["mes_lookup"] = df_mensual["mes_lookup"].astype("Int16")
    df_mensual = df_mensual.merge(
        dim_t_mes, left_on=["anio", "mes_lookup"], right_on=["anio", "mes"], how="left"
    )

    # Merge para datos anuales
    dim_t_anio = dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo", "anio"]].copy()
    df_anual = df[df["mes_lookup"].isna()].copy()
    df_anual = df_anual.merge(dim_t_anio, on="anio", how="left")

    df = pd.concat([df_mensual, df_anual], ignore_index=True)

    # 4. Resolver id_geografia por iso3c
    print_log("Resolviendo id_geografia...")
    dim_geo_int = dim_geografia[dim_geografia["departamento"].isna()][
        ["id_geografia", "iso3c"]
    ].copy()
    df["iso3c"] = df["iso3c"].astype(str).str.strip().str.upper()
    df = df.merge(dim_geo_int, on="iso3c", how="left")

    # 5. id_causa fijo: ZGEN — mortalidad general
    print_log("Asignando causa fija ZGEN (mortalidad general)...")
    id_causa_gen = int(dim_causa[dim_causa["codigo_cie10"] == "ZGEN"]["id_causa"].iloc[0])
    df["id_causa"] = id_causa_gen

    # 6. id_sexo fijo: No especificado
    df["id_sexo"] = 3

    # 7. id_grupo_etario fijo: No especificado
    df["id_grupo_etario"] = 8

    # 8. id_fuente segun fuente_dato
    mapa_fuente = dict(zip(dim_fuente["nombre"], dim_fuente["id_fuente"]))
    df["id_fuente"] = df["fuente_dato"].map(mapa_fuente).fillna(4).astype(int)

    # 9. Construir fact
    print_log("Ensamblando fact_defunciones...")
    df_fact = pd.DataFrame({
        "id_tiempo":        df["id_tiempo"],
        "id_geografia":     df["id_geografia"],
        "id_causa":         df["id_causa"],
        "id_sexo":          df["id_sexo"],
        "id_grupo_etario":  df["id_grupo_etario"],
        "id_fuente":        df["id_fuente"],
        "total_casos":      pd.to_numeric(df["defunciones_total"], errors="coerce").fillna(0).astype(int),
        "periodo":          df["periodo"],
        "fecha_carga":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    nulos = df_fact[["id_tiempo", "id_geografia"]].isna().sum()
    print_log(f"  Nulos en claves FK: {nulos.to_dict()}")

    # 10. Insertar
    print_log(f"Cargando {len(df_fact):,} registros a dw.fact_defunciones...")
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

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("CARGA EXITOSA — Mortalidad Mundial -> fact_defunciones")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_mundial")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")

    if not sandbox_url: raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_url:      raise EnvironmentError("DW_DB_URL no encontrada.")

    load_fact_mundial(sandbox_url, dw_url)