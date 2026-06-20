import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_defunciones_gt -> dw.fact_defunciones_gt
Grano: defunción individual (INE Guatemala)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact: pd.DataFrame, destino: str):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_defunciones_gt (
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
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_defunciones_gt RESTART IDENTITY"))
    print_log(f"  [{destino}] Tabla dw.fact_defunciones_gt truncada.")
    df_fact.to_sql(
        name="fact_defunciones_gt",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_defunciones_gt.")
    engine_dw.dispose()


def load_fact_defunciones_gt(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    print_log("Leyendo y agregando stage.stage_defunciones_gt...")
    query = """
        SELECT
            anio_ocurrencia         AS anio,
            mes_ocurrencia          AS mes,
            nombre_depto_ocurrencia AS departamento,
            nombre_muni_ocurrencia  AS municipio,
            sexo, grupo_etario, codigo_cie10, periodo,
            COUNT(*) AS total_casos
        FROM stage.stage_defunciones_gt
        WHERE anio_ocurrencia IS NOT NULL
        GROUP BY anio_ocurrencia, mes_ocurrencia,
                 nombre_depto_ocurrencia, nombre_muni_ocurrencia,
                 sexo, grupo_etario, codigo_cie10, periodo
    """
    df = pd.read_sql(query, engine_sandbox)
    print_log(f"  -> {len(df):,} filas agregadas.")

    print_log("Cargando dimensiones para lookup...")
    dim_tiempo  = pd.read_sql("SELECT * FROM dw.dim_tiempo",           engine_dw_local)
    dim_geo     = pd.read_sql("SELECT * FROM dw.dim_geografia_gt",     engine_dw_local)
    dim_causa   = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",      engine_dw_local)
    dim_sexo    = pd.read_sql("SELECT * FROM dw.dim_sexo",             engine_dw_local)
    dim_grupo   = pd.read_sql("SELECT * FROM dw.dim_grupo_etario",     engine_dw_local)
    dim_fuente  = pd.read_sql("SELECT * FROM dw.dim_fuente",           engine_dw_local)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").astype("Int16")
    df = df.merge(dim_tiempo[["id_tiempo","anio","mes"]], on=["anio","mes"], how="left")
    df = df.merge(dim_geo[["id_geografia","nombre_departamento","nombre_municipio"]],
                  left_on=["departamento","municipio"],
                  right_on=["nombre_departamento","nombre_municipio"], how="left")
    df = df.merge(dim_causa[["id_causa","codigo_cie10"]], on="codigo_cie10", how="left")

    mapa_sexo = {"Femenino": 1, "Masculino": 2}
    df["id_sexo"] = df["sexo"].map(mapa_sexo).fillna(3).astype(int)

    mapa_grupo = {
        "< 1 año": "< 1 anio", "1-4": "1-4", "5-14": "5-14",
        "15-29": "15-29", "30-44": "30-44", "45-59": "45-59",
        "60+": "60 o mas", "No especificado": "No especificado",
    }
    df["grupo_std"] = df["grupo_etario"].map(mapa_grupo).fillna("No especificado")
    df = df.merge(dim_grupo[["id_grupo_etario","rango"]],
                  left_on="grupo_std", right_on="rango", how="left")
    df["id_grupo_etario"] = df["id_grupo_etario"].fillna(8).astype(int)
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"]=="INE"]["id_fuente"].iloc[0])

    df_fact = pd.DataFrame({
        "id_tiempo":       df["id_tiempo"],
        "id_geografia":    df["id_geografia"],
        "id_causa":        df["id_causa"],
        "id_sexo":         df["id_sexo"],
        "id_grupo_etario": df["id_grupo_etario"],
        "id_fuente":       df["id_fuente"],
        "total_casos":     pd.to_numeric(df["total_casos"], errors="coerce").fillna(0).astype(int),
        "periodo":         df["periodo"],
        "fecha_carga":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    print_log(f"  Nulos FK: {df_fact[['id_tiempo','id_geografia','id_causa']].isna().sum().to_dict()}")
    print_log(f"Cargando {len(df_fact):,} registros...")
    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")
    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — omitiendo nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — fact_defunciones_gt")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_defunciones_gt")
    print_log("=" * 60)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): env_path = Path(".env")
    load_dotenv(env_path)
    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")
    load_fact_defunciones_gt(sandbox_url, dw_local_url, dw_cloud_url)