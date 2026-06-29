"""
Router de inferencia del modelo de machine learning.

Concentra los endpoints encargados de recibir datos de entrada,
ejecutar predicciones contra el modelo cargado y retornar los resultados.
"""

from fastapi import APIRouter

router = APIRouter(tags=["inference"])
