import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Módulo de Transformación: World Mortality + Centroamérica -> Stage
(stage_mortalidad_mundial)

Consolida dos fuentes del Sandbox en una sola tabla Stage para el análisis
comparativo internacional pre/post-COVID:

  - sandbox.sandbox_world_mortality : World Mortality Dataset (ISO3, ~127 países)
  - sandbox.sandbox_centroamerica   : INEC Panamá + INEC Costa Rica (RDS)

Transformaciones aplicadas:
1. Filtrado estratégico de ~35 países clave:
   - Toda Centroamérica (GTM, HND, SLV, NIC, CRI, PAN, BLZ)
   - Sudamérica con alto exceso de mortalidad (PER, BRA, COL, ECU, BOL)
   - Norteamérica (USA, MEX, CAN)
   - Europa/Asia/Oceanía contrastantes (ESP, ITA, SWE, JPN, KOR, NZL, GBR, DEU)

2. Homologación de esquemas:
   - World Mortality: formato largo (año, período, unidad, muertes).
   - Centroamérica: formato anual agregado con indicadores adicionales.
   - Ambas se alinean a un esquema común con columna 'fuente' para identificar origen.

3. Normalización:
   - Años filtrados al rango 2015-2024 (pre-COVID y post-COVID).
   - Columna 'periodo' clasificada.
   - Valores nulos documentados y conservados (NULLs estructurales de Centroamérica).

4. Trazabilidad:
   - Columna 'fuente_dato' para distinguir WORLD_MORTALITY vs CENTROAMERICA_RDS.
   - Inyección de metadatos de auditoría.
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


# Países clave seleccionados estratégicamente
PAISES_CLAVE = [
    # Centroamérica completa
    "GTM", "HND", "SLV", "NIC", "CRI", "PAN", "BLZ",
    # Sudamérica — alto exceso de mortalidad COVID
    "PER", "BRA", "COL", "ECU", "BOL", "ARG", "CHL",
    # Norteamérica
    "USA", "MEX", "CAN",
    # Europa — casos contrastantes
    "ESP", "ITA", "SWE", "GBR", "DEU", "FRA", "PRT",
    # Asia/Oceanía
    "JPN", "KOR", "NZL", "AUS",
]


def _clasificar_periodo(anio) -> str:
    """Clasifica el año en período pre-COVID, COVID o post-COVID."""
    try:
        anio = int(float(anio))
        if anio < 2020:    return "pre-COVID"
        elif anio <= 2021: return "COVID"
        else:              return "post-COVID"
    except:
        return "Ignorado"


def _procesar_world_mortality(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforma sandbox_world_mortality al esquema común.
    Filtra países clave y rango 2015-2024.
    """
    print_log("Procesando World Mortality Dataset...")

    # Filtrar países clave
    df = df[df["iso3c"].isin(PAISES_CLAVE)].copy()
    print_log(f"  -> Países filtrados: {df['iso3c'].nunique()} países seleccionados.")

    # Filtrar rango de años
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"].between(2015, 2024)]

    # Eliminar nulos críticos
    df = df[df["deaths"].notna()]
    df = df[df["iso3c"].notna()]

    # Eliminar duplicados
    total_antes = len(df)
    df = df.drop_duplicates(subset=["iso3c", "year", "time", "time_unit"])
    print_log(f"  -> Deduplicación: eliminados {total_antes - len(df):,} duplicados.")

    # Construir esquema común
    df_out = pd.DataFrame({
        "iso3c":                   df["iso3c"].str.strip().str.upper(),
        "pais":                    df["country_name"].str.strip().str.title(),
        "anio":                    df["year"].astype("Int16"),
        "periodo_tiempo":          df["time"].astype("Int16"),
        "unidad_tiempo":           df["time_unit"].str.strip(),
        "defunciones_total":       pd.to_numeric(df["deaths"], errors="coerce"),
        # Campos exclusivos de Centroamérica — NULL en World Mortality
        "defunciones_infantiles":  None,
        "defunciones_menores_5":   None,
        "defunciones_maternas":    None,
        "poblacion_total":         None,
        "tasa_bruta_por_mil":      None,
        "fuente_dato":             "WORLD_MORTALITY",
    })

    print_log(f"  -> {len(df_out):,} registros del World Mortality procesados.")
    return df_out


def _procesar_centroamerica(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforma sandbox_centroamerica al esquema común.
    Centroamérica ya tiene formato anual — se adapta al esquema unificado.
    """
    print_log("Procesando Centroamérica (RDS)...")

    # Filtrar rango de años
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df = df[df["anio"].between(2015, 2024)]

    # Eliminar nulos críticos
    df = df[df["pais"].notna()]
    df = df[df["defunciones_general"].notna()]

    # Mapeo de nombre de país a ISO3
    MAPA_ISO3 = {
        "Panama":     "PAN",
        "Costa Rica": "CRI",
    }

    df["iso3c"] = df["pais"].str.strip().str.title().map(MAPA_ISO3)

    # Eliminar duplicados
    total_antes = len(df)
    df = df.drop_duplicates(subset=["pais", "anio"])
    print_log(f"  -> Deduplicación: eliminados {total_antes - len(df):,} duplicados.")

    # Construir esquema común
    # Centroamérica es anual → time=1, time_unit='yearly'
    df_out = pd.DataFrame({
        "iso3c":                   df["iso3c"],
        "pais":                    df["pais"].str.strip().str.title(),
        "anio":                    df["anio"].astype("Int16"),
        "periodo_tiempo":          1,
        "unidad_tiempo":           "yearly",
        "defunciones_total":       pd.to_numeric(df["defunciones_general"], errors="coerce"),
        "defunciones_infantiles":  pd.to_numeric(df["defunciones_infantil_menores_de_un_anio"], errors="coerce"),
        "defunciones_menores_5":   pd.to_numeric(df["defunciones_menores_de_5_anios"],         errors="coerce"),
        "defunciones_maternas":    pd.to_numeric(df["defunciones_materna"],                    errors="coerce"),
        "poblacion_total":         pd.to_numeric(df["poblacion_total"],                        errors="coerce"),
        "tasa_bruta_por_mil":      pd.to_numeric(df["tasa_bruta_mortalidad_por_mil"],          errors="coerce"),
        "fuente_dato":             "CENTROAMERICA_RDS",
    })

    print_log(f"  -> {len(df_out):,} registros de Centroamérica procesados.")
    return df_out


def transform_mortalidad_mundial_stage(db_url: str):
    print_log("Conectando a la base de datos...")
    engine = create_engine(db_url, pool_pre_ping=True)

    # 1. Extracción desde Sandbox
    print_log("Leyendo tablas desde la capa Sandbox...")
    df_world  = pd.read_sql('SELECT * FROM sandbox.sandbox_world_mortality', engine)
    df_ca     = pd.read_sql('SELECT * FROM sandbox.sandbox_centroamerica',   engine)
    print_log(f"-> World Mortality: {len(df_world):,} filas | Centroamérica: {len(df_ca):,} filas")

    # 2. Procesar cada fuente al esquema común
    df_world_proc = _procesar_world_mortality(df_world)
    df_ca_proc    = _procesar_centroamerica(df_ca)

    # 3. Consolidar ambas fuentes
    print_log("Consolidando ambas fuentes en una sola tabla...")
    df_stage = pd.concat([df_world_proc, df_ca_proc], ignore_index=True)

    # 4. Columnas derivadas comunes
    df_stage["periodo"]      = df_stage["anio"].apply(_clasificar_periodo)
    df_stage["fuente_origen"] = "MORTALIDAD_MUNDIAL_STAGE"
    df_stage["fecha_carga"]   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # EDA resumen
    print_log("─" * 60)
    print_log("EDA LOCAL — stage_mortalidad_mundial")
    print_log("─" * 60)
    print_log(f"Shape                : {df_stage.shape}")
    print_log(f"Países únicos        : {df_stage['iso3c'].nunique()}")
    print_log(f"Rango de años        : {df_stage['anio'].min()} — {df_stage['anio'].max()}")
    print_log(f"Fuentes de dato:\n{df_stage['fuente_dato'].value_counts().to_string()}")
    print_log(f"Períodos:\n{df_stage['periodo'].value_counts().to_string()}")
    print_log(f"Top 5 filas:\n{df_stage.head(5).to_string()}")
    print_log("─" * 60)

    # 5. Carga a Stage
    print_log(f"Inyectando {len(df_stage):,} registros a stage.stage_mortalidad_mundial...")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))

    df_stage.to_sql(
        name="stage_mortalidad_mundial",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=2000,
        method="multi",
    )

    engine.dispose()
    print_log("CARGA EXITOSA A STAGE COMPLETADA — stage_mortalidad_mundial")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: Transformación Mortalidad Mundial -> Stage")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    db_url = os.getenv("SANDBOX_DB_URL")
    if not db_url:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en el entorno.")

    transform_mortalidad_mundial_stage(db_url)