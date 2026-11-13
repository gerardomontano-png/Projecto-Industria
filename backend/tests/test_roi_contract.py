"""
Pruebas del contrato de ROI con coordenadas absolutas — BACKEND.

Cubren el contrato en tres niveles: el validador puro, el endpoint REST (error
400 estructurado) y el WebSocket (error estructurado sin cerrar la conexión).

Criterios cubiertos:
  - Solo valores numéricos finitos.
  - x1 < x2, y1 < y2 y área positiva.
  - La ROI se limita o rechaza de forma controlada al exceder el frame.
  - Una ROI inválida genera un error estructurado sin cerrar el WebSocket.
  - La ausencia de ROI representa el frame completo.
  - Pruebas de valores válidos, límites, coordenadas invertidas y área nula.

Ejecutar:
    cd backend
    python -m pytest tests/test_roi_contract.py -v
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.roi_contract import (
    ROI_INCOMPLETE,
    ROI_NOT_FINITE,
    ROI_NOT_ORDERED,
    ROI_OUT_OF_BOUNDS,
    ROI,
    ROIValidationError,
    parse_roi_request,
    validate_roi,
)
from app.services.roi_resolver import resolve_roi_absolute

FRAME_W, FRAME_H = 640, 480


def frame(w=FRAME_W, h=FRAME_H):
    return np.zeros((h, w, 3), dtype=np.uint8)


# ── El validador: valores finitos ────────────────────────────────────────────

@pytest.mark.parametrize("x1,y1,x2,y2", [
    (float("nan"), 0, 10, 10),
    (0, float("inf"), 10, 10),
    (0, 0, float("-inf"), 10),
    (0, 0, 10, float("nan")),
])
def test_no_finitos_se_rechazan(x1, y1, x2, y2):
    with pytest.raises(ROIValidationError) as info:
        validate_roi(x1, y1, x2, y2)
    assert info.value.code == ROI_NOT_FINITE


@pytest.mark.parametrize("valor", ["10", "abc", None, [1, 2], True])
def test_no_numericos_se_rechazan(valor):
    with pytest.raises(ROIValidationError) as info:
        validate_roi(valor, 0, 100, 100)
    assert info.value.code == ROI_NOT_FINITE


def test_enteros_y_flotantes_finitos_se_aceptan():
    r1 = validate_roi(10, 20, 110, 160)
    r2 = validate_roi(10.0, 20.9, 110.2, 160.7)   # se truncan a enteros de píxel
    assert r1.to_dict() == {"x1": 10, "y1": 20, "x2": 110, "y2": 160}
    assert r2.x1 == 10 and r2.x2 == 110


# ── Orden y área positiva ────────────────────────────────────────────────────

@pytest.mark.parametrize("x1,y1,x2,y2, motivo", [
    (110, 20, 10, 160, "x invertida"),
    (10, 160, 110, 20, "y invertida"),
    (10, 20, 10, 160, "ancho cero"),
    (10, 20, 110, 20, "alto cero"),
    (10, 20, 10, 20, "área nula total"),
])
def test_orden_y_area_se_validan(x1, y1, x2, y2, motivo):
    with pytest.raises(ROIValidationError) as info:
        validate_roi(x1, y1, x2, y2)
    assert info.value.code == ROI_NOT_ORDERED, motivo


def test_la_roi_invertida_no_se_corrige_en_silencio():
    """El contrato RECHAZA una ROI invertida; no la arregla con min/max."""
    with pytest.raises(ROIValidationError):
        validate_roi(110, 20, 10, 160)
    # Una válida sí pasa y conserva sus coordenadas tal cual
    r = validate_roi(10, 20, 110, 160)
    assert r.x1 == 10 and r.x2 == 110


def test_propiedades_de_la_roi():
    r = ROI(10, 20, 110, 170)
    assert r.width == 100 and r.height == 150
    assert r.area == 15000
    assert r.offset == (10, 20)
    assert r.as_xywh() == [10, 20, 100, 150]


# ── Límites del frame: rechazar o limitar ────────────────────────────────────

def test_dentro_del_frame_se_acepta():
    r = validate_roi(0, 0, FRAME_W, FRAME_H, frame_width=FRAME_W, frame_height=FRAME_H)
    assert r.area == FRAME_W * FRAME_H


@pytest.mark.parametrize("x1,y1,x2,y2", [
    (-1, 0, 100, 100),          # izquierda fuera
    (0, -1, 100, 100),          # arriba fuera
    (0, 0, FRAME_W + 1, 100),   # derecha fuera
    (0, 0, 100, FRAME_H + 1),   # abajo fuera
])
def test_fuera_del_frame_se_rechaza_por_defecto(x1, y1, x2, y2):
    with pytest.raises(ROIValidationError) as info:
        validate_roi(x1, y1, x2, y2, frame_width=FRAME_W, frame_height=FRAME_H)
    assert info.value.code == ROI_OUT_OF_BOUNDS


def test_fuera_del_frame_con_clamp_se_limita():
    r = validate_roi(-50, -50, FRAME_W + 100, FRAME_H + 100,
                     frame_width=FRAME_W, frame_height=FRAME_H, clamp=True)
    assert r.to_dict() == {"x1": 0, "y1": 0, "x2": FRAME_W, "y2": FRAME_H}


def test_clamp_de_una_roi_enteramente_fuera_se_rechaza():
    # Una ROI completamente a la derecha del frame queda sin área tras limitar
    with pytest.raises(ROIValidationError) as info:
        validate_roi(FRAME_W + 10, 10, FRAME_W + 100, 100,
                     frame_width=FRAME_W, frame_height=FRAME_H, clamp=True)
    assert info.value.code == ROI_OUT_OF_BOUNDS


# ── parse_roi_request: ausencia e incompletos ────────────────────────────────

def test_sin_roi_es_frame_completo():
    assert parse_roi_request(None, None, None, None) is None


def test_roi_incompleta_se_rechaza():
    with pytest.raises(ROIValidationError) as info:
        parse_roi_request(10, 20, None, 160)
    assert info.value.code == ROI_INCOMPLETE


# ── resolve_roi_absolute: recorte real ───────────────────────────────────────

def test_resolver_sin_roi_devuelve_frame_completo():
    img = frame()
    cropped, roi, offset = resolve_roi_absolute(img)
    assert cropped.shape == img.shape
    assert roi is None and offset == (0, 0)


def test_resolver_recorta_la_region():
    img = frame()
    cropped, roi, offset = resolve_roi_absolute(img, 10, 20, 110, 170)
    assert cropped.shape == (150, 100, 3)   # alto, ancho, canales
    assert roi == [10, 20, 100, 150]
    assert offset == (10, 20)


def test_resolver_propaga_el_error_de_contrato():
    with pytest.raises(ROIValidationError):
        resolve_roi_absolute(frame(), 110, 20, 10, 170)   # invertida


# ── REST: error 400 estructurado ─────────────────────────────────────────────

class _FakeInference:
    """Doble del servicio de inferencia: no carga YOLO, devuelve una detección fija."""

    def list_models(self):
        return [{"id": "yolo", "task": "localization", "backend": "ultralytics"}]

    def localize(self, image, model_id, conf, iou, offset=(0, 0)):
        h, w = image.shape[:2]
        ox, oy = offset
        # El schema de LocalizationResponse del repo espera bbox como objeto
        # {x1,y1,x2,y2}. El doble lo devuelve en esa forma para no depender de
        # cambios de schema de otras tareas.
        return (model_id or "yolo"), [
            {"class_id": 0, "class_name": "pieza", "confidence": 0.9,
             "bbox": {"x1": float(ox), "y1": float(oy),
                      "x2": float(ox + min(10, w)), "y2": float(oy + min(10, h))}}
        ]


@pytest.fixture
def client(monkeypatch):
    from app.api.routers import inference
    # Se reemplaza el servicio real por el doble para no cargar YOLO (evita 503).
    monkeypatch.setattr(inference, "inference_service", _FakeInference())
    app = FastAPI()
    app.include_router(inference.router)
    return TestClient(app)


def png_bytes(w=FRAME_W, h=FRAME_H):
    import cv2
    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), dtype=np.uint8))
    return buf.tobytes()


def test_rest_sin_roi_procesa_el_frame_completo(client):
    r = client.post("/inference/localization",
                    files={"image": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json()["roi"] is None


def test_rest_roi_valida(client):
    r = client.post("/inference/localization",
                    params={"x1": 10, "y1": 20, "x2": 110, "y2": 170},
                    files={"image": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["roi"] == [10, 20, 100, 150]
    assert body["roi_points"] == [10, 20, 110, 170]


@pytest.mark.parametrize("params, codigo", [
    ({"x1": 110, "y1": 20, "x2": 10, "y2": 170}, ROI_NOT_ORDERED),      # invertida
    ({"x1": 10, "y1": 20, "x2": 10, "y2": 170}, ROI_NOT_ORDERED),       # área nula
    ({"x1": 0, "y1": 0, "x2": 9999, "y2": 100}, ROI_OUT_OF_BOUNDS),     # fuera
    ({"x1": 10, "y1": 20, "x2": 110}, ROI_INCOMPLETE),                  # incompleta
])
def test_rest_roi_invalida_da_400_estructurado(client, params, codigo):
    r = client.post("/inference/localization", params=params,
                    files={"image": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["error"] == codigo
    assert detail["field"] == "roi"
    assert detail["message"]


def test_rest_roi_fuera_con_clamp_se_procesa(client):
    r = client.post("/inference/localization",
                    params={"x1": -50, "y1": -50, "x2": 9999, "y2": 9999, "clamp": True},
                    files={"image": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json()["roi"] == [0, 0, FRAME_W, FRAME_H]


def test_rest_no_finito_lo_rechaza_fastapi_o_el_contrato(client):
    # 'nan' como texto: FastAPI no lo acepta como float → 422; un número real no finito
    # no puede viajar por query, así que este caso lo cubre la validación de tipo.
    r = client.post("/inference/localization",
                    params={"x1": "abc", "y1": 20, "x2": 110, "y2": 170},
                    files={"image": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 422   # error de validación de tipo de FastAPI


# ── WebSocket: error estructurado SIN cerrar la conexión ─────────────────────

def test_ws_roi_invalida_no_cierra_la_conexion():
    """
    El punto crítico del contrato: un ROI inválido en el stream de inferencia
    avisa con un mensaje estructurado y el video SIGUE, sin cerrar el socket.
    """
    import asyncio
    import contextlib

    from app.services.frame_slot import FrameSlot
    from app.services.roi_contract import ROIValidationError
    from app.services.stream_runner import _inference_loop, _Detections

    class FakeWS:
        def __init__(self):
            self.mensajes = []
            self.cerrado = False

        async def send_json(self, data):
            self.mensajes.append(data)

        async def close(self, code=1000):
            self.cerrado = True

    def infer_con_roi_mala(frame):
        raise ROIValidationError("ROI_NOT_ORDERED", "x1 >= x2")

    async def escenario():
        ws = FakeWS()
        slot = FrameSlot()
        dets = _Detections()
        tarea = asyncio.create_task(_inference_loop(ws, slot, infer_con_roi_mala, 1, dets))
        # Publicar unos frames: la inferencia fallará, pero el bucle no debe morir
        for i in range(3):
            slot.publish(np.zeros((8, 8, 3), dtype=np.uint8), float(i))
            await asyncio.sleep(0.02)
        viva = not tarea.done()
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
        return ws, viva, dets

    ws, viva, dets = asyncio.run(escenario())

    assert viva is True                 # el bucle de inferencia sigue vivo
    assert ws.cerrado is False          # NO se cerró el socket
    assert len(ws.mensajes) == 1        # se avisó una vez (no una por frame)
    assert ws.mensajes[0]["error"] == "ROI_NOT_ORDERED"
    assert ws.mensajes[0]["connected"] is True
    assert dets.items == []             # sin detecciones mientras la ROI es inválida


def test_ws_roi_vuelve_a_avisar_tras_recuperarse():
    """Si la ROI se arregla y vuelve a fallar, se avisa de nuevo (no se silencia para siempre)."""
    import asyncio
    import contextlib

    from app.services.frame_slot import FrameSlot
    from app.services.roi_contract import ROIValidationError
    from app.services.stream_runner import _inference_loop, _Detections

    estado = {"fallar": True, "llamadas": 0}

    class FakeWS:
        def __init__(self):
            self.mensajes = []
            self.cerrado = False

        async def send_json(self, data):
            self.mensajes.append(data)

        async def close(self, code=1000):
            self.cerrado = True

    def infer(frame):
        estado["llamadas"] += 1
        if estado["fallar"]:
            raise ROIValidationError("ROI_NOT_ORDERED", "x1 >= x2")
        return [{"class_id": 0}]

    async def escenario():
        ws = FakeWS()
        slot = FrameSlot()
        dets = _Detections()
        tarea = asyncio.create_task(_inference_loop(ws, slot, infer, 1, dets))
        slot.publish(np.zeros((8, 8, 3), dtype=np.uint8), 0.0)   # falla → avisa
        await asyncio.sleep(0.02)
        estado["fallar"] = False
        slot.publish(np.zeros((8, 8, 3), dtype=np.uint8), 1.0)   # ok
        await asyncio.sleep(0.02)
        estado["fallar"] = True
        slot.publish(np.zeros((8, 8, 3), dtype=np.uint8), 2.0)   # vuelve a fallar → avisa otra vez
        await asyncio.sleep(0.02)
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
        return ws

    ws = asyncio.run(escenario())
    assert ws.cerrado is False
    assert len(ws.mensajes) == 2   # avisó dos veces: una por cada racha de fallo
