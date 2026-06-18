import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Script de creación y carga de dimensiones del Data Warehouse.
(create_dimensions.py)

Lee las tablas Stage para construir los catálogos de cada dimensión
y los carga en el schema 'dw' de ambos destinos:
    - DW local    (DW_DB_URL)
    - DW en nube  (DW_CLOUD_URL)

IMPORTANTE: Este script debe ejecutarse ANTES de cualquier load_fact_*.py.

Dimensiones que crea:
    dw.dim_tiempo        — años, meses, trimestres y períodos
    dw.dim_geografia     — departamentos, municipios, países y regiones
    dw.dim_causa_cie10   — códigos CIE-10, descripciones y capítulos
    dw.dim_sexo          — catálogo de sexo estandarizado
    dw.dim_grupo_etario  — rangos de edad homologados
    dw.dim_fuente        — sistemas de origen de los datos
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


REGIONES = {
    "GTM": "Guatemala", "HND": "Centroamerica", "SLV": "Centroamerica",
    "NIC": "Centroamerica", "CRI": "Centroamerica", "PAN": "Centroamerica",
    "BLZ": "Centroamerica", "PER": "Sudamerica", "BRA": "Sudamerica",
    "COL": "Sudamerica", "ECU": "Sudamerica", "BOL": "Sudamerica",
    "ARG": "Sudamerica", "CHL": "Sudamerica", "USA": "Norteamerica",
    "MEX": "Norteamerica", "CAN": "Norteamerica", "ESP": "Europa",
    "ITA": "Europa", "SWE": "Europa", "GBR": "Europa", "DEU": "Europa",
    "FRA": "Europa", "PRT": "Europa", "JPN": "Asia-Oceania",
    "KOR": "Asia-Oceania", "NZL": "Asia-Oceania", "AUS": "Asia-Oceania",
}

CAPITULOS_CIE10 = {
    "A": "Enfermedades infecciosas y parasitarias",
    "B": "Enfermedades infecciosas y parasitarias",
    "C": "Tumores / Neoplasias",
    "D": "Tumores / Enfermedades de la sangre",
    "E": "Enfermedades endocrinas y metabolicas",
    "F": "Trastornos mentales",
    "G": "Enfermedades del sistema nervioso",
    "H": "Enfermedades del ojo y oido",
    "I": "Enfermedades del sistema circulatorio",
    "J": "Enfermedades del sistema respiratorio",
    "K": "Enfermedades del sistema digestivo",
    "L": "Enfermedades de la piel",
    "M": "Enfermedades del sistema musculoesqueletico",
    "N": "Enfermedades del sistema genitourinario",
    "O": "Embarazo, parto y puerperio",
    "P": "Afecciones del periodo perinatal",
    "Q": "Malformaciones congenitas",
    "R": "Sintomas y signos no clasificados",
    "S": "Traumatismos y envenenamientos",
    "T": "Traumatismos y envenenamientos",
    "U": "Codigos especiales (COVID-19)",
    "V": "Causas externas", "W": "Causas externas",
    "X": "Causas externas", "Y": "Causas externas",
    "Z": "Factores que influyen en el estado de salud",
}

CATEGORIAS_CIE10 = {
    "A": "Infecciosa", "B": "Infecciosa", "C": "Cronica", "D": "Cronica",
    "E": "Cronica", "F": "Cronica", "G": "Cronica", "H": "Cronica",
    "I": "Cronica", "J": "Cronica", "K": "Cronica", "L": "Cronica",
    "M": "Cronica", "N": "Cronica", "O": "Materna", "P": "Perinatal",
    "Q": "Congenita", "R": "Otra", "S": "Externa", "T": "Externa",
    "U": "COVID-19", "V": "Externa", "W": "Externa", "X": "Externa",
    "Y": "Externa", "Z": "Otra",
}


def _build_dim_tiempo(engine_sandbox) -> pd.DataFrame:
    print_log("Construyendo dim_tiempo...")
    q_mec     = "SELECT DISTINCT anio, NULL::smallint AS mes FROM stage.stage_mspas_mec WHERE anio IS NOT NULL"
    q_covid   = "SELECT DISTINCT anio, mes FROM stage.stage_mspas_covid WHERE anio IS NOT NULL"
    q_ine     = "SELECT DISTINCT anio_ocurrencia AS anio, mes_ocurrencia AS mes FROM stage.stage_defunciones_gt WHERE anio_ocurrencia IS NOT NULL"
    q_mundial = "SELECT DISTINCT anio, NULL::smallint AS mes FROM stage.stage_mortalidad_mundial WHERE anio IS NOT NULL"

    dfs = []
    for q in [q_mec, q_covid, q_ine, q_mundial]:
        try:
            dfs.append(pd.read_sql(q, engine_sandbox))
        except Exception as e:
            print_log(f"  Advertencia al leer Stage: {e}")

    df = pd.concat(dfs, ignore_index=True).drop_duplicates()
    df.columns = ["anio", "mes"]
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int16")
    df["mes"]  = pd.to_numeric(df["mes"],  errors="coerce").astype("Int16")

    def trimestre(mes):
        if pd.isna(mes): return None
        return int((mes - 1) // 3 + 1)

    def periodo(anio):
        if pd.isna(anio): return "Ignorado"
        a = int(anio)
        if a < 2020:    return "pre-COVID"
        elif a <= 2021: return "COVID"
        else:           return "post-COVID"

    df["trimestre"] = df["mes"].apply(trimestre)
    df["periodo"]   = df["anio"].apply(periodo)
    df = df.drop_duplicates().reset_index(drop=True)
    df.insert(0, "id_tiempo", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_tiempo")
    return df


def _build_dim_geografia(engine_sandbox) -> pd.DataFrame:
    print_log("Construyendo dim_geografia...")
    q_gt = """
        SELECT DISTINCT nombre_depto_ocurrencia AS departamento,
                        nombre_muni_ocurrencia  AS municipio,
               'Guatemala' AS pais, 'GTM' AS iso3c, 'Guatemala' AS region
        FROM stage.stage_defunciones_gt
        WHERE nombre_depto_ocurrencia IS NOT NULL
        UNION
        SELECT DISTINCT departamento, municipio,
               'Guatemala' AS pais, 'GTM' AS iso3c, 'Guatemala' AS region
        FROM stage.stage_mspas_mec
        WHERE departamento IS NOT NULL
        UNION
        SELECT DISTINCT departamento, municipio,
               'Guatemala' AS pais, 'GTM' AS iso3c, 'Guatemala' AS region
        FROM stage.stage_mspas_covid
        WHERE departamento IS NOT NULL
    """
    q_int = """
        SELECT DISTINCT NULL AS departamento, NULL AS municipio,
               pais, iso3c, NULL AS region
        FROM stage.stage_mortalidad_mundial
        WHERE pais IS NOT NULL
    """
    dfs = []
    for q in [q_gt, q_int]:
        try:
            dfs.append(pd.read_sql(q, engine_sandbox))
        except Exception as e:
            print_log(f"  Advertencia: {e}")

    df = pd.concat(dfs, ignore_index=True).drop_duplicates()
    df["region"] = df.apply(
        lambda r: REGIONES.get(str(r["iso3c"]).strip().upper(), "Otro")
        if pd.isna(r["region"]) and pd.notna(r["iso3c"])
        else r["region"],
        axis=1
    )
    df = df.drop_duplicates().reset_index(drop=True)
    df.insert(0, "id_geografia", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_geografia")
    return df


def _build_dim_causa_cie10(engine_sandbox) -> pd.DataFrame:
    print_log("Construyendo dim_causa_cie10...")
    q = """
        SELECT DISTINCT codigo_cie10, diagnostico AS descripcion
        FROM stage.stage_mspas_mec WHERE codigo_cie10 IS NOT NULL
        UNION
        SELECT DISTINCT codigo_cie10, descripcion_causa AS descripcion
        FROM stage.stage_defunciones_gt WHERE codigo_cie10 IS NOT NULL
    """
    try:
        df = pd.read_sql(q, engine_sandbox)
    except Exception as e:
        print_log(f"  Advertencia al leer causas: {e}")
        df = pd.DataFrame(columns=["codigo_cie10", "descripcion"])

    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()
    df["descripcion"]  = df["descripcion"].fillna("Sin descripcion")

    especiales = pd.DataFrame([
        {"codigo_cie10": "U071", "descripcion": "COVID-19 identificado"},
        {"codigo_cie10": "ZGEN", "descripcion": "Mortalidad general sin causa especifica"},
    ])
    df = pd.concat([df, especiales], ignore_index=True).drop_duplicates(subset=["codigo_cie10"])

    def capitulo(cod):
        if not isinstance(cod, str) or len(cod) == 0: return "No especificado"
        return CAPITULOS_CIE10.get(cod[0].upper(), "Capitulo no identificado")

    def categoria(cod):
        if not isinstance(cod, str) or len(cod) == 0: return "Otra"
        return CATEGORIAS_CIE10.get(cod[0].upper(), "Otra")

    df["capitulo_cie10"] = df["codigo_cie10"].apply(capitulo)
    df["categoria"]      = df["codigo_cie10"].apply(categoria)
    df = df.drop_duplicates().reset_index(drop=True)
    df.insert(0, "id_causa", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_causa_cie10")
    return df


def _build_dim_sexo() -> pd.DataFrame:
    print_log("Construyendo dim_sexo...")
    return pd.DataFrame([
        {"id_sexo": 1, "codigo": "F", "descripcion": "Femenino"},
        {"id_sexo": 2, "codigo": "M", "descripcion": "Masculino"},
        {"id_sexo": 3, "codigo": "N", "descripcion": "No especificado"},
    ])


def _build_dim_grupo_etario() -> pd.DataFrame:
    print_log("Construyendo dim_grupo_etario...")
    return pd.DataFrame([
        {"id_grupo_etario": 1, "rango": "< 1 anio",       "edad_min": 0,    "edad_max": 0},
        {"id_grupo_etario": 2, "rango": "1-4",             "edad_min": 1,    "edad_max": 4},
        {"id_grupo_etario": 3, "rango": "5-14",            "edad_min": 5,    "edad_max": 14},
        {"id_grupo_etario": 4, "rango": "15-29",           "edad_min": 15,   "edad_max": 29},
        {"id_grupo_etario": 5, "rango": "30-44",           "edad_min": 30,   "edad_max": 44},
        {"id_grupo_etario": 6, "rango": "45-59",           "edad_min": 45,   "edad_max": 59},
        {"id_grupo_etario": 7, "rango": "60 o mas",        "edad_min": 60,   "edad_max": None},
        {"id_grupo_etario": 8, "rango": "No especificado", "edad_min": None, "edad_max": None},
    ])


def _build_dim_fuente() -> pd.DataFrame:
    print_log("Construyendo dim_fuente...")
    return pd.DataFrame([
        {"id_fuente": 1, "nombre": "INE",               "tipo": "Nacional",      "pais_cobertura": "Guatemala",     "cobertura_temporal": "2018-2024"},
        {"id_fuente": 2, "nombre": "MSPAS_MEC",         "tipo": "Institucional", "pais_cobertura": "Guatemala",     "cobertura_temporal": "2012-2024"},
        {"id_fuente": 3, "nombre": "MSPAS_COVID",       "tipo": "Institucional", "pais_cobertura": "Guatemala",     "cobertura_temporal": "2020-2024"},
        {"id_fuente": 4, "nombre": "WORLD_MORTALITY",   "tipo": "Internacional", "pais_cobertura": "Global",        "cobertura_temporal": "2015-2024"},
        {"id_fuente": 5, "nombre": "CENTROAMERICA_RDS", "tipo": "Internacional", "pais_cobertura": "Centroamerica", "cobertura_temporal": "2000-2023"},
    ])


def _cargar_dimensiones(engine_dw, tablas: list, destino: str):
    """Carga todas las dimensiones en un engine destino."""
    with engine_dw.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS dw"))

    for nombre_tabla, df in tablas:
        df.to_sql(
            name=nombre_tabla,
            con=engine_dw,
            schema="dw",
            if_exists="replace",
            index=False,
            chunksize=1000,
            method="multi",
        )
        print_log(f"  [{destino}] dw.{nombre_tabla}: {len(df):,} registros cargados.")


def create_dimensions(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando a Sandbox (lectura)...")
    engine_sandbox = create_engine(sandbox_url, pool_pre_ping=True)

    # Construir todas las dimensiones una sola vez
    dim_tiempo       = _build_dim_tiempo(engine_sandbox)
    dim_geografia    = _build_dim_geografia(engine_sandbox)
    dim_causa_cie10  = _build_dim_causa_cie10(engine_sandbox)
    dim_sexo         = _build_dim_sexo()
    dim_grupo_etario = _build_dim_grupo_etario()
    dim_fuente       = _build_dim_fuente()

    tablas = [
        ("dim_tiempo",       dim_tiempo),
        ("dim_geografia",    dim_geografia),
        ("dim_causa_cie10",  dim_causa_cie10),
        ("dim_sexo",         dim_sexo),
        ("dim_grupo_etario", dim_grupo_etario),
        ("dim_fuente",       dim_fuente),
    ]

    # Cargar en DW local
    print_log("─" * 60)
    print_log("Cargando dimensiones -> DW LOCAL...")
    engine_local = create_engine(dw_local_url, pool_pre_ping=True)
    _cargar_dimensiones(engine_local, tablas, "LOCAL")
    engine_local.dispose()

    # Cargar en DW nube (si está configurado)
    if dw_cloud_url:
        print_log("─" * 60)
        print_log("Cargando dimensiones -> DW NUBE (RDS)...")
        engine_cloud = create_engine(dw_cloud_url, pool_pre_ping=True)
        _cargar_dimensiones(engine_cloud, tablas, "NUBE")
        engine_cloud.dispose()
    else:
        print_log("DW_CLOUD_URL no configurada — se omite carga en nube.")

    engine_sandbox.dispose()
    print_log("─" * 60)
    print_log("TODAS LAS DIMENSIONES CARGADAS EXITOSAMENTE.")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: Creacion de Dimensiones DW (local + nube)")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    sandbox_url  = os.getenv("SANDBOX_DB_URL")
    dw_local_url = os.getenv("DW_DB_URL")
    dw_cloud_url = os.getenv("DW_CLOUD_URL")

    if not sandbox_url:  raise EnvironmentError("SANDBOX_DB_URL no encontrada en el .env.")
    if not dw_local_url: raise EnvironmentError("DW_DB_URL no encontrada en el .env.")

    create_dimensions(sandbox_url, dw_local_url, dw_cloud_url)