import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Sincronización (Réplica): Nube (AWS RDS) -> Local (PostgreSQL)
Extrae datos en chunks desde el DW en la nube y los inserta en el DW local,
respetando el esquema Galaxy y la integridad referencial.
"""

def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()

# El orden es crucial para las Inserciones: Dimensiones primero, luego Hechos.
TABLAS_DIMENSIONES = [
    "dim_causa_cie10",
    "dim_fuente",
    "dim_geografia_gt",
    "dim_geografia_mundial",
    "dim_grupo_etario",
    "dim_sexo",
    "dim_tiempo"
]

TABLAS_HECHOS = [
    "fact_covid_mundial",
    "fact_defunciones_gt",
    "fact_morbimortalidad_mec",
    "fact_mortalidad_covid_gt",
    "fact_mortalidad_mundial"
]

def inicializar_esquema_local(engine_local):
    """Crea el esquema exacto en la base de datos local si es la primera vez que se corre."""
    print_log("Verificando/Creando esquema DDL en el entorno local...")
    
    ddl_sql = """
        CREATE SCHEMA IF NOT EXISTS dw;

        -- DIMENSIONES
        CREATE TABLE IF NOT EXISTS dw.dim_causa_cie10 (
            id_causa serial NOT NULL PRIMARY KEY,
            codigo_cie10 character varying(10) UNIQUE,
            descripcion text,
            capitulo_cie10 character varying(255),
            categoria character varying(100)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_fuente (
            id_fuente integer NOT NULL PRIMARY KEY,
            nombre character varying(100) UNIQUE,
            tipo character varying(50),
            pais_cobertura character varying(100),
            cobertura_temporal character varying(50)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_geografia_gt (
            id_geografia serial NOT NULL PRIMARY KEY,
            nombre_departamento character varying(150),
            nombre_municipio character varying(150),
            region character varying(100),
            pais character varying(100),
            iso3c character varying(3),
            fecha_inicio_vigencia date,
            fecha_fin_vigencia date,
            es_version_actual boolean,
            version integer,
            UNIQUE (nombre_departamento, nombre_municipio)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_geografia_mundial (
            id_geografia_mundial serial NOT NULL PRIMARY KEY,
            nombre_pais character varying(150),
            iso3c character varying(3) UNIQUE,
            iso2 character varying(2),
            region character varying(100)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_grupo_etario (
            id_grupo_etario integer NOT NULL PRIMARY KEY,
            rango character varying(50) UNIQUE,
            edad_min integer,
            edad_max integer
        );

        CREATE TABLE IF NOT EXISTS dw.dim_sexo (
            id_sexo integer NOT NULL PRIMARY KEY,
            codigo character varying(5) UNIQUE,
            descripcion character varying(50)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_tiempo (
            id_tiempo serial NOT NULL PRIMARY KEY,
            anio smallint,
            mes smallint,
            trimestre smallint,
            periodo character varying(50),
            UNIQUE (anio, mes)
        );

        -- TABLAS DE HECHOS
        CREATE TABLE IF NOT EXISTS dw.fact_covid_mundial (
            id_fact bigserial NOT NULL PRIMARY KEY,
            id_tiempo integer REFERENCES dw.dim_tiempo (id_tiempo),
            id_geografia_mundial integer REFERENCES dw.dim_geografia_mundial (id_geografia_mundial),
            id_fuente integer REFERENCES dw.dim_fuente (id_fuente),
            new_cases_mes bigint,
            new_deaths_mes bigint,
            cum_cases_fin bigint,
            cum_deaths_fin bigint,
            semanas_reporte integer,
            periodo character varying(20),
            fecha_carga character varying(30)
        );

        CREATE TABLE IF NOT EXISTS dw.fact_defunciones_gt (
            id_defuncion bigserial NOT NULL PRIMARY KEY,
            id_tiempo integer REFERENCES dw.dim_tiempo (id_tiempo),
            id_geografia integer REFERENCES dw.dim_geografia_gt (id_geografia),
            id_causa integer REFERENCES dw.dim_causa_cie10 (id_causa),
            id_sexo integer REFERENCES dw.dim_sexo (id_sexo),
            id_grupo_etario integer REFERENCES dw.dim_grupo_etario (id_grupo_etario),
            id_fuente integer REFERENCES dw.dim_fuente (id_fuente),
            total_casos bigint,
            periodo character varying(20),
            fecha_carga character varying(30)
        );

        CREATE TABLE IF NOT EXISTS dw.fact_morbimortalidad_mec (
            id_fact bigserial NOT NULL PRIMARY KEY,
            id_tiempo integer REFERENCES dw.dim_tiempo (id_tiempo),
            id_geografia integer REFERENCES dw.dim_geografia_gt (id_geografia),
            id_causa integer REFERENCES dw.dim_causa_cie10 (id_causa),
            id_grupo_etario integer REFERENCES dw.dim_grupo_etario (id_grupo_etario),
            id_sexo integer REFERENCES dw.dim_sexo (id_sexo),
            id_fuente integer REFERENCES dw.dim_fuente (id_fuente),
            casos bigint,
            periodo character varying(20),
            fecha_carga character varying(30)
        );

        CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_covid_gt (
            id_fact bigserial NOT NULL PRIMARY KEY,
            id_tiempo integer REFERENCES dw.dim_tiempo (id_tiempo),
            id_geografia integer REFERENCES dw.dim_geografia_gt (id_geografia),
            id_causa integer REFERENCES dw.dim_causa_cie10 (id_causa),
            id_fuente integer REFERENCES dw.dim_fuente (id_fuente),
            fallecidos bigint,
            tasa_por_100k numeric(10, 4),
            periodo character varying(20),
            fecha_carga character varying(30)
        );

        CREATE TABLE IF NOT EXISTS dw.fact_mortalidad_mundial (
            id_fact bigserial NOT NULL PRIMARY KEY,
            id_tiempo integer REFERENCES dw.dim_tiempo (id_tiempo),
            id_geografia_mundial integer REFERENCES dw.dim_geografia_mundial (id_geografia_mundial),
            id_fuente integer REFERENCES dw.dim_fuente (id_fuente),
            deaths bigint,
            time_unit character varying(20),
            semana integer,
            periodo character varying(20),
            fecha_carga character varying(30)
        );
    """
    with engine_local.begin() as conn:
        conn.execute(text(ddl_sql))
    print_log("Esquema local preparado.")

def vaciar_tablas_locales(engine_local):
    """Limpia el repositorio local antes de inyectar la réplica."""
    print_log("Truncando tablas locales en Cascada...")
    todas_las_tablas = ", ".join([f"dw.{t}" for t in TABLAS_HECHOS + TABLAS_DIMENSIONES])
    
    with engine_local.begin() as conn:
        # CASCADE elimina los datos de las tablas de hechos si intentamos vaciar las dimensiones
        conn.execute(text(f"TRUNCATE TABLE {todas_las_tablas} RESTART IDENTITY CASCADE;"))
    print_log("Tablas locales limpias y listas.")

def replicar_tabla(engine_cloud, engine_local, tabla):
    print_log(f"  -> Replicando {tabla}...")
    
    # Chunksize = 50,000 para no agotar la RAM de la computadora local
    chunk_size = 50000
    total_filas = 0
    
    # Extraer de la Nube (Generador iterativo)
    try:
        chunks = pd.read_sql(f"SELECT * FROM dw.{tabla}", engine_cloud, chunksize=chunk_size)
        
        # Inyectar Localmente
        for chunk in chunks:
            chunk.to_sql(
                name=tabla,
                con=engine_local,
                schema="dw",
                if_exists="append", # El append es clave porque ya creamos la tabla con Primary Keys
                index=False,
                method="multi"
            )
            total_filas += len(chunk)
            
        print_log(f"     [+] Se copiaron {total_filas:,} filas de {tabla}.")
    except Exception as e:
        print_log(f"     [!] Error copiando {tabla}: {e}")

def run_sync(cloud_url: str, local_url: str):
    print_log("Conectando a los Data Warehouses...")
    engine_cloud = create_engine(cloud_url, pool_pre_ping=True)
    engine_local = create_engine(local_url, pool_pre_ping=True)

    # 1. Preparación
    inicializar_esquema_local(engine_local)
    vaciar_tablas_locales(engine_local)

    # 2. Replicación (Respetando el orden lógico)
    print_log("\n--- INICIANDO COPIA DE DIMENSIONES ---")
    for tabla in TABLAS_DIMENSIONES:
        replicar_tabla(engine_cloud, engine_local, tabla)

    print_log("\n--- INICIANDO COPIA DE HECHOS ---")
    for tabla in TABLAS_HECHOS:
        replicar_tabla(engine_cloud, engine_local, tabla)

    engine_cloud.dispose()
    engine_local.dispose()
    print_log("\n=================================================")
    print_log("RÉPLICA CLOUD -> LOCAL COMPLETADA EXITOSAMENTE")
    print_log("=================================================")

if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Réplica de Data Warehouse")
    print_log("=" * 60)
    
    # Cargar variables de entorno
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists(): 
        env_path = Path(".env")
        
    load_dotenv(env_path)
    
    cloud_url = os.getenv("DW_CLOUD_URL")
    local_url = os.getenv("DW_DB_URL")
    
    if not cloud_url: raise EnvironmentError("Variable DW_CLOUD_URL no encontrada en .env")
    if not local_url: raise EnvironmentError("Variable DW_DB_URL no encontrada en .env")
    
    run_sync(cloud_url, local_url)