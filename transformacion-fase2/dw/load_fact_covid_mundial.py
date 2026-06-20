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
            
            CREATE TABLE IF NOT EXISTS dw.fact_covid_mundial (
                id_fact              BIGSERIAL PRIMARY KEY,
                id_tiempo            INTEGER REFERENCES dw.dim_tiempo(id_tiempo),
                id_geografia_mundial INTEGER REFERENCES dw.dim_geografia_mundial(id_geografia_mundial),
                id_fuente            INTEGER REFERENCES dw.dim_fuente(id_fuente),
                new_cases_mes        BIGINT,
                new_deaths_mes       BIGINT,
                cum_cases_fin        BIGINT,
                cum_deaths_fin       BIGINT,
                semanas_reporte      INTEGER,
                periodo              VARCHAR(20),
                fecha_carga          VARCHAR(30)
            )
        """))
        
    print_log(f"  [{destino}] Truncando tabla de hechos (Limpieza Bottom-Up)...")
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_covid_mundial RESTART IDENTITY"))
        
    print_log(f"  [{destino}] Inyectando {len(df_fact):,} registros agrupados...")
    df_fact.to_sql(
        name="fact_covid_mundial",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000, method="multi",
    )
    print_log(f"  [{destino}] Carga finalizada con éxito.")

def load_fact_covid_mundial(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw       = create_engine(dw_url, pool_pre_ping=True)

    # 1. LECTURA DESDE STAGE
    print_log("Leyendo stage.stage_covid_mundial...")
    df = pd.read_sql("SELECT * FROM stage.stage_covid_mundial WHERE anio IS NOT NULL", engine_sandbox)
    print_log(f"  -> {len(df):,} filas leídas desde el Stage.")

    # 2. LECTURA DE DIMENSIONES (Para hacer el Lookup)
    print_log("Cargando dimensiones maestras a memoria RAM...")
    dim_tiempo = pd.read_sql("SELECT id_tiempo, anio, mes FROM dw.dim_tiempo", engine_dw)
    dim_geo    = pd.read_sql("SELECT id_geografia_mundial, iso2 FROM dw.dim_geografia_mundial", engine_dw)
    
    # 3. LIMPIEZA DE PRE-JOIN (Alineando llaves)
    print_log("Alineando llaves para garantizar exactitud en el JOIN...")
    
    # Tiempo: Alinear tipos
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").fillna(0).astype("Int16")
    dim_tiempo["anio"] = dim_tiempo["anio"].astype("Int16")
    dim_tiempo["mes"]  = dim_tiempo["mes"].astype("Int16")

    # Geografía: Mapear por ISO2 (country_code en stage_covid_mundial)
    df["country_code"] = df["country_code"].astype(str).str.strip().str.upper()

    # 4. LOS MERGES (Calculando Foreign Keys)
    print_log("Cruzando Stage con Dimensiones (Calculando Foreign Keys)...")
    
    df = df.merge(dim_tiempo, on=["anio", "mes"], how="left")
    
    df = df.merge(dim_geo,
                  left_on="country_code", 
                  right_on="iso2", how="left")

    # Fuente: Asignación fija para OMS COVID (ID 6)
    df["id_fuente"] = 6

    # Validación Estricta de Nulos
    nulos = df[["id_tiempo", "id_geografia_mundial"]].isna().sum().to_dict()
    print_log(f"Validación de Integridad Referencial (Nulos en FKs): {nulos}")

    # 5. CONSTRUCCIÓN FINAL DE LA TABLA DE HECHOS
    df_fact = pd.DataFrame({
        "id_tiempo":            df["id_tiempo"],
        "id_geografia_mundial": df["id_geografia_mundial"],
        "id_fuente":            df["id_fuente"],
        "new_cases_mes":        pd.to_numeric(df["new_cases_mes"],   errors="coerce").fillna(0).astype(int),
        "new_deaths_mes":       pd.to_numeric(df["new_deaths_mes"],  errors="coerce").fillna(0).astype(int),
        "cum_cases_fin":        pd.to_numeric(df["cum_cases_fin"],   errors="coerce").fillna(0).astype(int),
        "cum_deaths_fin":       pd.to_numeric(df["cum_deaths_fin"],  errors="coerce").fillna(0).astype(int),
        "semanas_reporte":      pd.to_numeric(df["semanas_reporte"], errors="coerce").fillna(0).astype(int),
        "periodo":              df["periodo"],
        "fecha_carga":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Evitar romper Constraints eliminando huérfanos si existieran
    df_fact = df_fact.dropna(subset=["id_tiempo", "id_geografia_mundial"])
    
    # Casting entero estricto para las Foreign Keys
    df_fact["id_tiempo"]            = df_fact["id_tiempo"].astype(int)
    df_fact["id_geografia_mundial"] = df_fact["id_geografia_mundial"].astype(int)
    df_fact["id_fuente"]            = df_fact["id_fuente"].astype(int)

    # 6. INYECCIÓN
    _cargar_fact(engine_dw, df_fact, "LOCAL")

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("=" * 60)
    print_log("CARGA A DATA WAREHOUSE EXITOSA — fact_covid_mundial")
    print_log("=" * 60)


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Carga Fact COVID Mundial")
    print_log("=" * 60)
    
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")
    
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_url:       raise EnvironmentError("DW_DB_URL no encontrada.")
    
    load_fact_covid_mundial(sandbox_url, dw_url)