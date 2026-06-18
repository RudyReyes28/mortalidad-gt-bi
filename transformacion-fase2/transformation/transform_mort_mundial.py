"""

Transforma y une dos fuentes en stage.stage_mortalidad_mundial:

    sandbox.sandbox_world_mortality  → datos mensuales/semanales por país
    sandbox.sandbox_centroamerica    → datos anuales Panamá y Costa Rica

Transformaciones aplicadas:
    - Filtro de 35 países seleccionados (Centroamérica, Europa, América, Asia, Oceanía)
    - Filtro de años >= 2015
    - Separación de time en mes/semana según time_unit
    - Normalización de nombres de columnas
    - Clasificación de región por país
    - Clasificación de período pre-COVID / COVID / post-COVID
    - Unión de ambas fuentes en una tabla unificada

"""

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("transform.mundial")

# Países seleccionados con su región 
PAISES_SELECCIONADOS = {
    # Centroamérica
    "GTM": ("Guatemala",       "Centroamérica"),
    "HND": ("Honduras",        "Centroamérica"),
    "SLV": ("El Salvador",     "Centroamérica"),
    "NIC": ("Nicaragua",       "Centroamérica"),
    "CRI": ("Costa Rica",      "Centroamérica"),
    "PAN": ("Panamá",          "Centroamérica"),
    "BLZ": ("Belice",          "Centroamérica"),
    # América del Sur
    "PER": ("Perú",            "América del Sur"),
    "BOL": ("Bolivia",         "América del Sur"),
    "ECU": ("Ecuador",         "América del Sur"),
    "BRA": ("Brasil",          "América del Sur"),
    "COL": ("Colombia",        "América del Sur"),
    "ARG": ("Argentina",       "América del Sur"),
    "CHL": ("Chile",           "América del Sur"),
    # América del Norte
    "MEX": ("México",          "América del Norte"),
    "USA": ("Estados Unidos",  "América del Norte"),
    "CAN": ("Canadá",          "América del Norte"),
    # Europa
    "ESP": ("España",          "Europa"),
    "ITA": ("Italia",          "Europa"),
    "GBR": ("Reino Unido",     "Europa"),
    "DEU": ("Alemania",        "Europa"),
    "FRA": ("Francia",         "Europa"),
    "SWE": ("Suecia",          "Europa"),
    "PRT": ("Portugal",        "Europa"),
    "RUS": ("Rusia",           "Europa"),
    "UKR": ("Ucrania",         "Europa"),
    "POL": ("Polonia",         "Europa"),
    # Asia
    "JPN": ("Japón",           "Asia"),
    "KOR": ("Corea del Sur",   "Asia"),
    "TUR": ("Turquía",         "Asia"),
    # Oceanía
    "AUS": ("Australia",       "Oceanía"),
    "NZL": ("Nueva Zelanda",   "Oceanía"),
}

# Códigos ISO de Centroamérica para el sandbox_centroamerica
NOMBRE_A_ISO = {
    "Panama":     "PAN",
    "Costa Rica": "CRI",
}

AÑO_INICIO = 2015


# Clasificación de período
def _clasificar_periodo(anio: int) -> str:
    if anio < 2020:
        return "pre-COVID"
    elif anio <= 2021:
        return "COVID"
    else:
        return "post-COVID"


# Leer tabla del Sandbox
def _leer_sandbox(engine, tabla: str) -> pd.DataFrame:
    logger.info(f"Leyendo sandbox.{tabla}...")
    df = pd.read_sql(f"SELECT * FROM sandbox.{tabla}", engine)
    logger.info(f"  → {len(df):,} filas leídas")
    return df


# Procesar World Mortality 
def _procesar_world_mortality(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Filtra y normaliza sandbox_world_mortality.

    - Filtra países seleccionados y años >= 2015
    - Separa time en mes o semana según time_unit
    - Agrega columnas de región y período
    """
    logger.info("Procesando World Mortality Dataset...")

    # Filtrar países seleccionados
    df = df_raw[df_raw["iso3c"].isin(PAISES_SELECCIONADOS.keys())].copy()
    logger.info(f"  Después de filtro países: {len(df):,} filas")
    logger.info(f"  Países encontrados: {sorted(df['iso3c'].unique().tolist())}")

    # Filtrar años
    df = df[df["year"] >= AÑO_INICIO]
    logger.info(f"  Después de filtro años >= {AÑO_INICIO}: {len(df):,} filas")

    # Verificar time_units presentes
    logger.info(f"  time_unit únicos: {df['time_unit'].unique().tolist()}")

    # Separar mes y semana según time_unit
    df["mes"]    = df.apply(
        lambda row: int(row["time"]) if row["time_unit"] == "monthly" else None,
        axis=1
    )
    df["semana"] = df.apply(
        lambda row: int(row["time"]) if row["time_unit"] == "weekly" else None,
        axis=1
    )

    # Agregar región
    df["region"] = df["iso3c"].map(
        {k: v[1] for k, v in PAISES_SELECCIONADOS.items()}
    )

    # Agregar período
    df["periodo"] = df["year"].apply(_clasificar_periodo)

    # Construir DataFrame normalizado
    df_norm = pd.DataFrame({
        "iso3c":        df["iso3c"],
        "country_name": df["country_name"],
        "region":       df["region"],
        "anio":         df["year"].astype("Int16"),
        "mes":          df["mes"],
        "semana":       df["semana"],
        "deaths":       df["deaths"],
        "time_unit":    df["time_unit"],
        "periodo":      df["periodo"],
        "fuente":       "WORLD_MORTALITY",
        "fuente_origen": df["fuente_origen"],
        "fecha_carga":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    logger.info(f"  World Mortality procesado: {len(df_norm):,} filas")
    return df_norm


# Procesar Centroamérica
def _procesar_centroamerica(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza sandbox_centroamerica al mismo schema que World Mortality.

    - Agrega iso3c desde el nombre del país
    - Filtra años >= 2015
    - time_unit = annual, mes = NULL, semana = NULL
    - Usa defunciones_general como deaths
    """
    logger.info("Procesando Centroamérica (Panamá y Costa Rica)...")

    # Mapear nombre → iso3c
    df = df_raw.copy()
    df["iso3c"] = df["pais"].map(NOMBRE_A_ISO)

    # Filtrar solo países mapeados
    df = df[df["iso3c"].notna()]

    # Filtrar años
    df = df[df["anio"] >= AÑO_INICIO]
    logger.info(f"  Después de filtro años >= {AÑO_INICIO}: {len(df):,} filas")

    # Verificar nulos en defunciones_general
    nulos = df["defunciones_general"].isna().sum()
    if nulos > 0:
        logger.warning(f"  {nulos} registros con defunciones_general NULL — se excluyen")
        df = df[df["defunciones_general"].notna()]

    # Agregar período
    df["periodo"] = df["anio"].apply(_clasificar_periodo)

    # Construir DataFrame normalizado
    df_norm = pd.DataFrame({
        "iso3c":        df["iso3c"],
        "country_name": df["pais"],
        "region":       "Centroamérica",
        "anio":         df["anio"].astype("Int16"),
        "mes":          None,      # datos anuales — sin mes
        "semana":       None,      # datos anuales — sin semana
        "deaths":       df["defunciones_general"],
        "time_unit":    "annual",
        "periodo":      df["periodo"],
        "fuente":       df["fuente_origen"],
        "fuente_origen": df["fuente_origen"],
        "fecha_carga":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    logger.info(f"  Centroamérica procesada: {len(df_norm):,} filas")
    logger.info(f"  Países: {df_norm['country_name'].unique().tolist()}")
    logger.info(f"  Rango años: {df_norm['anio'].min()} — {df_norm['anio'].max()}")
    return df_norm


# Transformación principal
def transform_mundial(db_url: str) -> pd.DataFrame:
    """
    Lee sandbox_world_mortality y sandbox_centroamerica, los transforma
    y los une en un DataFrame Stage unificado.

    Args:
        db_url: Cadena de conexión al RDS PostgreSQL.

    Returns:
        DataFrame listo para cargar en stage.stage_mortalidad_mundial.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Transformación Mundial → Stage")
    logger.info("=" * 60)

    engine = create_engine(db_url, pool_pre_ping=True)

    #  1. Leer fuentes 
    df_wm = _leer_sandbox(engine, "sandbox_world_mortality")
    df_ca = _leer_sandbox(engine, "sandbox_centroamerica")
    engine.dispose()

    #  2. Procesar cada fuente 
    df_wm_norm = _procesar_world_mortality(df_wm)
    df_ca_norm = _procesar_centroamerica(df_ca)

    #  3. Verificar países que están en CA pero también en World Mortality
    # (Costa Rica y Panamá pueden estar en ambos — evitar duplicar)
    paises_ca   = set(df_ca_norm["iso3c"].unique())
    paises_wm   = set(df_wm_norm["iso3c"].unique())
    duplicados  = paises_ca & paises_wm

    if duplicados:
        logger.warning(
            f"Países en ambas fuentes: {duplicados}. "
            f"Se conservan AMBAS — la columna 'fuente' indica el origen. "
            f"En el DW se puede elegir cuál usar para cada análisis."
        )

    #  4. Unir ambas fuentes 
    logger.info("Uniendo fuentes...")
    df_stage = pd.concat([df_wm_norm, df_ca_norm], ignore_index=True)

    #  5. EDA rápido 
    logger.info("\n" + "─" * 60)
    logger.info("EDA — stage_mortalidad_mundial")
    logger.info("─" * 60)
    logger.info(f"Shape              : {df_stage.shape}")
    logger.info(f"Países únicos      : {df_stage['iso3c'].nunique()}")
    logger.info(f"Rango años         : {df_stage['anio'].min()} — {df_stage['anio'].max()}")
    logger.info(f"\nPor región:\n{df_stage['region'].value_counts().to_string()}")
    logger.info(f"\nPor time_unit:\n{df_stage['time_unit'].value_counts().to_string()}")
    logger.info(f"\nPor período:\n{df_stage['periodo'].value_counts().to_string()}")
    logger.info(f"\nPor fuente:\n{df_stage['fuente'].value_counts().to_string()}")
    logger.info(f"\nNULLs por columna:\n{df_stage.isnull().sum()[df_stage.isnull().sum() > 0].to_string()}")
    logger.info("─" * 60)

    return df_stage


# Cargar al Stage 
def cargar_stage(df: pd.DataFrame, db_url: str):
    """
    Carga el DataFrame en stage.stage_mortalidad_mundial.

    Args:
        df    : DataFrame retornado por transform_mundial().
        db_url: Cadena de conexión al RDS PostgreSQL.
    """
    logger.info("Cargando al Stage...")
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))

    df.to_sql(
        name="stage_mortalidad_mundial",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=5000,
        method="multi",
    )

    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM stage.stage_mortalidad_mundial")
        ).scalar()

    logger.info(f"  → {total:,} filas cargadas en stage.stage_mortalidad_mundial")
    engine.dispose()


# Entry point 
if __name__ == "__main__":
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    DB_URL = os.getenv("SANDBOX_DB_URL")
    if not DB_URL:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en .env")

    df_stage = transform_mundial(DB_URL)
    cargar_stage(df_stage, DB_URL)

    logger.info("\n Transformación Mundial completada exitosamente.")