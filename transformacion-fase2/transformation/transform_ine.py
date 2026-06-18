import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

"""
Módulo de Transformación: INE Sandbox -> Stage (stage_defunciones_gt)

Este script realiza la limpieza, estandarización y enriquecimiento de los datos crudos 
de mortalidad del INE, preparándolos para la capa Stage del Data Warehouse.

Transformaciones aplicadas:
1. Selección y Filtrado:
   - Conservación exclusiva de columnas demográficas, geográficas y temporales clave.
   - Eliminación de registros con causas de defunción (CIE-10) nulas o con formato inválido.

2. Traducción de Catálogos (Resolución de Códigos):
   - Cruce en memoria con 'sandbox_ine_diccionario' para traducir códigos numéricos 
     a etiquetas legibles (Departamento/Municipio de ocurrencia y registro, Sexo, 
     Asistencia Médica, Sitio de Ocurrencia y Pueblo de Pertenencia/Etnia).
   - Cruce con 'sandbox_ine_cie10' para obtener la descripción médica exacta de la causa de muerte.

3. Cálculos Derivados (Reglas de Negocio):
   - 'edad_anios': Conversión estandarizada de edad a años decimales utilizando 
     la magnitud (Edadif) y la unidad de tiempo (Perdif). Asigna NULL a valores ignorados.
   - 'grupo_etario': Clasificación categórica de la edad (ej. "< 1 año", "15-29", "60+").
   - 'periodo': Etiquetado temporal basado en el año de ocurrencia (pre-COVID, COVID, post-COVID).

4. Trazabilidad:
   - Inyección de metadatos de auditoría ('fuente_origen', 'fecha_carga').
"""

def print_log(mensaje):
    hora_actual = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] INFO: {mensaje}")
    sys.stdout.flush() 

# Mapeo Puente: Columnas RAW -> Nombres en el Diccionario 
MAPEO_VARIABLES = {
    "Depreg": "Departamento de registro",
    "Mupreg": "Municipio de registro",
    "Depocu": "Departamento de ocurrencia",
    "Mupocu": "Municipio de ocurrencia",
    "Sexo":   "Sexo del difunto(a)",
    "Asist":  "Asistencia recibida",
    "Ocur":   "Sitio de ocurrencia",
    "Puedif": "Pueblo de pertenencia del difunto(a)" 
}

COLUMNAS_SELECCIONADAS = list(MAPEO_VARIABLES.keys()) + ["Añoocu", "Mesocu", "Edadif", "Perdif", "Caudef"]

# Funciones de Lógica de Negocio 
def _clasificar_periodo(anio) -> str:
    try:
        anio = int(float(anio))
        if anio < 2020: return "pre-COVID"
        elif anio <= 2021: return "COVID"
        else: return "post-COVID"
    except:
        return "Ignorado"

def _calcular_edad_anios(edadif, perdif) -> float:
    try:
        e = float(edadif)
        p = float(perdif)
        if p == 1: return round(e / 365, 2)     # Días
        elif p == 2: return round(e / 12, 2)    # Meses
        elif p == 3: return e                   # Años
        else: return None
    except:
        return None

def _clasificar_grupo_etario(edad_anios) -> str:
    if pd.isna(edad_anios): return "No especificado"
    elif edad_anios < 1: return "< 1 año"
    elif edad_anios < 5: return "1-4"
    elif edad_anios < 15: return "5-14"
    elif edad_anios < 30: return "15-29"
    elif edad_anios < 45: return "30-44"
    elif edad_anios < 60: return "45-59"
    else: return "60+"

def _es_cie10_valido(codigo: str) -> bool:
    if not isinstance(codigo, str): return False
    import re
    return bool(re.match(r'^[A-Z]\d{2,4}', codigo.strip().upper()))

def _construir_diccionario(df_dicc: pd.DataFrame) -> dict:
    dicc = {}
    for _, row in df_dicc.iterrows():
        variable = str(row["variable"]).strip()
        try:
            codigo = str(int(float(row["codigo"])))
        except:
            codigo = str(row["codigo"]).strip()
            
        etiqueta = str(row["etiqueta"]).strip()
        
        if variable not in dicc: dicc[variable] = {}
        dicc[variable][codigo] = etiqueta
    return dicc

def _resolver_codigo(valor, nombre_variable: str, dicc: dict) -> str:
    if pd.isna(valor): return "Ignorado / No especificado"
    try:
        clave = str(int(float(valor)))
    except:
        clave = str(valor).strip()
    return dicc.get(nombre_variable, {}).get(clave, f"Código no encontrado: {clave}")

# Transformación Principal 
def transform_ine_stage(db_url: str):
    print_log("Conectando a la base de datos RDS...")
    engine = create_engine(db_url, pool_pre_ping=True)
    
    # 1. Extracción desde Sandbox
    print_log("Leyendo tablas desde la capa Sandbox...")
    df_ine  = pd.read_sql('SELECT * FROM sandbox.sandbox_ine', engine)
    df_dicc = pd.read_sql('SELECT * FROM sandbox.sandbox_ine_diccionario', engine)
    df_cie  = pd.read_sql('SELECT * FROM sandbox.sandbox_ine_cie10', engine)
    print_log(f"-> Leídas {len(df_ine):,} filas del INE RAW.")

    # 2. Filtrado Inicial
    df = df_ine[COLUMNAS_SELECCIONADAS].copy()
    
    total_antes = len(df)
    df = df[df["Caudef"].notna()]
    df = df[df["Caudef"].astype(str).apply(_es_cie10_valido)]
    print_log(f"-> Filtro CIE-10 descartó {total_antes - len(df):,} registros inválidos.")

    # 3. Preparación de Diccionarios
    dicc_variables = _construir_diccionario(df_dicc)
    dicc_cie10 = dict(zip(df_cie["codigo_cie10"].astype(str).str.strip().str.upper(), df_cie["descripcion"]))

    # 4. Transformaciones de Mapeo
    print_log("Traduciendo códigos usando el diccionario oficial del INE...")
    
    df["nombre_depto_registro"]   = df["Depreg"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Depreg"], dicc_variables))
    df["nombre_muni_registro"]    = df["Mupreg"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Mupreg"], dicc_variables))
    df["nombre_depto_ocurrencia"] = df["Depocu"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Depocu"], dicc_variables))
    df["nombre_muni_ocurrencia"]  = df["Mupocu"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Mupocu"], dicc_variables))
    df["sexo"]                    = df["Sexo"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Sexo"], dicc_variables))
    df["asistencia_medica"]       = df["Asist"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Asist"], dicc_variables))
    df["lugar_ocurrencia"]        = df["Ocur"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Ocur"], dicc_variables))
    df["pueblo_pertenencia"]      = df["Puedif"].apply(lambda x: _resolver_codigo(x, MAPEO_VARIABLES["Puedif"], dicc_variables))

    # 5. Transformaciones Derivadas
    print_log("Calculando edades, grupos etarios y períodos...")
    df["edad_anios"]   = df.apply(lambda row: _calcular_edad_anios(row["Edadif"], row["Perdif"]), axis=1)
    df["grupo_etario"] = df["edad_anios"].apply(_clasificar_grupo_etario)
    df["periodo"]      = df["Añoocu"].apply(_clasificar_periodo)
    
    df["codigo_cie10"]      = df["Caudef"].astype(str).str.strip().str.upper()
    df["descripcion_causa"] = df["codigo_cie10"].map(dicc_cie10).fillna("Sin descripción en catálogo")

    # 6. Construcción del Dataframe Final (Stage)
    print_log("Ensamblando estructura final Stage...")
    df_stage = pd.DataFrame({
        "anio_ocurrencia":          df["Añoocu"].astype("Int16"),
        "mes_ocurrencia":           df["Mesocu"].astype("Int16"),
        "nombre_depto_registro":    df["nombre_depto_registro"],
        "nombre_muni_registro":     df["nombre_muni_registro"],
        "nombre_depto_ocurrencia":  df["nombre_depto_ocurrencia"],
        "nombre_muni_ocurrencia":   df["nombre_muni_ocurrencia"],
        "pueblo_pertenencia":       df["pueblo_pertenencia"], # <--- Nueva columna en tabla final
        "sexo":                     df["sexo"],
        "edad_anios":               df["edad_anios"],
        "grupo_etario":             df["grupo_etario"],
        "codigo_cie10":             df["codigo_cie10"],
        "descripcion_causa":        df["descripcion_causa"],
        "asistencia_medica":        df["asistencia_medica"],
        "lugar_ocurrencia":         df["lugar_ocurrencia"],
        "periodo":                  df["periodo"],
        "fuente_origen":            "INE_STAGE",
        "fecha_carga":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # Imprimir un pequeño resumen EDA antes de cargar
    print_log("\n" + "─" * 60)
    print_log("EDA LOCAL — stage_defunciones_gt")
    print_log("─" * 60)
    print_log(f"Shape              : {df_stage.shape}")
    print_log(f"Top 5 filas:\n{df_stage.head(5).to_string()}")
    print_log("─" * 60 + "\n")

    # 7. Carga a RDS
    print_log(f"Inyectando {len(df_stage):,} registros transformados a la capa STAGE...")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))
    
    df_stage.to_sql(
        name="stage_defunciones_gt",
        con=engine,
        schema="stage",
        if_exists="replace",
        index=False,
        chunksize=2000,
        method="multi",
    )
    
    engine.dispose()
    print_log("CARGA EXITOSA A STAGE COMPLETADA.")

if __name__ == "__main__":
    print_log("======================================================")
    print_log("INICIANDO JOB LOCAL: Transformación INE -> Stage")
    print_log("======================================================")
    
    # Cargamos el archivo .env de forma local
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        env_path = Path(".env") 
         
    load_dotenv(env_path)
    print_log(f"Cargando .env desde: {env_path}")
    
    db_url = os.getenv("SANDBOX_DB_URL")
    
    if not db_url:
        raise EnvironmentError("Variable SANDBOX_DB_URL no encontrada en el entorno.")

    transform_ine_stage(db_url)