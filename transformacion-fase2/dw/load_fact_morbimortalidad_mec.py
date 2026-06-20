import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mspas_mec -> dw.fact_morbimortalidad_mec
Grano: año / departamento / causa / grupo_etario / sexo
Galaxy Schema — PDF Decisiones de Diseño Fase 2
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _cargar_fact(engine_dw, df_fact: pd.DataFrame, destino: str):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_morbimortalidad_mec (
                id_fact          BIGSERIAL PRIMARY KEY,
                id_tiempo        INTEGER REFERENCES dw.dim_tiempo(id_tiempo) ON DELETE CASCADE,
                id_geografia     INTEGER REFERENCES dw.dim_geografia_gt(id_geografia) ON DELETE CASCADE,
                id_causa         INTEGER REFERENCES dw.dim_causa_cie10(id_causa) ON DELETE CASCADE,
                id_grupo_etario  INTEGER REFERENCES dw.dim_grupo_etario(id_grupo_etario) ON DELETE CASCADE,
                id_sexo          INTEGER REFERENCES dw.dim_sexo(id_sexo) ON DELETE CASCADE,
                id_fuente        INTEGER REFERENCES dw.dim_fuente(id_fuente) ON DELETE CASCADE,
                casos            INTEGER,
                fecha_carga      VARCHAR(30)
            )
        """))
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_morbimortalidad_mec RESTART IDENTITY"))
    print_log(f"  [{destino}] Tabla dw.fact_morbimortalidad_mec truncada.")
    df_fact.to_sql(
        name="fact_morbimortalidad_mec",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_morbimortalidad_mec.")
    engine_dw.dispose()


def load_fact_morbimortalidad_mec(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    # 1. Leer Stage
    print_log("Leyendo stage.stage_mspas_mec...")
    df = pd.read_sql("SELECT * FROM stage.stage_mspas_mec", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leidas.")
    print_log(f"  Columnas: {list(df.columns)}")

    # 2. Cargar dimensiones
    print_log("Cargando dimensiones para lookup...")
    dim_tiempo   = pd.read_sql("SELECT * FROM dw.dim_tiempo",        engine_dw_local)
    dim_geo      = pd.read_sql("SELECT * FROM dw.dim_geografia_gt",  engine_dw_local)
    dim_causa    = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",   engine_dw_local)
    dim_etario   = pd.read_sql("SELECT * FROM dw.dim_grupo_etario",  engine_dw_local)
    dim_sexo     = pd.read_sql("SELECT * FROM dw.dim_sexo",          engine_dw_local)
    dim_fuente   = pd.read_sql("SELECT * FROM dw.dim_fuente",        engine_dw_local)

    # 3. Resolver id_tiempo (por anio, sin mes)
    print_log("Resolviendo id_tiempo...")
    dim_t = dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo","anio"]].copy()
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df = df.merge(dim_t, on="anio", how="left")

    # 4. Resolver id_geografia_gt (por depto + municipio)
    print_log("Resolviendo id_geografia...")
    df["departamento"] = df["departamento"].astype(str).str.strip().str.upper()
    df["municipio"]    = df["municipio"].astype(str).str.strip().str.upper()
    dim_geo["depto_upper"] = dim_geo["nombre_departamento"].str.upper()
    dim_geo["muni_upper"]  = dim_geo["nombre_municipio"].str.upper()
    df = df.merge(
        dim_geo[["id_geografia","depto_upper","muni_upper"]],
        left_on=["departamento","municipio"],
        right_on=["depto_upper","muni_upper"],
        how="left"
    )

    # 5. Resolver id_causa (por codigo CIE-10)
    print_log("Resolviendo id_causa...")
    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()
    dim_causa["codigo_cie10_upper"] = dim_causa["codigo_cie10"].str.upper()
    df = df.merge(
        dim_causa[["id_causa","codigo_cie10_upper"]],
        left_on="codigo_cie10",
        right_on="codigo_cie10_upper",
        how="left"
    )

    # 6. Resolver id_grupo_etario
    print_log("Resolviendo id_grupo_etario...")
    df["grupo_etario"] = df["grupo_etario"].astype(str).str.strip()
    df = df.merge(
        dim_etario[["id_grupo_etario","rango"]],
        left_on="grupo_etario",
        right_on="rango",
        how="left"
    )

    # 7. Resolver id_sexo
    print_log("Resolviendo id_sexo...")
    df["sexo"] = df["sexo"].astype(str).str.strip().str.upper()
    dim_sexo["codigo_upper"] = dim_sexo["codigo"].str.upper()
    df = df.merge(
        dim_sexo[["id_sexo","codigo_upper"]],
        left_on="sexo",
        right_on="codigo_upper",
        how="left"
    )

    # 8. Resolver id_fuente — MSPAS_MEC = id 2
    df["id_fuente"] = 2

    # 9. Construir fact
    print_log("Ensamblando fact_morbimortalidad_mec...")
    df_fact = pd.DataFrame({
        "id_tiempo":       df["id_tiempo"].astype("Int64"),
        "id_geografia":    df["id_geografia"].astype("Int64"),
        "id_causa":        df["id_causa"].astype("Int64"),
        "id_grupo_etario": df["id_grupo_etario"].astype("Int64"),
        "id_sexo":         df["id_sexo"].astype("Int64"),
        "id_fuente":       df["id_fuente"].astype(int),
        "casos":           pd.to_numeric(df["casos"], errors="coerce").fillna(0).astype(int),
        "fecha_carga":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    nulos = df_fact[["id_tiempo","id_geografia","id_causa"]].isna().sum()
    print_log(f"  Nulos FK: {nulos.to_dict()}")
    print_log(f"Cargando {len(df_fact):,} registros...")

    _cargar_fact(create_engine(dw_local_url, pool_pre_ping=True), df_fact, "LOCAL")
    if dw_cloud_url:
        _cargar_fact(create_engine(dw_cloud_url, pool_pre_ping=True), df_fact, "NUBE")
    else:
        print_log("DW_CLOUD_URL no configurada — omitiendo nube.")

    engine_sandbox.dispose()
    engine_dw_local.dispose()
    print_log("CARGA EXITOSA — fact_morbimortalidad_mec")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_morbimortalidad_mec")
    print_log("=" * 60)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): env_path = Path(".env")
    load_dotenv(env_path)
    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada.")
    load_fact_morbimortalidad_mec(sandbox_url, dw_local_url, dw_cloud_url)