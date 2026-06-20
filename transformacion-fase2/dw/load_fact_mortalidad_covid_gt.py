import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mspas_covid -> dw.fact_mortalidad_covid_gt
Grano: mensual / municipio (Agregado para optimizar rendimiento)
Galaxy Schema — PDF Decisiones de Diseño Fase 2
Causa fija: U071 (COVID-19 identificado)
"""

# =====================================================================
# LIBRERÍA DE LOGGING LOCAL
# =====================================================================
def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()

def _cargar_fact(engine_dw, df_fact: pd.DataFrame, destino: str):
    print_log(f"  [{destino}] Asegurando estructura DDL con Llaves Foráneas Físicas...")
    with engine_dw.begin() as conn:
        conn.execute(text("""
            CREATE SCHEMA IF NOT EXISTS dw;
            
            CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_covid_gt (
                id_fact         BIGSERIAL PRIMARY KEY,
                id_tiempo       INTEGER REFERENCES dw.dim_tiempo(id_tiempo),
                id_geografia    INTEGER REFERENCES dw.dim_geografia_gt(id_geografia),
                id_causa        INTEGER REFERENCES dw.dim_causa_cie10(id_causa),
                id_fuente       INTEGER REFERENCES dw.dim_fuente(id_fuente),
                fallecidos      BIGINT,
                tasa_por_100k   NUMERIC(10,4),
                periodo         VARCHAR(20),
                fecha_carga     VARCHAR(30)
            )
        """))
        
    print_log(f"  [{destino}] Truncando tabla de hechos (Limpieza Bottom-Up)...")
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_mortalidad_covid_gt RESTART IDENTITY"))
        
    print_log(f"  [{destino}] Inyectando {len(df_fact):,} registros agrupados...")
    df_fact.to_sql(
        name="fact_mortalidad_covid_gt",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000, method="multi",
    )
    print_log(f"  [{destino}] Carga finalizada con éxito.")

def load_fact_mortalidad_covid_gt(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw       = create_engine(dw_url, pool_pre_ping=True)

    # 1. LECTURA Y AGREGACIÓN DESDE STAGE
    print_log("Leyendo y agregando stage.stage_mspas_covid...")
    query = """
        SELECT
            anio,
            mes,
            departamento,
            municipio,
            periodo,
            SUM(fallecidos) AS fallecidos,
            MAX(tasa_por_100k) AS tasa_por_100k
        FROM stage.stage_mspas_covid
        WHERE anio IS NOT NULL
        GROUP BY anio, mes, departamento, municipio, periodo
    """
    df = pd.read_sql(query, engine_sandbox)
    print_log(f"  -> {len(df):,} filas agregadas desde el Stage.")

    # 2. LECTURA DE DIMENSIONES (Para hacer el Lookup)
    print_log("Cargando dimensiones maestras a memoria RAM...")
    dim_tiempo = pd.read_sql("SELECT id_tiempo, anio, mes FROM dw.dim_tiempo", engine_dw)
    dim_geo    = pd.read_sql("SELECT id_geografia, nombre_departamento, nombre_municipio FROM dw.dim_geografia_gt", engine_dw)
    dim_causa  = pd.read_sql("SELECT id_causa, codigo_cie10 FROM dw.dim_causa_cie10", engine_dw)
    dim_fuente = pd.read_sql("SELECT id_fuente, nombre FROM dw.dim_fuente", engine_dw)

    # 3. LIMPIEZA DE PRE-JOIN (Alineando llaves)
    print_log("Alineando llaves para garantizar exactitud en el JOIN...")
    
    # Tiempo: Alinear tipos
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").fillna(0).astype("Int16")
    dim_tiempo["anio"] = dim_tiempo["anio"].astype("Int16")
    dim_tiempo["mes"]  = dim_tiempo["mes"].astype("Int16")

    # Geografía: Alinear nombres
    df["departamento"] = df["departamento"].fillna("Ignorado").astype(str).str.strip()
    df["municipio"]    = df["municipio"].fillna("Ignorado").astype(str).str.strip()

    # 4. LOS MERGES (Calculando Foreign Keys)
    print_log("Cruzando Stage con Dimensiones (Calculando Foreign Keys)...")
    
    df = df.merge(dim_tiempo, on=["anio", "mes"], how="left")
    
    df = df.merge(dim_geo,
                  left_on=["departamento", "municipio"],
                  right_on=["nombre_departamento", "nombre_municipio"], how="left")

    # Causa Fija: U071 (COVID-19)
    try:
        id_u071 = int(dim_causa[dim_causa["codigo_cie10"] == "U071"]["id_causa"].iloc[0])
    except IndexError:
        id_u071 = 1 # Fallback
    df["id_causa"]  = id_u071

    # Fuente Fija: MSPAS_COVID
    try:
        id_fuente_ms = int(dim_fuente[dim_fuente["nombre"] == "MSPAS_COVID"]["id_fuente"].iloc[0])
    except IndexError:
        id_fuente_ms = 3
    df["id_fuente"] = id_fuente_ms

    # Validación Estricta de Nulos
    nulos = df[["id_tiempo", "id_geografia"]].isna().sum().to_dict()
    print_log(f"Validación de Integridad Referencial (Nulos en FKs): {nulos}")

    # 5. CONSTRUCCIÓN FINAL DE LA TABLA DE HECHOS
    df_fact = pd.DataFrame({
        "id_tiempo":    df["id_tiempo"],
        "id_geografia": df["id_geografia"],
        "id_causa":     df["id_causa"],
        "id_fuente":    df["id_fuente"],
        "fallecidos":   pd.to_numeric(df["fallecidos"], errors="coerce").fillna(0).astype(int),
        "tasa_por_100k":pd.to_numeric(df["tasa_por_100k"], errors="coerce"),
        "periodo":      df["periodo"],
        "fecha_carga":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Evitar romper Constraints eliminando huérfanos si existieran
    df_fact = df_fact.dropna(subset=["id_tiempo", "id_geografia"])
    
    # Casting entero estricto para las Foreign Keys
    df_fact["id_tiempo"]    = df_fact["id_tiempo"].astype(int)
    df_fact["id_geografia"] = df_fact["id_geografia"].astype(int)
    df_fact["id_causa"]     = df_fact["id_causa"].astype(int)
    df_fact["id_fuente"]    = df_fact["id_fuente"].astype(int)

    # 6. INYECCIÓN
    _cargar_fact(engine_dw, df_fact, "LOCAL")

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("=" * 60)
    print_log("CARGA A DATA WAREHOUSE EXITOSA — fact_mortalidad_covid_gt")
    print_log("=" * 60)

if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Carga Fact Mortalidad COVID GT")
    print_log("=" * 60)
    
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")
    
    if not sandbox_url:  raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada.")
    if not dw_url:       raise EnvironmentError("Variable DW_DB_URL no encontrada.")
    
    load_fact_mortalidad_covid_gt(sandbox_url, dw_url)