"""
Módulo de Automatización Web para extracción de tokens y cookies de Microsoft 365
Automatiza el login con credenciales del .env y gestiona la sesión para el MFA en modo 100% oculto.
"""
import os
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

logger = logging.getLogger("pipeline.auth_sharepoint")

# Ruta para persistir la sesión y evitar loguearse en cada corrida
SESSION_PATH = Path(__file__).resolve().parents[1] / "sharepoint_session.json"

def obtener_cookies_sharepoint(site_url: str) -> str:
    """
    Usa Playwright para ingresar automáticamente el correo y contraseña del .env.
    Funciona siempre en modo Headless (oculto). Si requiere MFA, espera la aprobación móvil.
    """
    # Leer credenciales desde el entorno (.env ya cargado por main.py)
    username = os.getenv("SHAREPOINT_USER")
    password = os.getenv("SHAREPOINT_PASSWORD")

    if not username or not password:
        raise ValueError("No se encontraron las variables SHAREPOINT_USER o SHAREPOINT_PASSWORD en el entorno.")

    with sync_playwright() as p:
        storage_state = str(SESSION_PATH) if SESSION_PATH.exists() else None
        
        # Forzamos Headless=True siempre para que nunca se abra la ventana del navegador
        logger.info("Abriendo navegador automatizado en segundo plano (Headless=True)...")
        
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        
        # Navegar a SharePoint
        page.goto(site_url)
        
        # Flujo de login automático si no existe sesión previa
        if not storage_state:
            logger.info("Iniciando flujo de autenticación automática en segundo plano...")
            
            # 1. Introducir el correo electrónico institucional
            page.wait_for_selector("input[type='email']", timeout=15000)
            page.fill("input[type='email']", username)
            page.click("input[type='submit']") # Botón "Siguiente"
            
            # 2. Esperar a que cargue el campo de contraseña de la institución
            page.wait_for_selector("input[type='password']", timeout=15000)
            page.fill("input[type='password']", password)
            page.click("input[type='submit']") # Botón "Iniciar sesión"
            
            # 3. Validar si Microsoft solicita la ventana de aprobación de MFA
            logger.warning("=" * 70)
            logger.warning("¡CREDENCIALES INYECTADAS OCULTAMENTE!")
            logger.warning("Por favor, revisa tu teléfono celular y APRUEBA el MFA ahora mismo.")
            logger.warning("=" * 70)
            
            # 4. Manejar la pantalla opcional de "¿Quiere mantener la sesión iniciada?"
            try:
                # Damos un pequeño tiempo o esperamos el selector del botón "Sí"
                page.wait_for_selector("input[id='idSIButton9']", timeout=20000)
                page.click("input[id='idSIButton9']")
            except Exception:
                # Si no aparece (porque el MFA tarda o se salta), continuamos al paso de espera de URL
                pass

            # 5. Esperar pacientemente hasta que el navegador llegue con éxito al sitio interno de SharePoint
            logger.info("Esperando aprobación en el celular y redirección final a SharePoint...")
            page.wait_for_url("**/sites/OMS_RAW**", timeout=120000) # 2 minutos de tolerancia máximos
            
            # Guardamos la sesión (cookies, tokens y localStorage) para las siguientes ejecuciones
            context.storage_state(path=str(SESSION_PATH))
            logger.info("¡Sesión y Cookies institucionales guardadas con éxito en disco!")

        # Extraer las cookies del contexto del navegador
        cookies = context.cookies()
        browser.close()
        
        # Formatear las cookies para la cabecera HTTP de requests
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        return cookie_string