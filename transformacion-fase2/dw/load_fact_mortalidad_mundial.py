import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mortalidad_mundial -> dw.fact_mortalidad_mundial
Grano: Agregado por país, año, mes y semana
Galaxy Schema — PDF Decisiones de Diseño Fase 2
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
            
            CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_mundial (
                id_fact              BIGSERIAL PRIMARY KEY,
                id_tiempo            INTEGER REFERENCES dw.dim_tiempo(id_tiempo),
                id_geografia_mundial INTEGER REFERENCES dw.dim_geografia_mundial(id_geografia_mundial),
                id_fuente            INTEGER REFERENCES dw.dim_fuente(id_fuente),
                deaths               BIGINT,
                time_unit            VARCHAR(20),
                semana               INTEGER,
                periodo              VARCHAR(20),
                fecha_carga          VARCHAR(30)
            )
        """))
        
    print_log(f"  [{destino}] Truncando tabla de hechos (Limpieza Bottom-Up)...")
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_mortalidad_mundial RESTART IDENTITY"))
        
    print_log(f"  [{destino}] Inyectando {len(df_fact):,} registros agrupados...")
    
    # Truco para psycopg2: Convertir tipos nullable a object con None nativo
    df_insert = df_fact.copy()
    df_insert["semana"] = df_insert["semana"].where(df_insert["semana"].notna(), other=None).astype(object)

    df_insert.to_sql(
        name="fact_mortalidad_mundial",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000, method="multi",
    )
    print_log(f"  [{destino}] Carga finalizada con éxito.")

def load_fact_mortalidad_mundial(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw       = create_engine(dw_url, pool_pre_ping=True)

    # 1. LECTURA Y AGREGACIÓN DESDE STAGE
    print_log("Leyendo y agregando stage.stage_mortalidad_mundial...")
    query = """
        SELECT
            iso3c, 
            anio, 
            mes, 
            semana,
            time_unit, 
            periodo, 
            fuente,
            SUM(deaths) AS deaths
        FROM stage.stage_mortalidad_mundial
        WHERE anio IS NOT NULL AND iso3c IS NOT NULL
        GROUP BY iso3c, anio, mes, semana, time_unit, periodo, fuente
    """
    df = pd.read_sql(query, engine_sandbox)
    print_log(f"  -> {len(df):,} filas agregadas desde el Stage.")

    # 2. LECTURA DE DIMENSIONES (Para hacer el Lookup)
    print_log("Cargando dimensiones maestras a memoria RAM...")
    dim_tiempo = pd.read_sql("SELECT id_tiempo, anio, mes FROM dw.dim_tiempo", engine_dw)
    dim_geo    = pd.read_sql("SELECT id_geografia_mundial, iso3c FROM dw.dim_geografia_mundial", engine_dw)
    dim_fuente = pd.read_sql("SELECT id_fuente, nombre FROM dw.dim_fuente", engine_dw)

    # 3. LIMPIEZA DE PRE-JOIN (Alineando llaves)
    print_log("Alineando llaves para garantizar exactitud en el JOIN...")
    
    # Tiempo: La clave del éxito es rellenar los meses nulos con 0 para igualar a la dimensión
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").fillna(0).astype("Int16")
    dim_tiempo["anio"] = dim_tiempo["anio"].astype("Int16")
    dim_tiempo["mes"]  = dim_tiempo["mes"].astype("Int16")

    # Geografía: Mayúsculas estrictas
    df["iso3c"] = df["iso3c"].astype(str).str.strip().str.upper()

    # Fuente: Asignación de ID
    mapa_fuente = {"WORLD_MORTALITY": 4, "CENTROAMERICA_RDS": 5}
    # Si viene algún valor raro, le asignamos 4 (World Mortality) por defecto
    df["id_fuente"] = df["fuente"].astype(str).str.strip().str.upper().map(mapa_fuente).fillna(4).astype(int)

    # 4. LOS MERGES (Calculando Foreign Keys)
    print_log("Cruzando Stage con Dimensiones (Calculando Foreign Keys)...")
    
    df = df.merge(dim_tiempo, on=["anio", "mes"], how="left")
    df = df.merge(dim_geo, on="iso3c", how="left")

    # Validación Estricta de Nulos
    nulos = df[["id_tiempo", "id_geografia_mundial"]].isna().sum().to_dict()
    print_log(f"Validación de Integridad Referencial (Nulos en FKs): {nulos}")
    
    # 5. CONSTRUCCIÓN FINAL DE LA TABLA DE HECHOS
    df_fact = pd.DataFrame({
        "id_tiempo":            df["id_tiempo"],
        "id_geografia_mundial": df["id_geografia_mundial"],
        "id_fuente":            df["id_fuente"],
        "deaths":               pd.to_numeric(df["deaths"], errors="coerce").fillna(0).astype(int),
        "time_unit":            df["time_unit"],
        "semana":               pd.to_numeric(df["semana"], errors="coerce").astype("Int64"),
        "periodo":              df["periodo"],
        "fecha_carga":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Evitar romper Constraints eliminando huérfanos si existieran
    df_fact = df_fact.dropna(subset=["id_tiempo", "id_geografia_mundial"])
    
    # Casting entero estricto
    df_fact["id_tiempo"] = df_fact["id_tiempo"].astype(int)
    df_fact["id_geografia_mundial"] = df_fact["id_geografia_mundial"].astype(int)
    df_fact["id_fuente"] = df_fact["id_fuente"].astype(int)

    # 6. INYECCIÓN
    _cargar_fact(engine_dw, df_fact, "LOCAL")

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("=" * 60)
    print_log("CARGA A DATA WAREHOUSE EXITOSA — fact_mortalidad_mundial")
    print_log("=" * 60)

if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Carga Fact Mortalidad Mundial")
    print_log("=" * 60)
    
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")
    
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_url:       raise EnvironmentError("DW_DB_URL no encontrada.")
    
    load_fact_mortalidad_mundial(sandbox_url, dw_url)