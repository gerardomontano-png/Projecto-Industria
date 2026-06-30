"""
Router WebSocket para streaming en tiempo real de frames de cámara.

Protocolo binario por mensaje:
  [4 bytes uint32 big-endian = longitud JSON] [JSON metadata UTF-8] [JPEG bytes]

El primer mensaje siempre es JSON de texto con el estado de conexión.
Si no hay cámara disponible se envía {"connected": false, ...} y se cierra
la conexión con código 1000 (cierre normal).
Test del websocket con ws://127.0.0.1:8000/ws/stream?camera_id=0
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.services.camera_service import (
    CameraCapture,
    encode_ws_message,
    open_camera,
)

router = APIRouter(tags=["stream"])

_TARGET_FPS = 30
_FRAME_INTERVAL = 1.0 / _TARGET_FPS


class _FPSTracker:
    """Calcula FPS promedio sobre una ventana deslizante de frames."""

    def __init__(self, window: int = 30) -> None:
        self._times: deque[float] = deque(maxlen=window)

    def tick(self) -> float:
        self._times.append(time.monotonic())
        if len(self._times) < 2:
            return 0.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])


@router.websocket("/ws/stream")
async def stream_camera(
    websocket: WebSocket,
    camera_id: str = Query(
        default="0",
        description="Índice USB (0, 1, …), URL rtsp:// o ruta a archivo de video.",
    ),
) -> None:
    """
    Transmite frames de la cámara procesados en tiempo real.

    **Flujo de mensajes:**
    1. El servidor envía un mensaje **JSON texto** con el estado de conexión.
    2. Si `connected` es `true`, los mensajes siguientes son **binarios**
       (header 4B + JSON + JPEG).
    3. Si la cámara se pierde durante el stream, se envía un JSON de error
       y la conexión se cierra.

    **Códigos de cierre WebSocket:**
    - `1000` — cierre normal (sin cámara o desconexión limpia del cliente).
    - `1011` — error interno del servidor.
    """
    await websocket.accept()  # HTTP 101 Switching Protocols

    settings = get_settings()
    loop = asyncio.get_event_loop()

    camera: Optional[CameraCapture] = await loop.run_in_executor(
        None, open_camera, camera_id
    )

    if camera is None:
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "description": (
                    f"No se detectó ninguna cámara en el dispositivo "
                    f"(fuente: '{camera_id}'). "
                    "Verifique que la cámara esté conectada y no esté "
                    "siendo usada por otra aplicación."
                ),
            }
        )
        await websocket.close(code=1000)
        return

    await websocket.send_json(
        {
            "connected": True,
            "camera_id": camera_id,
            "description": "Cámara detectada. Iniciando transmisión de video.",
        }
    )

    fps_tracker = _FPSTracker()

    try:
        while True:
            t0 = time.monotonic()

            frame = await loop.run_in_executor(None, camera.read_frame)

            if frame is None:
                await websocket.send_json(
                    {
                        "connected": False,
                        "camera_id": camera_id,
                        "description": (
                            "La cámara dejó de enviar frames. "
                            "Es posible que haya sido desconectada."
                        ),
                    }
                )
                await websocket.close(code=1000)
                break

            fps = fps_tracker.tick()

            message = await loop.run_in_executor(
                None,
                lambda: encode_ws_message(
                    frame,
                    [],  # detecciones — el pipeline ML las inyecta en producción
                    fps,
                    camera_id,
                    settings.jpeg_quality,
                ),
            )
            await websocket.send_bytes(message)

            elapsed = time.monotonic() - t0
            sleep_for = max(0.0, _FRAME_INTERVAL - elapsed)
            if sleep_for:
                await asyncio.sleep(sleep_for)

    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close(code=1011)
    finally:
        await loop.run_in_executor(None, camera.release)
