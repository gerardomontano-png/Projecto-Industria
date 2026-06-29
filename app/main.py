"""
Punto de entrada principal de la aplicación.

Inicializa la instancia de FastAPI con la configuración del proyecto
y registra todos los routers disponibles.
"""

from fastapi import FastAPI

from app.core.config import get_settings
from app.api.routers import health, inference


def create_app() -> FastAPI:
    """
    Construye y configura la aplicación FastAPI.

    Lee la configuración centralizada para establecer el título y la versión
    expuestos en la documentación automática (Swagger / ReDoc), luego registra
    cada router de la API.

    Returns:
        FastAPI: Instancia lista para ser servida por el servidor ASGI.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version_api,
    )

    # Rutas de diagnóstico y estado del servicio
    app.include_router(health.router)

    # Rutas de inferencia del modelo de machine learning
    app.include_router(inference.router)

    return app


# Instancia global consumida por el servidor ASGI (uvicorn app.main:app)
app = create_app()
