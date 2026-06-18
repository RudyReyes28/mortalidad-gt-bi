import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Módulo de Transformación: MSPAS MEC Sandbox -> Stage (stage_mspas_mec)

Este script realiza la limpieza, estandarización y enriquecimiento de los datos
de enfermedades crónicas del MSPAS (MEC 2012-2024), preparándolos para la capa
Stage del Data Warehouse.

Transformaciones aplicadas:
1. Selección y Filtrado:
   - Eliminación de registros con CIE-10 nulo o vacío.
   - Eliminación de duplicados exactos.
   - Filtro de registros con año fuera del rango válido (2012-2024).

2. Normalización de Tipos:
   - 'Año' y 'Casos' convertidos a Integer nullable.
   - Strings normalizados a mayúsculas, sin espacios extra.
   - 'Sexo': estandarizado a 'Femenino' / 'Masculino' / 'No especificado'.

3. Cálculos Derivados (Reglas de Negocio):
   - 'periodo': clasificación temporal pre-COVID / COVID / post-COVID.
   - 'codigo_cie10_limpio': normalización del código CIE-10 (mayúsculas, sin espacios).
   - 'capitulo_cie10': capítulo CIE-10 derivado de la letra inicial del código.

4. Trazabilidad:
   - Inyección de metadatos de auditoría ('fuente_origen', 'fecha_carga').
"""


def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush()


# Mapeo de sexo a etiqueta legible
MAPA_SEXO = {
    "F": "Femenino",
    "M": "Masculino",
}

# Capítulos CIE-10 por letra inicial
CAPITULOS_CIE10 = {
    "A": "Enfermedades infecciosas y parasitarias",
    "B": "Enfermedades infecciosas y parasitarias",
    "C": "Tumores / Neoplasias",
    "D": "Tumores / Enfermedades de la sangre",
    "E": "Enfermedades endocrinas y metabólicas",
    "F": "Trastornos mentales",
    "G": "Enfermedades del sistema nervioso",
    "H": "Enfermedades del ojo y oído",
    "I": "Enfermedades del sistema circulatorio",
    "J": "Enfermedades del sistema respiratorio",
    "K": "Enfermedades del sistema digestivo",
    "L": "Enfermedades de la piel",
    "M": "Enfermedades del sistema musculoesquelético",
    "N": "Enfermedades del sistema genitourinario",
    "O": "Embarazo, parto y puerperio",
    "P": "Afecciones del período perinatal",
    "Q": "Malformaciones congénitas",
    "R": "Síntomas y signos no clasificados",
    "S": "Traumatismos y envenenamientos",
    "T": "Traumatismos y envenenamientos",
    "U": "Códigos especiales (COVID-19)",
    "V": "Causas externas",
    "W": "Causas externas",
    "X": "Causas externas",
    "Y": "Causas externas",
    "Z": "Factores que influyen en el estado de salud",
}


def _clasificar_periodo(anio) -> str:
    """Clasifica el año en período pre-COVID, COVID o post-COVID."""
    try:
        anio = int(float(anio))
        if anio < 2020:   return "pre-COVID"
        elif anio <= 2021: return "COVID"
        else:              return "post-COVID"
    except:
        return "Ignorado"


def _normalizar_cie10(codigo) -> str:
    """Normaliza el código CIE-10 a mayúsculas sin espacios."""
    if pd.isna(codigo) or str(codigo).strip() == "":
        return None
    return str(codigo).strip().upper().replace(":", "")


def _capitulo_cie10(codigo_limpio) -> str:
    """Obtiene el capítulo CIE-10 a partir de la letra inicial del código."""
    if not codigo_limpio or len(codigo_limpio) == 0:
        return "No especificado"
    letra = codigo_limpio[0].upper()
    return CAPITULOS_CIE10.get(letra, "Capítulo no identificado")


def _normalizar_sexo(valor) -> str:
    """Estandariza el sexo a etiqueta legible."""
    if pd.isna(valor) or str(valor).strip() == "":
        return "No especificado"
    return MAPA_SEXO.get(str(valor).strip().upper(), "No especificado")


def _normalizar_texto(valor) -> str:
    """Normaliza texto: strip y título."""
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    return str(valor).strip().title()


def transform_mspas_mec_stage(db_url: str):
    print_log("Conectando a la base de datos...")
    engine = create_engine(db_url, pool_pre_ping=True)

    # 1. Extracción desde Sandbox
    print_log("Leyendo sandbox.sandbox_mspas_mec...")
    df = pd.read_sql('SELECT * FROM sandbox.sandbox_mspas_mec', engine)
    print_log(f"-> {len(df):,} filas leídas del Sandbox MEC.")

    # 2. Filtrado — eliminar nulos críticos
    total_antes = len(df)
    df = df[df["CIE-10"].notna()]
    df = df[df["CIE-10"].astype(str).str.strip() != ""]
    df = df[df["Año"].notna()]
    df = df[df["Casos"].notna()]
    print_log(f"-> Filtro nulos: descartados {total_antes - len(df):,} registros.")

    # 3. Filtro de rango de año válido (2012-2024)
    df["Año"] = pd.to_numeric(df["Año"], errors="coerce")
    total_antes = len(df)
    df = df[df["Año"].between(2012, 2024)]
    print_log(f"-> Filtro año (2012-2024): descartados {total_antes - len(df):,} registros.")

    # 4. Eliminación de duplicados exactos
    total_antes = len(df)
    df = df.drop_duplicates(
        subset=["Año", "Departamento", "Municipio", "CIE-10", "Grupo Etario", "Sexo"]
    )
    print_log(f"-> Deduplicación: eliminados {total_antes - len(df):,} duplicados exactos.")

    # 5. Normalización y transformaciones
    print_log("Aplicando transformaciones y reglas de negocio...")

    df["codigo_cie10_limpio"] = df["CIE-10"].apply(_normalizar_cie10)
    df["capitulo_cie10"]      = df["codigo_cie10_limpio"].apply(_capitulo_cie10)
    df["sexo_legible"]        = df["Sexo"].apply(_normalizar_sexo)
    df["departamento_norm"]   = df["Departamento"].apply(_normalizar_texto)
    df["municipio_norm"]      = df["Municipio"].apply(_normalizar_texto)
    df["diagnostico_norm"]    = df["Diagnóstico"].apply(_normalizar_texto)
    df["periodo"]             = df["Año"].apply(_clasificar_periodo)

    # 6. Construcción del DataFrame Stage
    print_log("Ensamblando estructura final Stage...")
    df_stage = pd.DataFrame({
        "anio":               df["Año"].astype("Int16"),
        "departamento":       df["departamento_norm"],
        "municipio":          df["municipio_norm"],
        "codigo_cie10":       df["codigo_cie10_limpio"],
        "diagnostico":        df["diagnostico_norm"],
        "capitulo_cie10":     df["capitulo_cie10"],
        "grupo_etario":       df["Grupo Etario"].astype(str).str.strip(),
        "sexo":               df["sexo_legible"],
        "casos":              pd.to_numeric(df["Casos"], errors="coerce").astype("Int64"),
        "periodo":            df["periodo"],
        "fuente_origen":      "MSPAS_MEC_STAGE",
        "fecha_carga":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # EDA resumen
    print_log("─" * 60)
    print_log("EDA LOCAL — stage_mspas_mec")
    print_log("─" * 60)
    print_log(f"Shape              : {df_stage.shape}")
    print_log(f"Años cubiertos     : {sorted(df_stage['anio'].dropna().unique().tolist())}")
    print_log(f"Períodos:\n{df_stage['periodo'].value_counts().to_string()}")
    print_log(f"Top 5 filas:\n{df_stage.head(5).to_string()}")
    print_log("─" * 60)

    # 7. Carga a Stage
    print_log(f"Inyectando {len(df_stage):,} registros a stage.stage_mspas_mec...")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))

    df_stage.to_sql(
        name="stage_mspas_mec",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=2000,
        method="multi",
    )

    engine.dispose()
    print_log("CARGA EXITOSA A STAGE COMPLETADA — stage_mspas_mec")


if __name__ == "__main__":
    print_log("=" * 60)
    print_log("INICIANDO JOB: Transformación MSPAS MEC -> Stage")
    print_log("=" * 60)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env")

    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")

    db_url = os.getenv("SANDBOX_DB_URL")
    if not db_url:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en el entorno.")

    transform_mspas_mec_stage(db_url)