import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Script de carga de hechos: stage_mspas_mec -> dw.fact_defunciones
(load_fact_mspas_mec.py)

Lee stage.stage_mspas_mec, resuelve los IDs de cada dimension
y carga los registros en dw.fact_defunciones.

IMPORTANTE: Ejecutar create_dimensions.py antes de este script.
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _clasificar_grupo_etario_mspas(rango: str) -> str:
    """
    Mapea los rangos del MSPAS al catálogo estándar de dim_grupo_etario.
    MSPAS usa rangos como '25 a 29 años', '< 1 mes', '70+', etc.
    """
    if pd.isna(rango) or str(rango).strip() == "":
        return "No especificado"
    r = str(rango).strip().lower()
    if "mes" in r or "< 1" in r:       return "< 1 anio"
    if "1 a" in r or "2 a" in r or "3 a" in r or "4 a" in r: return "1-4"
    if any(x in r for x in ["5 a", "6 a", "7 a", "8 a", "9 a", "10 a", "11 a", "12 a", "13 a", "14 a"]): return "5-14"
    if any(x in r for x in ["15 a", "16 a", "17 a", "18 a", "19 a", "20 a", "21 a", "22 a", "23 a", "24 a", "25 a", "26 a", "27 a", "28 a", "29 a"]): return "15-29"
    if any(x in r for x in ["30 a", "31 a", "32 a", "33 a", "34 a", "35 a", "36 a", "37 a", "38 a", "39 a", "40 a", "41 a", "42 a", "43 a", "44 a"]): return "30-44"
    if any(x in r for x in ["45 a", "46 a", "47 a", "48 a", "49 a", "50 a", "51 a", "52 a", "53 a", "54 a", "55 a", "56 a", "57 a", "58 a", "59 a"]): return "45-59"
    if "60" in r or "65" in r or "70" in r or "75" in r or "80" in r or "+" in r: return "60 o mas"
    return "No especificado"


def load_fact_mspas_mec(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox = create_engine(sandbox_url, pool_pre_ping=True)
    engine_dw      = create_engine(dw_url,      pool_pre_ping=True)

    # 1. Leer Stage
    print_log("Leyendo stage.stage_mspas_mec...")
    df = pd.read_sql("SELECT * FROM stage.stage_mspas_mec", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leidas.")

    # 2. Cargar dimensiones del DW como lookup
    print_log("Cargando dimensiones para lookup...")
    dim_tiempo       = pd.read_sql("SELECT * FROM dw.dim_tiempo",       engine_dw)
    dim_geografia    = pd.read_sql("SELECT * FROM dw.dim_geografia",    engine_dw)
    dim_causa        = pd.read_sql("SELECT * FROM dw.dim_causa_cie10",  engine_dw)
    dim_sexo         = pd.read_sql("SELECT * FROM dw.dim_sexo",         engine_dw)
    dim_grupo        = pd.read_sql("SELECT * FROM dw.dim_grupo_etario", engine_dw)
    dim_fuente       = pd.read_sql("SELECT * FROM dw.dim_fuente",       engine_dw)

    # 3. Resolver id_tiempo (anual — mes=NULL)
    print_log("Resolviendo id_tiempo...")
    dim_t = dim_tiempo[dim_tiempo["mes"].isna()][["id_tiempo", "anio", "periodo"]].copy()
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df = df.merge(dim_t[["id_tiempo", "anio"]], on="anio", how="left")
    df = df.rename(columns={"id_tiempo": "id_tiempo"})

    # 4. Resolver id_geografia
    print_log("Resolviendo id_geografia...")
    dim_geo_gt = dim_geografia[["id_geografia", "departamento", "municipio"]].copy()
    df = df.merge(dim_geo_gt, on=["departamento", "municipio"], how="left")

    # 5. Resolver id_causa
    print_log("Resolviendo id_causa...")
    dim_c = dim_causa[["id_causa", "codigo_cie10"]].copy()
    df = df.merge(dim_c, on="codigo_cie10", how="left")

    # 6. Resolver id_sexo
    print_log("Resolviendo id_sexo...")
    mapa_sexo = {"Femenino": 1, "Masculino": 2}
    df["id_sexo"] = df["sexo"].map(mapa_sexo).fillna(3).astype(int)

    # 7. Resolver id_grupo_etario
    print_log("Resolviendo id_grupo_etario...")
    df["rango_std"] = df["grupo_etario"].apply(_clasificar_grupo_etario_mspas)
    dim_g = dim_grupo[["id_grupo_etario", "rango"]].copy()
    df = df.merge(dim_g, left_on="rango_std", right_on="rango", how="left")
    df["id_grupo_etario"] = df["id_grupo_etario"].fillna(8).astype(int)

    # 8. id_fuente fijo para MSPAS_MEC
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"] == "MSPAS_MEC"]["id_fuente"].iloc[0])

    # 9. Construir fact
    print_log("Ensamblando fact_defunciones...")
    df_fact = pd.DataFrame({
        "id_tiempo":        df["id_tiempo"],
        "id_geografia":     df["id_geografia"],
        "id_causa":         df["id_causa"],
        "id_sexo":          df["id_sexo"],
        "id_grupo_etario":  df["id_grupo_etario"],
        "id_fuente":        df["id_fuente"],
        "total_casos":      pd.to_numeric(df["casos"], errors="coerce").fillna(0).astype(int),
        "periodo":          df["periodo"],
        "fecha_carga":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    nulos = df_fact[["id_tiempo", "id_geografia", "id_causa"]].isna().sum()
    print_log(f"  Nulos en claves FK: {nulos.to_dict()}")

    # 10. Crear tabla si no existe, luego insertar
    print_log(f"Cargando {len(df_fact):,} registros a dw.fact_defunciones...")
    with engine_dw.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS dw"))
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
    print_log("CARGA EXITOSA — MSPAS MEC -> fact_defunciones")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: load_fact_mspas_mec")
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

    load_fact_mspas_mec(sandbox_url, dw_url)