"""
Pruebas del alcance MVP: una sola cámara (camera_id=0) y un solo cliente.

Criterios cubiertos:
  - Solo camera_id=0 se acepta en /ws/stream, /ws/inference-stream y
    POST /cameras/session/start; cualquier otro id recibe INVALID_CAMERA_ID
    estructurado sin abrir ninguna captura.
  - Una segunda conexión concurrente no abre otra captura y recibe CAMERA_BUSY,
    también entre los dos WebSockets (comparten la sesión centralizada).
  - El cierre del cliente libera la sesión y permite reconectar.
  - Una cámara no disponible produce un error controlado y no deja recursos
    bloqueados.
  - En el stream de inferencia, un ROI fuera del frame se recorta en vez de
    cortar la conexión; un ROI vacío se rechaza con INVALID_ROI.

Sin cámara física ni modelos: `open_camera` y la inferencia se simulan.

Ejecutar:
    cd backend
    python -m pytest tests/test_mvp_single_camera.py -v
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import cameras as cameras_router
from app.api.routers import inference as inference_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import CameraSessionManager

FRAME_W, FRAME_H = 64, 48


# ── Dobles de prueba ─────────────────────────────────────────────────────────

class CameraStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
        self.active = 0
        self.available = True

    def opened(self) -> None:
        with self._lock:
            self.opens += 1
            self.active += 1

    def closed(self) -> None:
        with self._lock:
            self.active -= 1


class FakeCapture:
    is_opened = True

    def __init__(self, stats: CameraStats) -> None:
        self._stats = stats
        self._released = False
        stats.opened()

    def read_frame(self):
        time.sleep(0.005)
        return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._stats.closed()


class FakeInference:
    def __init__(self) -> None:
        self.crops: list[tuple[int, int]] = []
        self.offsets: list[tuple[int, int]] = []
        self.params: list[tuple[float, float]] = []

    def localize(self, frame, model_id, conf, iou, offset):
        self.params.append((conf, iou))
        self.crops.append(frame.shape[:2])
        self.offsets.append(offset)
        return "fake-model", [{"label": "pieza", "confidence": 0.9}]


@pytest.fixture
def stats(monkeypatch) -> CameraStats:
    camera_stats = CameraStats()

    def fake_open(source: str):
        return FakeCapture(camera_stats) if camera_stats.available else None

    monkeypatch.setattr(manager_module, "open_camera", fake_open)
    return camera_stats


@pytest.fixture
def fake_inference(monkeypatch) -> FakeInference:
    fake = FakeInference()
    monkeypatch.setattr(inference_router, "inference_service", fake)
    return fake


@pytest.fixture
def gestor(monkeypatch, stats) -> CameraSessionManager:
    nuevo = CameraSessionManager()
    for router in (stream_router, inference_router, cameras_router):
        monkeypatch.setattr(router, "camera_session_manager", nuevo)
    return nuevo


@pytest.fixture
def client(gestor, fake_inference):
    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(inference_router.router)
    app.include_router(cameras_router.router)
    with TestClient(app) as test_client:
        yield test_client


def esperar(condicion, limite: float = 2.0) -> None:
    fin = time.monotonic() + limite
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        time.sleep(0.01)


def esperar_fin(ws) -> tuple[dict, int]:
    """Descarta frames hasta el mensaje JSON de fin y devuelve (mensaje, código)."""
    while True:
        mensaje = ws.receive()
        if mensaje.get("text"):
            datos = json.loads(mensaje["text"])
            cierre = ws.receive()
            assert cierre["type"] == "websocket.close"
            return datos, cierre["code"]


# ── Identificadores inválidos ────────────────────────────────────────────────

INVALID_IDS = ["1", "2", "-1", "00", " 0", "abc", "rtsp://10.0.0.5/stream", "/dev/video0"]


@pytest.mark.parametrize("camera_id", INVALID_IDS)
@pytest.mark.parametrize("ruta", ["/ws/stream", "/ws/inference-stream"])
def test_websocket_rechaza_camera_id_invalido(client, gestor, stats, ruta, camera_id):
    with client.websocket_connect(ruta, params={"camera_id": camera_id}) as ws:
        rechazo, codigo = esperar_fin(ws)

    assert rechazo["connected"] is False
    assert rechazo["error"] == "INVALID_CAMERA_ID"
    assert rechazo["description"]
    assert codigo == 1008
    assert stats.opens == 0                       # no se tocó el hardware
    assert gestor.state.value == "idle"


@pytest.mark.parametrize("camera_id", INVALID_IDS)
def test_rest_start_rechaza_camera_id_invalido(client, gestor, stats, camera_id):
    respuesta = client.post("/cameras/session/start", params={"camera_id": camera_id})

    assert respuesta.status_code == 400
    cuerpo = respuesta.json()
    assert cuerpo["error"] == "INVALID_CAMERA_ID"
    assert cuerpo["meta"]["description"]
    assert stats.opens == 0
    assert gestor.state.value == "idle"


def test_camera_id_invalido_no_afecta_a_la_sesion_activa(client, gestor, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["connected"] is True
        ws.receive_bytes()

        with client.websocket_connect("/ws/stream?camera_id=1") as otro:
            rechazo, _ = esperar_fin(otro)
        assert rechazo["error"] == "INVALID_CAMERA_ID"

        ws.receive_bytes()                        # el cliente válido sigue recibiendo
        assert stats.opens == 1


def test_camera_id_cero_es_el_valor_por_defecto(client, stats):
    with client.websocket_connect("/ws/stream") as ws:
        bienvenida = ws.receive_json()
    assert bienvenida["connected"] is True
    assert bienvenida["camera_id"] == "0"


# ── Concurrencia ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "primera, segunda",
    [
        ("/ws/stream", "/ws/stream"),
        ("/ws/stream", "/ws/inference-stream"),
        ("/ws/inference-stream", "/ws/stream"),
        ("/ws/inference-stream", "/ws/inference-stream"),
    ],
)
def test_segunda_conexion_recibe_camera_busy_sin_abrir_otra_captura(
    client, gestor, stats, primera, segunda
):
    with client.websocket_connect(f"{primera}?camera_id=0") as ws:
        bienvenida = ws.receive_json()
        ws.receive_bytes()

        with client.websocket_connect(f"{segunda}?camera_id=0") as otro:
            rechazo, codigo = esperar_fin(otro)

        assert rechazo["error"] == "CAMERA_BUSY"
        assert codigo == 1008
        assert stats.opens == 1 and stats.active == 1
        # La sesión centralizada sigue siendo la del primer cliente
        assert gestor.session.active_client == bienvenida["client_id"]
        ws.receive_bytes()


# ── Cierre y reapertura ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ruta", ["/ws/stream", "/ws/inference-stream"])
def test_cierre_libera_la_sesion_y_permite_reconectar(client, gestor, stats, ruta):
    for intento in range(1, 4):
        with client.websocket_connect(f"{ruta}?camera_id=0") as ws:
            assert ws.receive_json()["connected"] is True
            ws.receive_bytes()
        esperar(lambda: gestor.state.value == "idle" and stats.active == 0)
        assert stats.opens == intento


def test_otro_endpoint_puede_tomar_la_camara_tras_el_cierre(client, gestor, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
    esperar(lambda: gestor.state.value == "idle")

    with client.websocket_connect("/ws/inference-stream?camera_id=0") as ws:
        assert ws.receive_json()["connected"] is True
        ws.receive_bytes()
    esperar(lambda: stats.active == 0)


# ── Cámara no disponible ─────────────────────────────────────────────────────

def test_camara_no_disponible_error_controlado_sin_recursos_bloqueados(client, gestor, stats):
    stats.available = False
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        rechazo, codigo = esperar_fin(ws)

    assert rechazo["error"] == "CAMERA_UNAVAILABLE"
    assert codigo == 1000
    assert gestor.state.value == "idle"
    assert gestor.session is None
    assert stats.active == 0

    # La cámara vuelve: la siguiente conexión funciona con normalidad
    stats.available = True
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["connected"] is True
        ws.receive_bytes()
    esperar(lambda: stats.active == 0)


def test_rest_start_con_camara_no_disponible(client, gestor, stats):
    stats.available = False
    respuesta = client.post("/cameras/session/start", params={"camera_id": "0"})
    assert respuesta.status_code == 503
    assert respuesta.json()["error"] == "CAMERA_UNAVAILABLE"
    assert gestor.state.value == "idle"


# ── ROI en el stream de inferencia ───────────────────────────────────────────

def _primer_frame_con_detecciones(ws) -> dict:
    for _ in range(100):
        frame = ws.receive_bytes()
        longitud = int.from_bytes(frame[:4], "big")
        metadatos = json.loads(frame[4:4 + longitud])
        if metadatos["detections"]:
            return metadatos
    raise AssertionError("no llegaron detecciones")


def test_roi_mas_grande_que_el_frame_se_recorta_sin_cortar_el_stream(client, fake_inference):
    # El frontend calculó el ROI con 1920x1080 pero la cámara entrega 64x48
    params = "camera_id=0&infer_every_n_frames=1&x1=10&y1=8&x2=1920&y2=1080"
    with client.websocket_connect(f"/ws/inference-stream?{params}") as ws:
        assert ws.receive_json()["connected"] is True
        _primer_frame_con_detecciones(ws)

    assert fake_inference.crops[0] == (FRAME_H - 8, FRAME_W - 10)
    assert fake_inference.offsets[0] == (10, 8)


def test_roi_vacio_tras_recortar_cierra_con_invalid_roi(client, gestor, stats):
    params = "camera_id=0&infer_every_n_frames=1&x1=2000&y1=2000&x2=2100&y2=2100"
    with client.websocket_connect(f"/ws/inference-stream?{params}") as ws:
        assert ws.receive_json()["connected"] is True
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "INVALID_ROI"
    assert codigo == 1008
    esperar(lambda: gestor.state.value == "idle" and stats.active == 0)


# ── Ajuste en vivo de conf/iou (HU-08) ───────────────────────────────────────

def _esperar_param(ws, fake: FakeInference, condicion) -> None:
    for _ in range(300):
        ws.receive_bytes()
        if fake.params and condicion(fake.params[-1]):
            return
    raise AssertionError(f"el parámetro no llegó a la inferencia: {fake.params[-3:]}")


def test_config_en_vivo_cambia_conf_e_iou_sin_reconectar(client, stats, fake_inference):
    url = "/ws/inference-stream?camera_id=0&infer_every_n_frames=1&conf=0.25&iou=0.45"
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["connected"] is True
        _esperar_param(ws, fake_inference, lambda p: p == (0.25, 0.45))

        ws.send_json({"type": "config", "conf": 0.7})
        _esperar_param(ws, fake_inference, lambda p: p == (0.7, 0.45))

        ws.send_json({"type": "config", "iou": 0.3})
        _esperar_param(ws, fake_inference, lambda p: p == (0.7, 0.3))

    assert stats.opens == 1                       # la cámara nunca se reabrió


@pytest.mark.parametrize(
    "mensaje",
    [
        "no es json",
        "[1, 2]",
        json.dumps({"type": "config", "conf": 1.5}),
        json.dumps({"type": "config", "conf": "alto"}),
        json.dumps({"type": "config", "conf": True}),
        json.dumps({"type": "otro", "conf": 0.9}),
    ],
)
def test_config_invalida_se_ignora_sin_cortar_el_stream(client, stats, fake_inference, mensaje):
    url = "/ws/inference-stream?camera_id=0&infer_every_n_frames=1&conf=0.25"
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["connected"] is True
        ws.send_text(mensaje)
        ws.send_json({"type": "config", "conf": 0.6})   # un mensaje válido después
        _esperar_param(ws, fake_inference, lambda p: p[0] == 0.6)

    assert all(conf in (0.25, 0.6) for conf, _ in fake_inference.params)
    assert stats.opens == 1


def test_stream_sin_inferencia_ignora_mensajes_de_control(client, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["connected"] is True
        ws.send_json({"type": "config", "conf": 0.6})
        ws.receive_bytes()
        ws.receive_bytes()
