import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Módulo de Carga de Dimensiones (LOCAL): Stage -> Data Warehouse

Aplica la estrategia UPSERT (Insertar si no existe, Ignorar si existe) 
para preservar la Integridad Referencial y los IDs Subrogados.
Las relaciones (Foreign Keys) en las tablas de Hechos NO se rompen.

Dimensiones conformadas (7):
    - dw.dim_tiempo
    - dw.dim_sexo
    - dw.dim_grupo_etario
    - dw.dim_causa_cie10
    - dw.dim_geografia_gt
    - dw.dim_geografia_mundial
    - dw.dim_fuente
"""

# =====================================================================
# LIBRERÍA DE LOGGING LOCAL RÁPIDA
# =====================================================================
def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()

# ── Catálogos y Diccionarios ──────────────────────────────────────────────
CAPITULOS_CIE10 = {
    "A": "Enfermedades infecciosas y parasitarias", "B": "Enfermedades infecciosas y parasitarias",
    "C": "Tumores / Neoplasias", "D": "Tumores / Enfermedades de la sangre",
    "E": "Enfermedades endocrinas y metabolicas", "F": "Trastornos mentales",
    "G": "Enfermedades del sistema nervioso", "H": "Enfermedades del ojo y oido",
    "I": "Enfermedades del sistema circulatorio", "J": "Enfermedades del sistema respiratorio",
    "K": "Enfermedades del sistema digestivo", "L": "Enfermedades de la piel",
    "M": "Enfermedades del sistema musculoesqueletico", "N": "Enfermedades del sistema genitourinario",
    "O": "Embarazo, parto y puerperio", "P": "Afecciones del periodo perinatal",
    "Q": "Malformaciones congenitas", "R": "Sintomas y signos no clasificados",
    "S": "Traumatismos y envenenamientos", "T": "Traumatismos y envenenamientos",
    "U": "Codigos especiales (COVID-19)", "V": "Causas externas", "W": "Causas externas",
    "X": "Causas externas", "Y": "Causas externas", "Z": "Factores que influyen en el estado de salud",
}

CATEGORIAS_CIE10 = {
    "A": "Infecciosa", "B": "Infecciosa", "C": "Cronica", "D": "Cronica",
    "E": "Cronica",   "F": "Cronica",   "G": "Cronica", "H": "Cronica",
    "I": "Cronica",   "J": "Cronica",   "K": "Cronica", "L": "Cronica",
    "M": "Cronica",   "N": "Cronica",   "O": "Materna", "P": "Perinatal",
    "Q": "Congenita", "R": "Otra",      "S": "Externa", "T": "Externa",
    "U": "COVID-19",  "V": "Externa",   "W": "Externa", "X": "Externa",
    "Y": "Externa",   "Z": "Otra",
}

ISO2_A_ISO3 = {
    "GT": "GTM", "HN": "HND", "SV": "SLV", "NI": "NIC", "CR": "CRI",
    "PA": "PAN", "BZ": "BLZ", "PE": "PER", "BO": "BOL", "EC": "ECU",
    "BR": "BRA", "CO": "COL", "AR": "ARG", "CL": "CHL", "MX": "MEX",
    "US": "USA", "CA": "CAN", "ES": "ESP", "IT": "ITA", "GB": "GBR",
    "DE": "DEU", "FR": "FRA", "SE": "SWE", "PT": "PRT", "RU": "RUS",
    "UA": "UKR", "PL": "POL", "JP": "JPN", "KR": "KOR", "TR": "TUR",
    "AU": "AUS", "NZ": "NZL",
}

REGIONES_ISO3 = {
    "GTM": "Centroamerica", "HND": "Centroamerica", "SLV": "Centroamerica",
    "NIC": "Centroamerica", "CRI": "Centroamerica", "PAN": "Centroamerica",
    "BLZ": "Centroamerica", "PER": "Sudamerica",   "BRA": "Sudamerica",
    "COL": "Sudamerica",   "ECU": "Sudamerica",   "BOL": "Sudamerica",
    "ARG": "Sudamerica",   "CHL": "Sudamerica",   "USA": "Norteamerica",
    "MEX": "Norteamerica", "CAN": "Norteamerica", "ESP": "Europa",
    "ITA": "Europa",       "SWE": "Europa",       "GBR": "Europa",
    "DEU": "Europa",       "FRA": "Europa",       "PRT": "Europa",
    "RUS": "Europa",       "UKR": "Europa",       "POL": "Europa",
    "JPN": "Asia-Oceania", "KOR": "Asia-Oceania", "TUR": "Asia-Oceania",
    "AUS": "Asia-Oceania", "NZL": "Asia-Oceania",
}


# ── DDL: Definición Estricta de Tablas DW (Crear si no existen) ───────────
def _asegurar_esquema_dw(engine):
    """Crea el esquema y las tablas con Constraints Únicos para el Upsert."""
    print_log("Asegurando estructura DDL y Constraints en el esquema 'dw'...")
    ddl_sql = """
        CREATE SCHEMA IF NOT EXISTS dw;

        CREATE TABLE IF NOT EXISTS dw.dim_tiempo (
            id_tiempo SERIAL PRIMARY KEY,
            anio SMALLINT,
            mes SMALLINT,
            trimestre SMALLINT,
            periodo VARCHAR(50),
            UNIQUE (anio, mes)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_geografia_gt (
            id_geografia SERIAL PRIMARY KEY,
            nombre_departamento VARCHAR(150),
            nombre_municipio VARCHAR(150),
            region VARCHAR(100),
            pais VARCHAR(100),
            iso3c VARCHAR(3),
            fecha_inicio_vigencia DATE,
            fecha_fin_vigencia DATE,
            es_version_actual BOOLEAN,
            version INT,
            UNIQUE (nombre_departamento, nombre_municipio)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_geografia_mundial (
            id_geografia_mundial SERIAL PRIMARY KEY,
            nombre_pais VARCHAR(150),
            iso3c VARCHAR(3) UNIQUE,
            iso2 VARCHAR(2),
            region VARCHAR(100)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_causa_cie10 (
            id_causa SERIAL PRIMARY KEY,
            codigo_cie10 VARCHAR(10) UNIQUE,
            descripcion TEXT,          -- Cambiado a TEXT para evitar cortes en diagnósticos largos
            capitulo_cie10 VARCHAR(255),
            categoria VARCHAR(100)
        );

        -- Catálogos Fijos (IDs definidos en código)
        CREATE TABLE IF NOT EXISTS dw.dim_sexo (
            id_sexo INT PRIMARY KEY,
            codigo VARCHAR(5) UNIQUE,
            descripcion VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS dw.dim_grupo_etario (
            id_grupo_etario INT PRIMARY KEY,
            rango VARCHAR(50) UNIQUE,
            edad_min INT,
            edad_max INT
        );

        CREATE TABLE IF NOT EXISTS dw.dim_fuente (
            id_fuente INT PRIMARY KEY,
            nombre VARCHAR(100) UNIQUE,
            tipo VARCHAR(50),
            pais_cobertura VARCHAR(100),
            cobertura_temporal VARCHAR(50)
        );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl_sql))

# ── Función Maestra de Upsert ─────────────────────────────────────────────
def _upsert_dimension(engine, df: pd.DataFrame, table_name: str, unique_keys: list):
    if df.empty:
        print_log(f"  -> {table_name} sin datos para procesar.")
        return

    temp_table = f"temp_{table_name}"
    
    # Asegurarnos de que no exista una tabla temporal de una ejecución fallida anterior
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS dw.{temp_table}"))
        
    # 1. Cargar datos a tabla temporal
    df.to_sql(temp_table, engine, schema="dw", if_exists="replace", index=False)

    # 2. Construir el UPSERT dinámico
    cols_insert = ", ".join(df.columns)
    cols_conflict = ", ".join(unique_keys)

    sql_upsert = f"""
        INSERT INTO dw.{table_name} ({cols_insert})
        SELECT {cols_insert} FROM dw.{temp_table}
        ON CONFLICT ({cols_conflict}) DO NOTHING;
    """
    
    with engine.begin() as conn:
        conn.execute(text(sql_upsert))
        conn.execute(text(f"DROP TABLE IF EXISTS dw.{temp_table}"))
        
    print_log(f"  -> Upsert completado exitosamente en dw.{table_name}")

# ── Construcción de Dimensiones Dinámicas (Postgres asigna el ID) ──────────
def _build_dim_tiempo(engine_sandbox) -> pd.DataFrame:
    print_log("Analizando dim_tiempo desde Stage...")
    queries = [
        "SELECT DISTINCT anio, 0::smallint AS mes FROM stage.stage_mspas_mec WHERE anio IS NOT NULL",
        "SELECT DISTINCT anio, mes FROM stage.stage_mspas_covid WHERE anio IS NOT NULL",
        "SELECT DISTINCT anio_ocurrencia AS anio, mes_ocurrencia AS mes FROM stage.stage_defunciones_gt WHERE anio_ocurrencia IS NOT NULL",
        "SELECT DISTINCT anio, mes FROM stage.stage_mortalidad_mundial WHERE anio IS NOT NULL AND mes IS NOT NULL",
        "SELECT DISTINCT anio, 0::smallint AS mes FROM stage.stage_mortalidad_mundial WHERE anio IS NOT NULL AND time_unit = 'annual'",
        "SELECT DISTINCT anio, mes FROM stage.stage_covid_mundial WHERE anio IS NOT NULL",
    ]

    dfs = []
    for q in queries:
        try:
            dfs.append(pd.read_sql(q, engine_sandbox))
        except Exception as e:
            pass

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True).drop_duplicates()
    df.columns = ["anio", "mes"]
    
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"], errors="coerce").fillna(0).astype("Int16") # 0 = anual

    # Convertir forzosamente el trimestre a Int16 para evitar DatatypeMismatch
    df["trimestre"] = df["mes"].apply(lambda m: pd.NA if m == 0 else int((m - 1) // 3 + 1)).astype("Int16")
    df["periodo"]   = df["anio"].apply(lambda a: "pre-COVID" if a < 2020 else ("COVID" if a <= 2021 else "post-COVID"))
    
    df = df.drop_duplicates().reset_index(drop=True)
    return df

def _build_dim_geografia_gt(engine_sandbox) -> pd.DataFrame:
    print_log("Analizando dim_geografia_gt desde Stage...")
    q = """
        SELECT DISTINCT nombre_depto_ocurrencia AS nombre_departamento, nombre_muni_ocurrencia AS nombre_municipio
        FROM stage.stage_defunciones_gt WHERE nombre_depto_ocurrencia IS NOT NULL
        UNION
        SELECT DISTINCT departamento AS nombre_departamento, municipio AS nombre_municipio
        FROM stage.stage_mspas_mec WHERE departamento IS NOT NULL
        UNION
        SELECT DISTINCT departamento AS nombre_departamento, municipio AS nombre_municipio
        FROM stage.stage_mspas_covid WHERE departamento IS NOT NULL
    """
    try:
        df = pd.read_sql(q, engine_sandbox)
    except:
        return pd.DataFrame()

    df.columns = ["nombre_departamento", "nombre_municipio"]
    
    # Limpieza básica para consistencia
    df["nombre_departamento"] = df["nombre_departamento"].fillna("Ignorado").astype(str).str.strip()
    df["nombre_municipio"] = df["nombre_municipio"].fillna("Ignorado").astype(str).str.strip()
    df = df.drop_duplicates().reset_index(drop=True)
    
    df["region"]                = "Guatemala"
    df["pais"]                  = "Guatemala"
    df["iso3c"]                 = "GTM"
    
    # Asegurar el uso de un objeto Datetime para mapearlo limpiamente a un DATE en la BBDD
    df["fecha_inicio_vigencia"] = pd.to_datetime("2015-01-01") 
    df["fecha_fin_vigencia"]    = pd.to_datetime(None) # pd.to_datetime(None) genera NaT, forzando a crear un campo Time/Date
    
    df["es_version_actual"]     = True
    df["version"]               = 1

    return df

def _build_dim_geografia_mundial(engine_sandbox) -> pd.DataFrame:
    print_log("Analizando dim_geografia_mundial desde Stage...")
    q_mundial = "SELECT DISTINCT country_name AS nombre_pais, iso3c FROM stage.stage_mortalidad_mundial WHERE iso3c IS NOT NULL"
    q_covid = "SELECT DISTINCT country_name AS nombre_pais, country_code AS iso2 FROM stage.stage_covid_mundial WHERE country_code IS NOT NULL"

    dfs = []
    try:
        df_m = pd.read_sql(q_mundial, engine_sandbox)
        df_m["iso2"] = df_m["iso3c"].str.strip().str.upper().map({v: k for k, v in ISO2_A_ISO3.items()})
        dfs.append(df_m)
    except: pass

    try:
        df_c = pd.read_sql(q_covid, engine_sandbox)
        df_c["iso3c"] = df_c["iso2"].str.strip().str.upper().map(ISO2_A_ISO3)
        dfs.append(df_c)
    except: pass

    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame(columns=["nombre_pais", "iso3c", "iso2"])
    if df.empty: return df

    df["iso3c"] = df["iso3c"].str.strip().str.upper()
    df = df.dropna(subset=["iso3c"]).drop_duplicates(subset=["iso3c"]).reset_index(drop=True)
    df["region"] = df["iso3c"].map(REGIONES_ISO3).fillna("Otro")
    
    return df[["nombre_pais", "iso3c", "iso2", "region"]]

def _build_dim_causa_cie10(engine_sandbox) -> pd.DataFrame:
    print_log("Analizando dim_causa_cie10 desde Stage...")
    q = """
        SELECT DISTINCT codigo_cie10, diagnostico AS descripcion
        FROM stage.stage_mspas_mec WHERE codigo_cie10 IS NOT NULL
        UNION
        SELECT DISTINCT codigo_cie10, descripcion_causa AS descripcion
        FROM stage.stage_defunciones_gt WHERE codigo_cie10 IS NOT NULL
    """
    try:
        df = pd.read_sql(q, engine_sandbox)
    except:
        return pd.DataFrame()

    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()
    df["descripcion"]  = df["descripcion"].fillna("Sin descripcion")

    especiales = pd.DataFrame([
        {"codigo_cie10": "U071", "descripcion": "COVID-19 identificado"},
        {"codigo_cie10": "ZGEN", "descripcion": "Mortalidad general sin causa especifica"},
    ])
    df = pd.concat([df, especiales], ignore_index=True).drop_duplicates(subset=["codigo_cie10"])

    df["capitulo_cie10"] = df["codigo_cie10"].apply(lambda c: CAPITULOS_CIE10.get(c[0].upper(), "No especificado") if len(c) > 0 else "No especificado")
    df["categoria"] = df["codigo_cie10"].apply(lambda c: CATEGORIAS_CIE10.get(c[0].upper(), "Otra") if len(c) > 0 else "Otra")

    return df.reset_index(drop=True)

# ── Construcción de Dimensiones Estáticas (Python asigna el ID explícito) ───
def _build_dim_sexo() -> pd.DataFrame:
    return pd.DataFrame([
        {"id_sexo": 1, "codigo": "F", "descripcion": "Femenino"},
        {"id_sexo": 2, "codigo": "M", "descripcion": "Masculino"},
        {"id_sexo": 3, "codigo": "N", "descripcion": "No especificado"},
    ])

def _build_dim_grupo_etario() -> pd.DataFrame:
    return pd.DataFrame([
        {"id_grupo_etario": 1, "rango": "< 1 anio",       "edad_min": 0,    "edad_max": 0},
        {"id_grupo_etario": 2, "rango": "1-4",            "edad_min": 1,    "edad_max": 4},
        {"id_grupo_etario": 3, "rango": "5-14",           "edad_min": 5,    "edad_max": 14},
        {"id_grupo_etario": 4, "rango": "15-29",          "edad_min": 15,   "edad_max": 29},
        {"id_grupo_etario": 5, "rango": "30-44",          "edad_min": 30,   "edad_max": 44},
        {"id_grupo_etario": 6, "rango": "45-59",          "edad_min": 45,   "edad_max": 59},
        {"id_grupo_etario": 7, "rango": "60 o mas",       "edad_min": 60,   "edad_max": None},
        {"id_grupo_etario": 8, "rango": "No especificado","edad_min": None, "edad_max": None},
    ])

def _build_dim_fuente() -> pd.DataFrame:
    return pd.DataFrame([
        {"id_fuente": 1, "nombre": "INE",               "tipo": "Nacional",      "pais_cobertura": "Guatemala",    "cobertura_temporal": "2018-2024"},
        {"id_fuente": 2, "nombre": "MSPAS_MEC",         "tipo": "Institucional", "pais_cobertura": "Guatemala",    "cobertura_temporal": "2012-2024"},
        {"id_fuente": 3, "nombre": "MSPAS_COVID",       "tipo": "Institucional", "pais_cobertura": "Guatemala",    "cobertura_temporal": "2020-2024"},
        {"id_fuente": 4, "nombre": "WORLD_MORTALITY",   "tipo": "Internacional", "pais_cobertura": "Global",       "cobertura_temporal": "2015-2024"},
        {"id_fuente": 5, "nombre": "CENTROAMERICA_RDS", "tipo": "Internacional", "pais_cobertura": "Centroamerica","cobertura_temporal": "2000-2023"},
        {"id_fuente": 6, "nombre": "OMS_COVID_MUNDIAL", "tipo": "Internacional", "pais_cobertura": "Global",       "cobertura_temporal": "2020-2024"},
    ])

# ── Ejecución Principal ───────────────────────────────────────────────────
def load_dimensions(sandbox_url: str, dw_url: str):
    print_log("Conectando a las bases de datos...")
    engine_sandbox = create_engine(sandbox_url, pool_pre_ping=True)
    engine_dw = create_engine(dw_url, pool_pre_ping=True)
    
    # 1. Asegurar Estructura en DW
    _asegurar_esquema_dw(engine_dw)

    # 2. Extraer y Construir desde Sandbox
    dim_tiempo             = _build_dim_tiempo(engine_sandbox)
    dim_geografia_gt       = _build_dim_geografia_gt(engine_sandbox)
    dim_geografia_mundial  = _build_dim_geografia_mundial(engine_sandbox)
    dim_causa_cie10        = _build_dim_causa_cie10(engine_sandbox)
    dim_sexo               = _build_dim_sexo()
    dim_grupo_etario       = _build_dim_grupo_etario()
    dim_fuente             = _build_dim_fuente()

    # 3. UPSERT a Data Warehouse
    print_log("=" * 60)
    print_log("INICIANDO UPSERT A DIMENSIONES...")
    print_log("=" * 60)

    # Las llaves dinámicas usan las columnas de negocio (Postgres asignará los IDs si son nuevos)
    _upsert_dimension(engine_dw, dim_tiempo, "dim_tiempo", ["anio", "mes"])
    _upsert_dimension(engine_dw, dim_geografia_gt, "dim_geografia_gt", ["nombre_departamento", "nombre_municipio"])
    _upsert_dimension(engine_dw, dim_geografia_mundial, "dim_geografia_mundial", ["iso3c"])
    _upsert_dimension(engine_dw, dim_causa_cie10, "dim_causa_cie10", ["codigo_cie10"])

    # Las estáticas utilizan sus IDs fijos que enviamos desde Pandas
    _upsert_dimension(engine_dw, dim_sexo, "dim_sexo", ["id_sexo"])
    _upsert_dimension(engine_dw, dim_grupo_etario, "dim_grupo_etario", ["id_grupo_etario"])
    _upsert_dimension(engine_dw, dim_fuente, "dim_fuente", ["id_fuente"])

    engine_sandbox.dispose()
    engine_dw.dispose()
    print_log("======================================================")
    print_log("CARGA DE DIMENSIONES (IDEMPOTENTE) COMPLETADA CON ÉXITO")
    print_log("======================================================")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB LOCAL: Creación y Upsert de Dimensiones DW")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    sandbox_url = os.getenv("SANDBOX_DB_URL")
    dw_url = os.getenv("DW_DB_URL") 
    
    if not sandbox_url:
        raise EnvironmentError("Variable de entorno SANDBOX_DB_URL no encontrada.")
    if not dw_url:
        raise EnvironmentError("Variable de entorno DW_DB_URL no encontrada.")

    load_dimensions(sandbox_url, dw_url)