"""

Transforma sandbox.sandbox_covid_mundial -> stage.stage_covid_mundial

Transformaciones aplicadas:
    - Filtro de 35 países seleccionados (mismos que stage_mortalidad_mundial)
    - Extracción de año y mes desde Date_reported
    - Agregación semanal → mensual (suma New_cases y New_deaths por mes)
    - Último valor acumulado del mes (Cumulative_cases y Cumulative_deaths)
    - Clasificación de período pre-COVID / COVID / post-COVID
    - Mapeo de región desde WHO_region a nombre legible

"""

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("transform.covid_mundial")

# ── Países seleccionados (mismos que stage_mortalidad_mundial) ────────────────
# Clave: ISO2 (como viene en el dataset OMS)
# Valor: (nombre, región)
PAISES_SELECCIONADOS = {
    # Centroamérica
    "GT": ("Guatemala",       "Centroamérica"),
    "HN": ("Honduras",        "Centroamérica"),
    "SV": ("El Salvador",     "Centroamérica"),
    "NI": ("Nicaragua",       "Centroamérica"),
    "CR": ("Costa Rica",      "Centroamérica"),
    "PA": ("Panamá",          "Centroamérica"),
    "BZ": ("Belice",          "Centroamérica"),
    # América del Sur
    "PE": ("Perú",            "América del Sur"),
    "BO": ("Bolivia",         "América del Sur"),
    "EC": ("Ecuador",         "América del Sur"),
    "BR": ("Brasil",          "América del Sur"),
    "CO": ("Colombia",        "América del Sur"),
    "AR": ("Argentina",       "América del Sur"),
    "CL": ("Chile",           "América del Sur"),
    # América del Norte
    "MX": ("México",          "América del Norte"),
    "US": ("Estados Unidos",  "América del Norte"),
    "CA": ("Canadá",          "América del Norte"),
    # Europa
    "ES": ("España",          "Europa"),
    "IT": ("Italia",          "Europa"),
    "GB": ("Reino Unido",     "Europa"),
    "DE": ("Alemania",        "Europa"),
    "FR": ("Francia",         "Europa"),
    "SE": ("Suecia",          "Europa"),
    "PT": ("Portugal",        "Europa"),
    "RU": ("Rusia",           "Europa"),
    "UA": ("Ucrania",         "Europa"),
    "PL": ("Polonia",         "Europa"),
    # Asia
    "JP": ("Japón",           "Asia"),
    "KR": ("Corea del Sur",   "Asia"),
    "TR": ("Turquía",         "Asia"),
    # Oceanía
    "AU": ("Australia",       "Oceanía"),
    "NZ": ("Nueva Zelanda",   "Oceanía"),
}

# ── Mapeo de región OMS a nombre legible ─────────────────────────────────────
WHO_REGION_MAP = {
    "AMRO":  "América",
    "EURO":  "Europa",
    "SEARO": "Asia Sudoriental",
    "WPRO":  "Pacífico Occidental",
    "EMRO":  "Mediterráneo Oriental",
    "AFRO":  "África",
    "OTHER": "Otro",
}


# ── Clasificar período ────────────────────────────────────────────────────────
def _clasificar_periodo(anio: int) -> str:
    if anio < 2020:
        return "pre-COVID"
    elif anio <= 2021:
        return "COVID"
    else:
        return "post-COVID"


# ── Leer tabla del Sandbox ────────────────────────────────────────────────────
def _leer_sandbox(engine) -> pd.DataFrame:
    logger.info("Leyendo sandbox.sandbox_covid_mundial...")
    df = pd.read_sql("SELECT * FROM sandbox.sandbox_covid_mundial", engine)
    logger.info(f"  → {len(df):,} filas leídas")
    logger.info(f"  → Países únicos: {df['Country_code'].nunique()}")
    return df


# ── Transformación principal ──────────────────────────────────────────────────
def transform_covid_mundial(db_url: str) -> pd.DataFrame:
    """
    Lee sandbox_covid_mundial, filtra países, agrega a mensual
    y retorna el DataFrame Stage.

    Args:
        db_url: Cadena de conexión al RDS PostgreSQL.

    Returns:
        DataFrame listo para cargar en stage.stage_covid_mundial.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Transformación COVID Mundial → Stage")
    logger.info("=" * 60)

    engine = create_engine(db_url, pool_pre_ping=True)
    df_raw = _leer_sandbox(engine)
    engine.dispose()

    # ── 1. Convertir Date_reported a datetime ─────────────────────────
    logger.info("Convirtiendo fechas...")
    df_raw["Date_reported"] = pd.to_datetime(
        df_raw["Date_reported"], errors="coerce"
    )
    nulos_fecha = df_raw["Date_reported"].isna().sum()
    if nulos_fecha > 0:
        logger.warning(f"  {nulos_fecha:,} fechas inválidas → se eliminan")
        df_raw = df_raw[df_raw["Date_reported"].notna()]

    # ── 2. Extraer año y mes ──────────────────────────────────────────
    df_raw["anio"] = df_raw["Date_reported"].dt.year
    df_raw["mes"]  = df_raw["Date_reported"].dt.month

    # ── 3. Filtrar países seleccionados ───────────────────────────────
    antes = len(df_raw)
    df = df_raw[df_raw["Country_code"].isin(PAISES_SELECCIONADOS.keys())].copy()
    logger.info(f"Filtro países: {antes:,} → {len(df):,} filas")

    paises_encontrados = sorted(df["Country_code"].unique().tolist())
    paises_faltantes   = [p for p in PAISES_SELECCIONADOS if p not in paises_encontrados]
    logger.info(f"  Países encontrados ({len(paises_encontrados)}): {paises_encontrados}")
    if paises_faltantes:
        logger.warning(f"  Países no encontrados en dataset: {paises_faltantes}")

    # ── 4. Convertir columnas numéricas ───────────────────────────────
    for col in ["New_cases", "Cumulative_cases", "New_deaths", "Cumulative_deaths"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── 5. Agregación semanal → mensual (Opción A — suma) ─────────────
    logger.info("Agregando datos semanales a mensuales...")

    # Agrupar por país + año + mes
    grupo = ["Country_code", "Country", "WHO_region", "anio", "mes"]

    df_agg = df.groupby(grupo).agg(
        new_cases_mes  = ("New_cases",          "sum"),
        new_deaths_mes = ("New_deaths",         "sum"),
        cum_cases_fin  = ("Cumulative_cases",   "last"),  # último valor del mes
        cum_deaths_fin = ("Cumulative_deaths",  "last"),  # último valor del mes
        semanas_reporte= ("Date_reported",      "count"), # cuántas semanas en ese mes
    ).reset_index()

    logger.info(f"  Filas antes de agregar (semanales): {len(df):,}")
    logger.info(f"  Filas después de agregar (mensuales): {len(df_agg):,}")

    # ── 6. Agregar región legible ─────────────────────────────────────
    df_agg["region"] = df_agg["Country_code"].map(
        {k: v[1] for k, v in PAISES_SELECCIONADOS.items()}
    )

    # ── 7. Normalizar nombre OMS region ──────────────────────────────
    df_agg["who_region_desc"] = df_agg["WHO_region"].map(WHO_REGION_MAP).fillna("Otro")

    # ── 8. Clasificar período ─────────────────────────────────────────
    df_agg["periodo"] = df_agg["anio"].apply(_clasificar_periodo)

    # ── 9. Construir DataFrame Stage final ────────────────────────────
    df_stage = pd.DataFrame({
        "anio":             df_agg["anio"].astype("Int16"),
        "mes":              df_agg["mes"].astype("Int16"),
        "country_code":     df_agg["Country_code"],
        "country_name":     df_agg["Country"],
        "who_region":       df_agg["WHO_region"],
        "who_region_desc":  df_agg["who_region_desc"],
        "region":           df_agg["region"],
        "new_cases_mes":    df_agg["new_cases_mes"],
        "new_deaths_mes":   df_agg["new_deaths_mes"],
        "cum_cases_fin":    df_agg["cum_cases_fin"],
        "cum_deaths_fin":   df_agg["cum_deaths_fin"],
        "semanas_reporte":  df_agg["semanas_reporte"],
        "periodo":          df_agg["periodo"],
        "fuente_origen":    "OMS_COVID_MUNDIAL_STAGE",
        "fecha_carga":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # ── 10. EDA rápido ────────────────────────────────────────────────
    logger.info("\n" + "─" * 60)
    logger.info("EDA — stage_covid_mundial")
    logger.info("─" * 60)
    logger.info(f"Shape              : {df_stage.shape}")
    logger.info(f"Países únicos      : {df_stage['country_code'].nunique()}")
    logger.info(f"Rango años         : {df_stage['anio'].min()} — {df_stage['anio'].max()}")
    logger.info(f"\nPor región:\n{df_stage['region'].value_counts().to_string()}")
    logger.info(f"\nPor período:\n{df_stage['periodo'].value_counts().to_string()}")
    logger.info(f"\nTop 5 países por muertes totales:")
    top = df_stage.groupby("country_name")["new_deaths_mes"].sum().sort_values(ascending=False).head(5)
    logger.info(f"\n{top.to_string()}")
    logger.info(f"\nNULLs por columna:\n{df_stage.isnull().sum()[df_stage.isnull().sum() > 0].to_string()}")
    logger.info("─" * 60)

    return df_stage


# ── Cargar al Stage ───────────────────────────────────────────────────────────
def cargar_stage(df: pd.DataFrame, db_url: str):
    """
    Carga el DataFrame en stage.stage_covid_mundial.

    Args:
        df    : DataFrame retornado por transform_covid_mundial().
        db_url: Cadena de conexión al RDS PostgreSQL.
    """
    logger.info("Cargando al Stage...")
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))

    df.to_sql(
        name="stage_covid_mundial",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=5000,
        method="multi",
    )

    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM stage.stage_covid_mundial")
        ).scalar()

    logger.info(f"  → {total:,} filas cargadas en stage.stage_covid_mundial")
    engine.dispose()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    DB_URL = os.getenv("SANDBOX_DB_URL")
    if not DB_URL:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en .env")

    df_stage = transform_covid_mundial(DB_URL)
    cargar_stage(df_stage, DB_URL)

    logger.info("\n✓ Transformación COVID Mundial completada exitosamente.")