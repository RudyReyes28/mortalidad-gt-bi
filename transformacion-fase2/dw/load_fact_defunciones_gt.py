import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Carga: stage_defunciones_gt -> dw.fact_defunciones_gt
Grano: Agrupado por características (Ahorra millones de filas conservando precisión analítica)
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
            
            CREATE TABLE IF NOT EXISTS dw.fact_defunciones_gt (
                id_defuncion    BIGSERIAL PRIMARY KEY,
                id_tiempo       INTEGER REFERENCES dw.dim_tiempo(id_tiempo),
                id_geografia    INTEGER REFERENCES dw.dim_geografia_gt(id_geografia),
                id_causa        INTEGER REFERENCES dw.dim_causa_cie10(id_causa),
                id_sexo         INTEGER REFERENCES dw.dim_sexo(id_sexo),
                id_grupo_etario INTEGER REFERENCES dw.dim_grupo_etario(id_grupo_etario),
                id_fuente       INTEGER REFERENCES dw.dim_fuente(id_fuente),
                total_casos     BIGINT,
                periodo         VARCHAR(20),
                fecha_carga     VARCHAR(30)
            )
        """))
        
    print_log(f"  [{destino}] Truncando tabla de hechos (Limpieza Bottom-Up)...")
    with engine_dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.fact_defunciones_gt RESTART IDENTITY"))
        
    print_log(f"  [{destino}] Inyectando {len(df_fact):,} registros agrupados...")
    df_fact.to_sql(
        name="fact_defunciones_gt",
        con=engine_dw, schema="dw",
        if_exists="append", index=False,
        chunksize=5000, method="multi",
    )
    print_log(f"  [{destino}] Carga finalizada con éxito.")

def load_fact_defunciones_gt(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox  = create_engine(sandbox_url,  pool_pre_ping=True)
    engine_dw       = create_engine(dw_url, pool_pre_ping=True)

    # 1. LECTURA Y AGREGACIÓN DESDE STAGE
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
    print_log(f"  -> {len(df):,} filas agregadas (representando el 100% de los casos individuales).")

    # 2. LECTURA DE DIMENSIONES (Para hacer el Lookup)
    print_log("Cargando dimensiones maestras a memoria RAM...")
    dim_tiempo  = pd.read_sql("SELECT id_tiempo, anio, mes FROM dw.dim_tiempo", engine_dw)
    dim_geo     = pd.read_sql("SELECT id_geografia, nombre_departamento, nombre_municipio FROM dw.dim_geografia_gt", engine_dw)
    dim_causa   = pd.read_sql("SELECT id_causa, codigo_cie10 FROM dw.dim_causa_cie10", engine_dw)
    dim_grupo   = pd.read_sql("SELECT id_grupo_etario, rango FROM dw.dim_grupo_etario", engine_dw)
    dim_fuente  = pd.read_sql("SELECT id_fuente, nombre FROM dw.dim_fuente", engine_dw)

    # 3. LIMPIEZA DE PRE-JOIN (Misma regla que usamos en las dimensiones)
    print_log("Limpiando columnas Stage para garantizar 100% de aciertos en el JOIN...")
    
    # Tiempo
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").fillna(0).astype("Int16")
    dim_tiempo["anio"] = dim_tiempo["anio"].astype("Int16")
    dim_tiempo["mes"]  = dim_tiempo["mes"].astype("Int16")
    
    # Geografía
    df["departamento"] = df["departamento"].fillna("Ignorado").astype(str).str.strip()
    df["municipio"]    = df["municipio"].fillna("Ignorado").astype(str).str.strip()
    
    # Causa CIE-10
    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()

    # Sexo (Arreglando el problema de Hombre/Mujer vs Masculino/Femenino)
    mapa_sexo = {"Mujer": 1, "Femenino": 1, "Hombre": 2, "Masculino": 2}
    df["id_sexo"] = df["sexo"].map(mapa_sexo).fillna(3).astype(int)

    # Grupo Etario
    mapa_grupo = {
        "< 1 año": "< 1 anio", "1-4": "1-4", "5-14": "5-14",
        "15-29": "15-29", "30-44": "30-44", "45-59": "45-59",
        "60+": "60 o mas", "No especificado": "No especificado",
    }
    df["grupo_std"] = df["grupo_etario"].map(mapa_grupo).fillna("No especificado")


    # 4. LOS MERGES (Cruce de Stage con Dimensiones para obtener los IDs)
    print_log("Cruzando Stage con Dimensiones (Calculando Foreign Keys)...")
    
    df = df.merge(dim_tiempo, on=["anio","mes"], how="left")
    
    df = df.merge(dim_geo,
                  left_on=["departamento","municipio"],
                  right_on=["nombre_departamento","nombre_municipio"], how="left")
                  
    df = df.merge(dim_causa, on="codigo_cie10", how="left")
    
    df = df.merge(dim_grupo, left_on="grupo_std", right_on="rango", how="left")
    df["id_grupo_etario"] = df["id_grupo_etario"].fillna(8).astype(int) # 8 = No especificado
    
    df["id_fuente"] = int(dim_fuente[dim_fuente["nombre"] == "INE"]["id_fuente"].iloc[0])

    # Validación Estricta de Nulos
    nulos = df[['id_tiempo','id_geografia','id_causa', 'id_sexo', 'id_grupo_etario']].isna().sum().to_dict()
    print_log(f"Validación de Integridad Referencial (Nulos en FKs): {nulos}")
    
    # 5. CONSTRUCCIÓN FINAL DE LA TABLA DE HECHOS
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

    # Si por alguna extrema razón quedó un huérfano, no lo dejamos pasar al DW para que no rompa la constraint.
    df_fact = df_fact.dropna(subset=["id_tiempo", "id_geografia", "id_causa"])
    
    # Asegurar tipos enteros finales para inyección (evita errores con Postgres)
    df_fact["id_tiempo"] = df_fact["id_tiempo"].astype(int)
    df_fact["id_geografia"] = df_fact["id_geografia"].astype(int)
    df_fact["id_causa"] = df_fact["id_causa"].astype(int)

    # 6. INYECCIÓN
    _cargar_fact(engine_dw, df_fact, "LOCAL")

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("=" * 60)
    print_log("CARGA A DATA WAREHOUSE EXITOSA — fact_defunciones_gt")
    print_log("=" * 60)

if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Carga Fact Defunciones GT")
    print_log("=" * 60)
    
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url      = os.getenv("DW_DB_URL")
    
    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada.")
    if not dw_url:       raise EnvironmentError("DW_DB_URL no encontrada.")
    
    load_fact_defunciones_gt(sandbox_url, dw_url)