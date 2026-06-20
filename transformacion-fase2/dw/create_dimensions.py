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

Arquitectura Galaxy Schema — PDF Decisiones de Diseño Fase 2:

Dimensiones conformadas (7):
    dw.dim_tiempo           — compartida por las 5 fact tables
    dw.dim_sexo             — fact_defunciones_gt + fact_morbimortalidad_mec
    dw.dim_grupo_etario     — fact_defunciones_gt + fact_morbimortalidad_mec
    dw.dim_causa_cie10      — fact_defunciones_gt + fact_morbimortalidad_mec
    dw.dim_geografia_gt     — fact_defunciones_gt + fact_mortalidad_covid_gt + fact_morbimortalidad_mec
                              SCD Tipo 2 (preserva historial de cambios administrativos)
    dw.dim_geografia_mundial — fact_mortalidad_mundial + fact_covid_mundial
    dw.dim_fuente           — todas las 5 fact tables

IMPORTANTE: Ejecutar ANTES de cualquier load_fact_*.py
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


# ── Capítulos y categorías CIE-10 ────────────────────────────────────────────
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
    "E": "Cronica",   "F": "Cronica",   "G": "Cronica", "H": "Cronica",
    "I": "Cronica",   "J": "Cronica",   "K": "Cronica", "L": "Cronica",
    "M": "Cronica",   "N": "Cronica",   "O": "Materna", "P": "Perinatal",
    "Q": "Congenita", "R": "Otra",      "S": "Externa", "T": "Externa",
    "U": "COVID-19",  "V": "Externa",   "W": "Externa", "X": "Externa",
    "Y": "Externa",   "Z": "Otra",
}

# ── Mapeo ISO2 → ISO3 para dim_geografia_mundial ─────────────────────────────
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


# ────────────────────────────────────────────────────────────────────────────
# 1. dim_tiempo
# ────────────────────────────────────────────────────────────────────────────
def _build_dim_tiempo(engine_sandbox) -> pd.DataFrame:
    """
    Recopila años y meses únicos de las 5 tablas Stage.
    Calcula trimestre y período para cada combinación.
    """
    print_log("Construyendo dim_tiempo...")

    queries = [
        "SELECT DISTINCT anio, NULL::smallint AS mes FROM stage.stage_mspas_mec WHERE anio IS NOT NULL",
        "SELECT DISTINCT anio, mes FROM stage.stage_mspas_covid WHERE anio IS NOT NULL",
        "SELECT DISTINCT anio_ocurrencia AS anio, mes_ocurrencia AS mes FROM stage.stage_defunciones_gt WHERE anio_ocurrencia IS NOT NULL",
        # Mensuales de world mortality
        "SELECT DISTINCT anio, mes FROM stage.stage_mortalidad_mundial WHERE anio IS NOT NULL AND mes IS NOT NULL",
        # Anuales/semanales de world mortality — solo anio, mes NULL
        "SELECT DISTINCT anio, NULL::smallint AS mes FROM stage.stage_mortalidad_mundial WHERE anio IS NOT NULL",
        "SELECT DISTINCT anio, mes FROM stage.stage_covid_mundial WHERE anio IS NOT NULL",
    ]

    dfs = []
    for q in queries:
        try:
            dfs.append(pd.read_sql(q, engine_sandbox))
        except Exception as e:
            print_log(f"  Advertencia: {e}")

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


# ────────────────────────────────────────────────────────────────────────────
# 2. dim_geografia_gt  (SCD Tipo 2)
# ────────────────────────────────────────────────────────────────────────────
def _build_dim_geografia_gt(engine_sandbox) -> pd.DataFrame:
    """
    Dimensión geográfica para fuentes guatemaltecas (depto/municipio).
    Implementa SCD Tipo 2: cada registro tiene fecha_inicio_vigencia,
    fecha_fin_vigencia y es_version_actual para preservar historial
    de cambios administrativos en el período 2015-2024.
    En esta versión inicial todos los registros son versión 1 (vigentes).
    """
    print_log("Construyendo dim_geografia_gt (SCD Tipo 2)...")

    q = """
        SELECT DISTINCT nombre_depto_ocurrencia AS nombre_departamento,
                        nombre_muni_ocurrencia  AS nombre_municipio
        FROM stage.stage_defunciones_gt
        WHERE nombre_depto_ocurrencia IS NOT NULL
        UNION
        SELECT DISTINCT departamento AS nombre_departamento,
                        municipio   AS nombre_municipio
        FROM stage.stage_mspas_mec
        WHERE departamento IS NOT NULL
        UNION
        SELECT DISTINCT departamento AS nombre_departamento,
                        municipio   AS nombre_municipio
        FROM stage.stage_mspas_covid
        WHERE departamento IS NOT NULL
    """
    try:
        df = pd.read_sql(q, engine_sandbox)
    except Exception as e:
        print_log(f"  Advertencia: {e}")
        df = pd.DataFrame(columns=["nombre_departamento", "nombre_municipio"])

    df.columns = ["nombre_departamento", "nombre_municipio"]
    df = df.drop_duplicates().reset_index(drop=True)

    # SCD Tipo 2 — columnas de control
    df["codigo_departamento"]   = None   # se puede enriquecer con catálogo oficial
    df["codigo_municipio"]      = None
    df["region"]                = "Guatemala"
    df["pais"]                  = "Guatemala"
    df["iso3c"]                 = "GTM"
    df["fecha_inicio_vigencia"] = "2015-01-01"
    df["fecha_fin_vigencia"]    = None   # NULL = versión vigente actual
    df["es_version_actual"]     = True
    df["version"]               = 1

    df.insert(0, "id_geografia", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_geografia_gt (versión 1 — vigentes)")
    return df


# ────────────────────────────────────────────────────────────────────────────
# 3. dim_geografia_mundial
# ────────────────────────────────────────────────────────────────────────────
def _build_dim_geografia_mundial(engine_sandbox) -> pd.DataFrame:
    """
    Dimensión geográfica para fuentes internacionales (país/región).
    Separada de dim_geografia_gt porque tienen grano geográfico distinto
    (nivel país vs nivel municipio). SCD Tipo 1.
    Incluye ISO2 (para mapear desde stage_covid_mundial) e ISO3.
    """
    print_log("Construyendo dim_geografia_mundial...")

    # Desde stage_mortalidad_mundial (tiene iso3c y country_name)
    q_mundial = """
        SELECT DISTINCT country_name AS nombre_pais, iso3c
        FROM stage.stage_mortalidad_mundial
        WHERE country_name IS NOT NULL AND iso3c IS NOT NULL
    """
    # Desde stage_covid_mundial (tiene country_code = ISO2)
    q_covid = """
        SELECT DISTINCT country_name AS nombre_pais, country_code AS iso2
        FROM stage.stage_covid_mundial
        WHERE country_name IS NOT NULL
    """

    dfs = []
    try:
        df_m = pd.read_sql(q_mundial, engine_sandbox)
        df_m["iso2"] = df_m["iso3c"].map({v: k for k, v in ISO2_A_ISO3.items()})
        dfs.append(df_m)
    except Exception as e:
        print_log(f"  Advertencia mundial: {e}")

    try:
        df_c = pd.read_sql(q_covid, engine_sandbox)
        df_c["iso3c"] = df_c["iso2"].map(ISO2_A_ISO3)
        dfs.append(df_c)
    except Exception as e:
        print_log(f"  Advertencia covid mundial: {e}")

    if not dfs:
        df = pd.DataFrame(columns=["nombre_pais", "iso3c", "iso2"])
    else:
        df = pd.concat(dfs, ignore_index=True).drop_duplicates(
            subset=["iso3c"]
        ).reset_index(drop=True)

    df["region"] = df["iso3c"].map(REGIONES_ISO3).fillna("Otro")

    df = df[["nombre_pais", "iso3c", "iso2", "region"]].drop_duplicates().reset_index(drop=True)
    df.insert(0, "id_geografia_mundial", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_geografia_mundial")
    return df


# ────────────────────────────────────────────────────────────────────────────
# 4. dim_causa_cie10
# ────────────────────────────────────────────────────────────────────────────
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
        print_log(f"  Advertencia: {e}")
        df = pd.DataFrame(columns=["codigo_cie10", "descripcion"])

    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()
    df["descripcion"]  = df["descripcion"].fillna("Sin descripcion")

    especiales = pd.DataFrame([
        {"codigo_cie10": "U071", "descripcion": "COVID-19 identificado"},
        {"codigo_cie10": "ZGEN", "descripcion": "Mortalidad general sin causa especifica"},
    ])
    df = pd.concat([df, especiales], ignore_index=True).drop_duplicates(subset=["codigo_cie10"])

    df["capitulo_cie10"] = df["codigo_cie10"].apply(
        lambda c: CAPITULOS_CIE10.get(c[0].upper(), "Capitulo no identificado")
        if isinstance(c, str) and len(c) > 0 else "No especificado"
    )
    df["categoria"] = df["codigo_cie10"].apply(
        lambda c: CATEGORIAS_CIE10.get(c[0].upper(), "Otra")
        if isinstance(c, str) and len(c) > 0 else "Otra"
    )

    df = df.drop_duplicates().reset_index(drop=True)
    df.insert(0, "id_causa", range(1, len(df) + 1))
    print_log(f"  -> {len(df):,} registros en dim_causa_cie10")
    return df


# ────────────────────────────────────────────────────────────────────────────
# 5. dim_sexo  (catálogo fijo)
# ────────────────────────────────────────────────────────────────────────────
def _build_dim_sexo() -> pd.DataFrame:
    print_log("Construyendo dim_sexo...")
    return pd.DataFrame([
        {"id_sexo": 1, "codigo": "F", "descripcion": "Femenino"},
        {"id_sexo": 2, "codigo": "M", "descripcion": "Masculino"},
        {"id_sexo": 3, "codigo": "N", "descripcion": "No especificado"},
    ])


# ────────────────────────────────────────────────────────────────────────────
# 6. dim_grupo_etario  (catálogo fijo)
# ────────────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────────────
# 7. dim_fuente  (catálogo fijo — 6 fuentes incluyendo OMS COVID)
# ────────────────────────────────────────────────────────────────────────────
def _build_dim_fuente() -> pd.DataFrame:
    print_log("Construyendo dim_fuente...")
    return pd.DataFrame([
        {"id_fuente": 1, "nombre": "INE",               "tipo": "Nacional",      "pais_cobertura": "Guatemala",    "cobertura_temporal": "2018-2024"},
        {"id_fuente": 2, "nombre": "MSPAS_MEC",         "tipo": "Institucional", "pais_cobertura": "Guatemala",    "cobertura_temporal": "2012-2024"},
        {"id_fuente": 3, "nombre": "MSPAS_COVID",       "tipo": "Institucional", "pais_cobertura": "Guatemala",    "cobertura_temporal": "2020-2024"},
        {"id_fuente": 4, "nombre": "WORLD_MORTALITY",   "tipo": "Internacional", "pais_cobertura": "Global",       "cobertura_temporal": "2015-2024"},
        {"id_fuente": 5, "nombre": "CENTROAMERICA_RDS", "tipo": "Internacional", "pais_cobertura": "Centroamerica","cobertura_temporal": "2000-2023"},
        {"id_fuente": 6, "nombre": "OMS_COVID_MUNDIAL", "tipo": "Internacional", "pais_cobertura": "Global",       "cobertura_temporal": "2020-2024"},
    ])


# ────────────────────────────────────────────────────────────────────────────
# Carga a un destino DW
# ────────────────────────────────────────────────────────────────────────────
def _cargar_dimensiones(engine_dw, tablas: list, destino: str):
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


# ────────────────────────────────────────────────────────────────────────────
# Función principal
# ────────────────────────────────────────────────────────────────────────────
def create_dimensions(sandbox_url: str, dw_local_url: str, dw_cloud_url: str = None):
    print_log("Conectando a Sandbox (lectura)...")
    engine_sandbox = create_engine(sandbox_url, pool_pre_ping=True)

    # Construir las 7 dimensiones
    dim_tiempo             = _build_dim_tiempo(engine_sandbox)
    dim_geografia_gt       = _build_dim_geografia_gt(engine_sandbox)
    dim_geografia_mundial  = _build_dim_geografia_mundial(engine_sandbox)
    dim_causa_cie10        = _build_dim_causa_cie10(engine_sandbox)
    dim_sexo               = _build_dim_sexo()
    dim_grupo_etario       = _build_dim_grupo_etario()
    dim_fuente             = _build_dim_fuente()

    tablas = [
        ("dim_tiempo",            dim_tiempo),
        ("dim_geografia_gt",      dim_geografia_gt),
        ("dim_geografia_mundial", dim_geografia_mundial),
        ("dim_causa_cie10",       dim_causa_cie10),
        ("dim_sexo",              dim_sexo),
        ("dim_grupo_etario",      dim_grupo_etario),
        ("dim_fuente",            dim_fuente),
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
    print_log("7 dimensiones: dim_tiempo, dim_geografia_gt (SCD2), dim_geografia_mundial,")
    print_log("               dim_causa_cie10, dim_sexo, dim_grupo_etario, dim_fuente")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: Creacion de Dimensiones DW (Galaxy Schema)")
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