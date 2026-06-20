import sys
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_mspas_mec -> dw.fact_morbimortalidad_mec
Grano: Agregado por año, departamento, municipio, causa, grupo y sexo (>= 2015)
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
            
            CREATE TABLE IF NOT EXISTS dw.fact_morbimortalidad_mec (
                id_fact          BIGSERIAL PRIMARY KEY,
                id_tiempo        INTEGER REFERENCES dw.dim_tiempo(id_tiempo),
                id_geografia     INTEGER REFERENCES dw.dim_geografia_gt(id_geografia),
                id_causa         INTEGER REFERENCES dw.dim_causa_cie10(id_causa),
                id_grupo_etario  INTEGER REFERENCES dw.dim_grupo_etario(id_grupo_etario),
                id_sexo          INTEGER REFERENCES dw.dim_sexo(id_sexo),
                id_fuente        INTEGER REFERENCES dw.dim_fuente(id_fuente),
                casos            BIGINT,
                periodo          VARCHAR(20),
                fecha_carga      VARCHAR(30)
            )
        """))
        
    print_log(f"  [{destino}] Truncando tabla de hechos (Limpieza Bottom-Up)...")
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_morbimortalidad_mec RESTART IDENTITY"))
        
    print_log(f"  [{destino}] Inyectando {len(df_fact):,} registros agrupados...")
    df_fact.to_sql(
        name="fact_morbimortalidad_mec",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000, method="multi",
    )
    print_log(f"  [{destino}] Carga finalizada con éxito.")

def _mapear_grupo_etario_mec(val) -> str:
    """
    Toma rangos del MEC (ej. '45 a 49 años', '70+') y los convierte
    a los 8 grupos estándar de nuestra dimensión de Data Warehouse.
    """
    val_str = str(val).strip().lower()
    
    if "< 1" in val_str or "menor" in val_str: 
        return "< 1 anio"
        
    nums = re.findall(r'\d+', val_str)
    if not nums: 
        return "No especificado"
        
    min_age = int(nums[0])
    
    if min_age < 1:   return "< 1 anio"
    elif min_age < 5:  return "1-4"
    elif min_age < 15: return "5-14"
    elif min_age < 30: return "15-29"
    elif min_age < 45: return "30-44"
    elif min_age < 60: return "45-59"
    else:              return "60 o mas"

def load_fact_morbimortalidad_mec(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw       = create_engine(dw_url, pool_pre_ping=True)

    # 1. LECTURA Y AGREGACIÓN DESDE STAGE (Con Filtro 2015)
    print_log("Leyendo y agregando stage.stage_mspas_mec (Solo 2015 en adelante)...")
    query = """
        SELECT
            anio,
            departamento,
            municipio,
            codigo_cie10,
            grupo_etario,
            sexo,
            periodo,
            SUM(casos) AS casos
        FROM stage.stage_mspas_mec
        WHERE anio IS NOT NULL AND anio >= 2015
        GROUP BY anio, departamento, municipio, codigo_cie10, grupo_etario, sexo, periodo
    """
    df = pd.read_sql(query, engine_sandbox)
    print_log(f"  -> {len(df):,} filas agregadas desde el Stage (2015+).")

    # 2. LECTURA DE DIMENSIONES (Para hacer el Lookup)
    print_log("Cargando dimensiones maestras a memoria RAM...")
    dim_tiempo   = pd.read_sql("SELECT id_tiempo, anio, mes FROM dw.dim_tiempo", engine_dw)
    dim_geo      = pd.read_sql("SELECT id_geografia, nombre_departamento, nombre_municipio FROM dw.dim_geografia_gt", engine_dw)
    dim_causa    = pd.read_sql("SELECT id_causa, codigo_cie10 FROM dw.dim_causa_cie10", engine_dw)
    dim_etario   = pd.read_sql("SELECT id_grupo_etario, rango FROM dw.dim_grupo_etario", engine_dw)

    # 3. LIMPIEZA DE PRE-JOIN (Alineando llaves)
    print_log("Alineando llaves para garantizar exactitud en el JOIN...")
    
    # Tiempo: Convertir el mes a 0 para que haga match con los registros anuales de la dimensión
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = 0
    df["mes"]  = df["mes"].astype("Int16")
    dim_tiempo["anio"] = dim_tiempo["anio"].astype("Int16")
    dim_tiempo["mes"]  = dim_tiempo["mes"].astype("Int16")
    
    # Geografía: Limpieza estricta de espacios
    df["departamento"] = df["departamento"].fillna("Ignorado").astype(str).str.strip()
    df["municipio"]    = df["municipio"].fillna("Ignorado").astype(str).str.strip()
    
    # Causa CIE-10
    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()

    # Sexo: Mapeo manual directo a ID
    mapa_sexo = {"Mujer": 1, "Femenino": 1, "Hombre": 2, "Masculino": 2}
    df["id_sexo"] = df["sexo"].map(mapa_sexo).fillna(3).astype(int)

    # Grupo Etario: Transformación mediante Regex
    df["rango_std"] = df["grupo_etario"].apply(_mapear_grupo_etario_mec)

    # Fuente: Asignación fija para el MSPAS MEC (ID 2)
    df["id_fuente"] = 2

    # 4. LOS MERGES (Calculando Foreign Keys)
    print_log("Cruzando Stage con Dimensiones (Calculando Foreign Keys)...")
    
    df = df.merge(dim_tiempo, on=["anio", "mes"], how="left")
    
    df = df.merge(dim_geo,
                  left_on=["departamento", "municipio"],
                  right_on=["nombre_departamento", "nombre_municipio"], how="left")
                  
    df = df.merge(dim_causa, on="codigo_cie10", how="left")
    
    df = df.merge(dim_etario, left_on="rango_std", right_on="rango", how="left")
    df["id_grupo_etario"] = df["id_grupo_etario"].fillna(8).astype(int) # 8 = No especificado

    # Validación Estricta de Nulos
    nulos = df[["id_tiempo", "id_geografia", "id_causa", "id_grupo_etario"]].isna().sum().to_dict()
    print_log(f"Validación de Integridad Referencial (Nulos en FKs): {nulos}")
    
    # 5. CONSTRUCCIÓN FINAL DE LA TABLA DE HECHOS
    df_fact = pd.DataFrame({
        "id_tiempo":       df["id_tiempo"],
        "id_geografia":    df["id_geografia"],
        "id_causa":        df["id_causa"],
        "id_grupo_etario": df["id_grupo_etario"],
        "id_sexo":         df["id_sexo"],
        "id_fuente":       df["id_fuente"],
        "casos":           pd.to_numeric(df["casos"], errors="coerce").fillna(0).astype(int),
        "periodo":         df["periodo"],
        "fecha_carga":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Evitar romper Constraints eliminando huérfanos si existieran
    df_fact = df_fact.dropna(subset=["id_tiempo", "id_geografia", "id_causa"])
    
    # Casting entero estricto para las Foreign Keys
    df_fact["id_tiempo"]       = df_fact["id_tiempo"].astype(int)
    df_fact["id_geografia"]    = df_fact["id_geografia"].astype(int)
    df_fact["id_causa"]        = df_fact["id_causa"].astype(int)

    # 6. INYECCIÓN
    _cargar_fact(engine_dw, df_fact, "LOCAL")

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("=" * 60)
    print_log("CARGA A DATA WAREHOUSE EXITOSA — fact_morbimortalidad_mec")
    print_log("=" * 60)

if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Carga Fact Morbimortalidad MEC")
    print_log("=" * 60)
    
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")
    
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_url:       raise EnvironmentError("DW_DB_URL no encontrada.")
    
    load_fact_morbimortalidad_mec(sandbox_url, dw_url)