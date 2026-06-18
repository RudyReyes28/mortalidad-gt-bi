import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Módulo de Transformación: MSPAS COVID Sandbox -> Stage (stage_mspas_covid)

Este script realiza la limpieza, estandarización y enriquecimiento de los datos
de fallecidos por COVID-19 del MSPAS (2020-2024), preparándolos para la capa
Stage del Data Warehouse.

Transformaciones aplicadas:
1. Selección y Filtrado:
   - Eliminación de registros con fecha_fallecimiento nula.
   - Eliminación de registros con fallecidos <= 0.
   - Filtro de fechas fuera del rango válido (2020-2024).
   - Eliminación de duplicados exactos por municipio-fecha.

2. Normalización de Tipos:
   - 'fecha_fallecimiento' convertida a DATE.
   - 'fallecidos', 'poblacion', códigos a Integer nullable.
   - Nombres de departamento y municipio normalizados a título.

3. Cálculos Derivados (Reglas de Negocio):
   - 'anio': extraído de la fecha de fallecimiento.
   - 'mes': extraído de la fecha de fallecimiento.
   - 'periodo': clasificación temporal COVID / post-COVID.
   - 'tasa_por_100k': tasa de fallecidos por 100,000 habitantes (cuando poblacion > 0).

4. Trazabilidad:
   - Inyección de metadatos de auditoría ('fuente_origen', 'fecha_carga').
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


def _clasificar_periodo_covid(anio) -> str:
    """Clasifica el año en período COVID o post-COVID."""
    try:
        anio = int(float(anio))
        if anio <= 2021: return "COVID"
        else:            return "post-COVID"
    except:
        return "Ignorado"


def _calcular_tasa(fallecidos, poblacion) -> float:
    """Calcula la tasa de fallecidos por 100,000 habitantes."""
    try:
        f = float(fallecidos)
        p = float(poblacion)
        if p > 0:
            return round((f / p) * 100_000, 4)
        return None
    except:
        return None


def _normalizar_texto(valor) -> str:
    """Normaliza texto: strip y título."""
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    return str(valor).strip().title()


def transform_mspas_covid_stage(db_url: str):
    print_log("Conectando a la base de datos...")
    engine = create_engine(db_url, pool_pre_ping=True)

    # 1. Extracción desde Sandbox
    print_log("Leyendo sandbox.sandbox_mspas_covid...")
    df = pd.read_sql('SELECT * FROM sandbox.sandbox_mspas_covid', engine)
    print_log(f"-> {len(df):,} filas leídas del Sandbox COVID.")

    # 2. Filtrado — eliminar nulos críticos
    total_antes = len(df)
    df = df[df["fecha_fallecimiento"].notna()]
    df = df[df["fallecidos"].notna()]
    df = df[pd.to_numeric(df["fallecidos"], errors="coerce") > 0]
    print_log(f"-> Filtro nulos/ceros: descartados {total_antes - len(df):,} registros.")

    # 3. Conversión de fecha y filtro de rango válido
    df["fecha_fallecimiento"] = pd.to_datetime(df["fecha_fallecimiento"], errors="coerce")
    total_antes = len(df)
    df = df[df["fecha_fallecimiento"].dt.year.between(2020, 2024)]
    print_log(f"-> Filtro rango 2020-2024: descartados {total_antes - len(df):,} registros.")

    # 4. Eliminación de duplicados exactos
    total_antes = len(df)
    df = df.drop_duplicates(subset=["municipio", "fecha_fallecimiento"])
    print_log(f"-> Deduplicación: eliminados {total_antes - len(df):,} duplicados.")

    # 5. Transformaciones y columnas derivadas
    print_log("Aplicando transformaciones y reglas de negocio...")

    df["fallecidos"]  = pd.to_numeric(df["fallecidos"],  errors="coerce").astype("Int64")
    df["poblacion"]   = pd.to_numeric(df["poblacion"],   errors="coerce").astype("Int64")
    df["codigo_departamento"] = pd.to_numeric(df["codigo_departamento"], errors="coerce").astype("Int64")
    df["codigo_municipio"]    = pd.to_numeric(df["codigo_municipio"],    errors="coerce").astype("Int64")

    df["anio"]    = df["fecha_fallecimiento"].dt.year.astype("Int16")
    df["mes"]     = df["fecha_fallecimiento"].dt.month.astype("Int16")
    df["periodo"] = df["anio"].apply(_clasificar_periodo_covid)

    df["departamento_norm"] = df["departamento"].apply(_normalizar_texto)
    df["municipio_norm"]    = df["municipio"].apply(_normalizar_texto)

    df["tasa_por_100k"] = df.apply(
        lambda row: _calcular_tasa(row["fallecidos"], row["poblacion"]), axis=1
    )

    # 6. Construcción del DataFrame Stage
    print_log("Ensamblando estructura final Stage...")
    df_stage = pd.DataFrame({
        "fecha_fallecimiento":  df["fecha_fallecimiento"].dt.date,
        "anio":                 df["anio"],
        "mes":                  df["mes"],
        "departamento":         df["departamento_norm"],
        "codigo_departamento":  df["codigo_departamento"],
        "municipio":            df["municipio_norm"],
        "codigo_municipio":     df["codigo_municipio"],
        "poblacion":            df["poblacion"],
        "fallecidos":           df["fallecidos"],
        "tasa_por_100k":        df["tasa_por_100k"],
        "periodo":              df["periodo"],
        "fuente_origen":        "MSPAS_COVID_STAGE",
        "fecha_carga":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # EDA resumen
    print_log("─" * 60)
    print_log("EDA LOCAL — stage_mspas_covid")
    print_log("─" * 60)
    print_log(f"Shape                : {df_stage.shape}")
    print_log(f"Rango de fechas      : {df_stage['fecha_fallecimiento'].min()} — {df_stage['fecha_fallecimiento'].max()}")
    print_log(f"Total fallecidos     : {df_stage['fallecidos'].sum():,}")
    print_log(f"Municipios únicos    : {df_stage['municipio'].nunique()}")
    print_log(f"Períodos:\n{df_stage['periodo'].value_counts().to_string()}")
    print_log(f"Top 5 filas:\n{df_stage.head(5).to_string()}")
    print_log("─" * 60)

    # 7. Carga a Stage
    print_log(f"Inyectando {len(df_stage):,} registros a stage.stage_mspas_covid...")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))

    df_stage.to_sql(
        name="stage_mspas_covid",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=2000,
        method="multi",
    )

    engine.dispose()
    print_log("CARGA EXITOSA A STAGE COMPLETADA — stage_mspas_covid")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: Transformación MSPAS COVID -> Stage")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    db_url = os.getenv("SANDBOX_DB_URL")
    if not db_url:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en el entorno.")

    transform_mspas_covid_stage(db_url)