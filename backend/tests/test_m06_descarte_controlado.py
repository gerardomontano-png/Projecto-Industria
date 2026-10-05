"""
M06: último frame con descarte controlado.

Verifica los criterios de aceptación sin cámara física:
  1. No existen colas sin límite.
  2. La memoria no crece de forma sostenida por frames atrasados.
  3. El único cliente recibe el frame más reciente disponible.
  4. Las métricas permiten observar frames capturados y descartados.

Ejecutar:
    cd backend
    pytest tests/test_m06_descarte_controlado.py -v
"""

import ast
import asyncio
import gc
import json
import struct
import time
import tracemalloc
import weakref
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.services.camera_session_manager import CameraSessionManager
from app.services.frame_slot import FrameSlot
from app.services.stream_runner import serve_camera_stream

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Frame de tamaño real (640×480 BGR ≈ 0.9 MB) para que una fuga se note en memoria.
FRAME_SHAPE = (480, 640, 3)
FRAME_BYTES = int(np.prod(FRAME_SHAPE))


# ── Dobles de prueba ──────────────────────────────────────────────────────────

class TrackedCapture:
    """Cámara falsa que entrega frames nuevos y registra cuáles siguen vivos."""

    is_opened = True

    def __init__(self, read_delay: float = 0.005) -> None:
        self.read_delay = read_delay
        self.reads = 0
        self.release_calls = 0
        self._refs: list[weakref.ref] = []

    def read_frame(self):
        time.sleep(self.read_delay)
        self.reads += 1
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        self._refs.append(weakref.ref(frame))
        return frame

    def alive_frames(self) -> int:
        gc.collect()
        return sum(1 for ref in self._refs if ref() is not None)

    def release(self) -> None:
        self.release_calls += 1


class SlowClient:
    """WebSocket falso: tarda `send_delay` por envío y anota la secuencia recibida."""

    def __init__(self, manager: CameraSessionManager, send_delay: float) -> None:
        self.manager = manager
        self.send_delay = send_delay
        self.received: list[int] = []
        # Secuencia más reciente del slot en el instante de cada envío.
        self.latest_at_send: list[int] = []
        self._disconnect = asyncio.Event()

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        pass

    async def send_bytes(self, data: bytes) -> None:
        (json_len,) = struct.unpack(">I", data[:4])
        meta = json.loads(data[4 : 4 + json_len])
        self.received.append(meta["seq"])
        session = self.manager.session
        if session is not None and session.frames.latest is not None:
            self.latest_at_send.append(session.frames.latest.seq)
        await asyncio.sleep(self.send_delay)

    async def receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def close(self, code: int = 1000) -> None:
        pass

    def disconnect(self) -> None:
        self._disconnect.set()


async def _start(manager, capture, client):
    """Inicia el stream y espera a que la sesión haya abierto la cámara falsa."""
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        task = asyncio.create_task(serve_camera_stream(client, manager, "0", "listo"))
        while manager.session is None:
            await asyncio.sleep(0.005)
    return task


# ── 1. Sin colas sin límite ───────────────────────────────────────────────────

_QUEUE_TYPES = {"Queue", "LifoQueue", "PriorityQueue", "SimpleQueue"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _keyword(node: ast.Call, name: str):
    return next((kw.value for kw in node.keywords if kw.arg == name), None)


def test_no_existen_colas_sin_limite_en_el_backend():
    unbounded = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            where = f"{path.relative_to(APP_DIR)}:{node.lineno}"
            if name == "deque" and _keyword(node, "maxlen") is None and len(node.args) < 2:
                unbounded.append(f"{where} deque sin maxlen")
            if name in _QUEUE_TYPES:
                size = _keyword(node, "maxsize") or (node.args[0] if node.args else None)
                if name == "SimpleQueue" or size is None or (
                    isinstance(size, ast.Constant) and size.value <= 0
                ):
                    unbounded.append(f"{where} {name} sin maxsize")

    assert unbounded == []


def test_slot_tiene_capacidad_de_un_frame():
    assert FrameSlot.CAPACITY == 1


# ── 2. Memoria acotada ────────────────────────────────────────────────────────

def test_slot_sin_consumidor_retiene_un_solo_frame():
    slot = FrameSlot()
    refs = []
    for i in range(200):
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        refs.append(weakref.ref(frame))
        slot.publish(frame, float(i))
        del frame

    gc.collect()
    alive = [ref for ref in refs if ref() is not None]

    assert len(alive) == 1
    assert alive[0]() is slot.latest.frame


def test_cliente_lento_no_acumula_frames_en_memoria():
    async def scenario():
        manager = CameraSessionManager()
        capture = TrackedCapture()
        client = SlowClient(manager, send_delay=0.3)
        task = await _start(manager, capture, client)

        samples = []
        for _ in range(6):
            await asyncio.sleep(0.25)
            samples.append(capture.alive_frames())
        reads = capture.reads

        client.disconnect()
        await asyncio.wait_for(task, timeout=5)
        return samples, reads

    samples, reads = asyncio.run(scenario())

    # Se capturaron decenas de frames, pero vivos nunca hay más que el del slot
    # y los que tienen en uso el emisor y la lectura en curso.
    assert reads >= 30
    assert max(samples) <= 3


def test_memoria_estable_con_cliente_lento_sostenido():
    async def scenario():
        manager = CameraSessionManager()
        capture = TrackedCapture()
        client = SlowClient(manager, send_delay=0.25)
        task = await _start(manager, capture, client)

        await asyncio.sleep(0.5)  # calentamiento: primeras asignaciones
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        readings = []
        for _ in range(4):
            await asyncio.sleep(0.4)
            gc.collect()
            current, _ = tracemalloc.get_traced_memory()
            readings.append(current - baseline)
        reads = capture.reads

        client.disconnect()
        await asyncio.wait_for(task, timeout=5)
        return readings, reads

    tracemalloc.start()
    try:
        readings, reads = asyncio.run(scenario())
    finally:
        tracemalloc.stop()

    # Con ~60+ frames de 0.9 MB capturados en la ventana, una cola los acumularía
    # (decenas de MB). Con descarte controlado el crecimiento queda en pocos frames.
    assert reads >= 40
    assert max(readings) < 4 * FRAME_BYTES
    # Y no hay tendencia creciente entre la primera y la última lectura.
    assert readings[-1] - readings[0] < 2 * FRAME_BYTES


# ── 3. El cliente recibe el frame más reciente ────────────────────────────────

def test_cliente_lento_recibe_siempre_el_frame_mas_reciente():
    async def scenario():
        manager = CameraSessionManager()
        client = SlowClient(manager, send_delay=0.2)
        task = await _start(manager, TrackedCapture(), client)
        await asyncio.sleep(1.2)
        client.disconnect()
        await asyncio.wait_for(task, timeout=5)
        return client

    client = asyncio.run(scenario())

    assert len(client.received) >= 4
    # Lo enviado es el último frame del slot (a lo sumo uno más llegó mientras
    # se codificaba el JPEG), nunca un frame viejo de una cola.
    for sent, latest in zip(client.received, client.latest_at_send):
        assert latest - sent <= 1
    # Entre envíos consecutivos se saltan los frames intermedios.
    gaps = [b - a for a, b in zip(client.received, client.received[1:])]
    assert max(gaps) > 1


# ── 4. Métricas de capturados y descartados ───────────────────────────────────

def test_metricas_permiten_observar_capturados_y_descartados():
    async def scenario():
        manager = CameraSessionManager()
        client = SlowClient(manager, send_delay=0.2)
        task = await _start(manager, TrackedCapture(), client)
        await asyncio.sleep(1.0)
        status = manager.get_status()
        client.disconnect()
        await asyncio.wait_for(task, timeout=5)
        return status, client

    status, client = asyncio.run(scenario())
    captured = status["metrics"]["frames_total"]
    buffer = status["frame_buffer"]
    delivery = status["delivery"]

    assert captured == buffer["frames_published"]
    assert buffer["frames_discarded"] > 0
    assert buffer["frames_consumed"] + buffer["frames_discarded"] <= captured
    assert captured - buffer["frames_consumed"] - buffer["frames_discarded"] <= 1
    # Las métricas de entrega (tomadas antes de desconectar) no superan lo recibido.
    assert 0 < delivery["frames_sent"] <= len(client.received)
    assert delivery["frames_skipped"] > 0
