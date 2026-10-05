"""
Demostración de M06: último frame con descarte controlado.

No necesita cámara ni servidor: una cámara simulada entrega frames de 640×480
a ~30 FPS y un cliente simulado tarda lo que se indique en recibir cada uno,
contra el mismo código que atiende /ws/stream en producción.

Cada segundo muestra lo que expone GET /cameras/session (capturados, entregados,
descartados) junto con los frames que siguen vivos en memoria y la memoria
asignada desde el inicio. Con descarte controlado, ambas se mantienen planas
aunque el cliente vaya muy por detrás de la cámara.

Ejecutar:
    cd backend
    python scripts/demo_m06_descarte.py
"""

from __future__ import annotations

import asyncio
import gc
import json
import struct
import sys
import time
import tracemalloc
import weakref
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.camera_session_manager import CameraSessionManager  # noqa: E402
from app.services.stream_runner import serve_camera_stream  # noqa: E402

SECONDS = 6
FRAME_SHAPE = (480, 640, 3)
FRAME_MB = np.prod(FRAME_SHAPE) / 1e6


class SimulatedCamera:
    is_opened = True

    def __init__(self) -> None:
        self.refs: list[weakref.ref] = []

    def read_frame(self) -> np.ndarray:
        time.sleep(0.005)
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        self.refs.append(weakref.ref(frame))
        return frame

    def alive_frames(self) -> int:
        gc.collect()
        return sum(1 for ref in self.refs if ref() is not None)

    def release(self) -> None:
        pass


class SimulatedClient:
    """Cliente WebSocket que tarda `send_delay` segundos en recibir cada frame."""

    def __init__(self, send_delay: float) -> None:
        self.send_delay = send_delay
        self.last_age_ms = 0.0
        self._disconnect = asyncio.Event()

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        pass

    async def send_bytes(self, data: bytes) -> None:
        (json_len,) = struct.unpack(">I", data[:4])
        meta = json.loads(data[4 : 4 + json_len])
        self.last_age_ms = (time.time() - meta["timestamp"]) * 1000
        await asyncio.sleep(self.send_delay)

    async def receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def close(self, code: int = 1000) -> None:
        pass

    def disconnect(self) -> None:
        self._disconnect.set()


async def run_scenario(label: str, send_delay: float) -> None:
    camera = SimulatedCamera()
    client = SimulatedClient(send_delay)
    manager = CameraSessionManager()

    print(f"\n{label}: el cliente tarda {send_delay * 1000:.0f} ms por frame")
    print("   s | capturados | entregados | descartados | frames vivos | memoria  | antigüedad")
    print("  ---+------------+------------+-------------+--------------+----------+-----------")

    tracemalloc.start()
    with patch("app.services.camera_session_manager.open_camera", return_value=camera):
        task = asyncio.create_task(serve_camera_stream(client, manager, "0", "listo"))
        while manager.session is None:
            await asyncio.sleep(0.005)
    baseline, _ = tracemalloc.get_traced_memory()

    for second in range(1, SECONDS + 1):
        await asyncio.sleep(1.0)
        status = manager.get_status()
        buffer = status["frame_buffer"]
        alive = camera.alive_frames()
        memory_mb = (tracemalloc.get_traced_memory()[0] - baseline) / 1e6
        print(
            f"  {second:>2} | {status['metrics']['frames_total']:>10} "
            f"| {status['delivery']['frames_sent']:>10} "
            f"| {buffer['frames_discarded']:>11} "
            f"| {alive:>12} "
            f"| {memory_mb:>5.1f} MB "
            f"| {client.last_age_ms:>6.0f} ms"
        )

    client.disconnect()
    await task
    tracemalloc.stop()

    backlog = status["metrics"]["frames_total"] - status["delivery"]["frames_sent"]
    if backlog > 1:
        print(
            f"  Sin descarte, una cola habría retenido ~{backlog} frames "
            f"(~{backlog * FRAME_MB:.0f} MB) y la antigüedad seguiría creciendo."
        )


async def main() -> None:
    await run_scenario("Cliente rápido", send_delay=0.0)
    await run_scenario("Cliente lento", send_delay=0.25)
    await run_scenario("Cliente muy lento", send_delay=1.0)


if __name__ == "__main__":
    asyncio.run(main())
