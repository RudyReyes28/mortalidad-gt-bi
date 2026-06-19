import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mspas_mec -> dw.fact_morbimortalidad_mec
Grano: año / depto / causa / grupo / sexo (MSPAS MEC)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _clasificar_grupo_mspas(rango):
    if pd.isna(rango) or str(rango).strip() == "": return "No especificado"
    r = str(rango).strip().lower()
    if "mes" in r or "< 1" in r: return "< 1 anio"
    if any(x in r for x in ["1 a","2 a","3 a","4 a"]): return "1-4"
    if any(x in r for x in ["5 a","6 a","7 a","8 a","9 a","10 a","11 a","12 a","13 a","14 a"]): return "5-14"
    if any(x in r for x in ["15 a","16 a","17 a","18 a","19 a","20 a","21 a","22 a","23 a","24 a","25 a","26 a","27 a","28 a","29 a"]): return "15-29"
    if any(x in r for x in ["30 a","31 a","32 a","33 a","34 a","35 a","36 a","37 a","38 a","39 a","40 a","41 a","42 a","43 a","44 a"]): return "30-44"
    if any(x in r for x in ["45 a","46 a","47 a","48 a","49 a","50 a","51 a","52 a","53 a","54 a","55 a","56 a","57 a","58 a","59 a"]): return "45-59"
    if "60" in r or "65" in r or "70" in r or "75" in r or "80" in r or "+" in r: return "60 o mas"
    return "No especificado"


def _cargar_fact(engine_dw, df_fact, destino):
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dw.fact_morbimortalidad_mec (
                id_fact         BIGSERIAL PRIMARY KEY,
                id_tiempo       INTEGER,
                id_geografia    INTEGER,
                id_causa        INTEGER,
                id_sexo         INTEGER,
                id_grupo_etario INTEGER,
                id_fuente       INTEGER,
                casos           BIGINT,
                periodo         VARCHAR(20),
                fecha_carga     VARCHAR(30)
            )
        """))
    df_fact.to_sql(
        name="fact_morbimortalidad_mec",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=2000, method="multi",
    )
    print_log(f"  [{destino}] {len(df_fact):,} registros en dw.fact_morbimortalidad_mec.")
    engine_dw.dispose()


def load_fact_morbimortalidad_mec(sandbox_url, dw_local_url, dw_cloud_url=None):
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw_local = create_engine(dw_local_url, pool_pre_ping=True)

    print_log("Leyendo stage.stage_mspas_mec...")
    df = pd.read_sql("SELECT * FROM stage.stage_mspas_mec", engine_sandbox)
    print_log(f"  -> {len(df):,} filas.")

    dim_tiempo = pd.read_sql("SELECT * FROM dw.dim_tiempo",           engine_dw_local)
    dim_geo    = pd.read_sql("SELECT * FROM dw.dim_geografia_gt",     engine_dw_local)
    dim_causa  = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",      engine_dw_local)
    dim_sexo   = pd.read_sql("SELECT * FROM dw.dim_sexo",             engine_dw_local)
    dim_grupo  = pd.read_sql("SELECT * FROM dw.dim_grupo_etario",     engine_dw_local)
    dim_fuente = pd.read_sql("SELECT * FROM dw.dim_fuente",           engine_dw_local)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    dim_t = dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo","anio"]].copy()
    df = df.merge(dim_t, on="anio", how="left")
    df = df.merge(dim_geo[["id_geografia","nombre_departamento","nombre_municipio"]],
                  left_on=["departamento","municipio"],
                  right_on=["nombre_departamento","nombre_municipio"], how="left")
    df = df.merge(dim_causa[["id_causa","codigo_cie10"]], on="codigo_cie10", how="left")

    mapa_sexo = {"Femenino": 1, "Masculino": 2}
    df["id_sexo"] = df["sexo"].map(mapa_sexo).fillna(3).astype(int)

    df["rango_std"] = df["grupo_etario"].apply(_clasificar_grupo_mspas)
    df = df.merge(dim_grupo[["id_grupo_etario","rango"]],
                  left_on="rango_std", right_on="rango", how="left")
    df["id_grupo_etario"] = df["id_grupo_etario"].fillna(8).astype(int)
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"]=="MSPAS_MEC"]["id_fuente"].iloc[0])

    df_fact = pd.DataFrame({
        "id_tiempo":       df["id_tiempo"],
        "id_geografia":    df["id_geografia"],
        "id_causa":        df["id_causa"],
        "id_sexo":         df["id_sexo"],
        "id_grupo_etario": df["id_grupo_etario"],
        "id_fuente":       df["id_fuente"],
        "casos":           pd.to_numeric(df["casos"], errors="coerce").fillna(0).astype(int),
        "periodo":         df["periodo"],
        "fecha_carga":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

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
