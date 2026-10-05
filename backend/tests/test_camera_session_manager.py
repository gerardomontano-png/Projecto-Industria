"""
Pruebas unitarias del CameraSessionManager.
Ejecutables sin hardware físico: open_camera se mockea en todos los tests.

Ejecutar:
    cd backend
    pytest tests/test_camera_session_manager.py -v
"""

import asyncio
import dataclasses
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.camera_session_manager import (
    CameraSession,
    CameraSessionManager,
    SessionBusyError,
    SessionCameraError,
    SessionMetrics,
    SessionStatus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_capture(opened: bool = True) -> MagicMock:
    """CameraCapture falso que devuelve un frame negro de 640×480."""
    mock = MagicMock()
    mock.is_opened = opened
    mock.read_frame.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
    mock.release.return_value = None
    return mock


def _manager() -> CameraSessionManager:
    """Instancia fresca del gestor para cada test."""
    return CameraSessionManager()


def run(coro):
    """Ejecuta una corrutina sin necesitar pytest-asyncio."""
    return asyncio.run(coro)


# ── acquire ───────────────────────────────────────────────────────────────────

def test_acquire_crea_sesion():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        session = run(manager.acquire("0", "cliente-1"))

    assert session.camera_id == "0"
    assert session.active_client == "cliente-1"
    assert session.status == SessionStatus.STREAMING
    assert manager.session is session


def test_acquire_falla_si_sesion_ocupada():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))

        with pytest.raises(SessionBusyError):
            run(manager.acquire("0", "cliente-2"))


def test_acquire_falla_si_camara_no_disponible():
    with patch("app.services.camera_session_manager.open_camera", return_value=None):
        manager = _manager()
        with pytest.raises(SessionCameraError):
            run(manager.acquire("0", "cliente-1"))


def test_acquire_no_crea_sesion_si_camara_falla():
    with patch("app.services.camera_session_manager.open_camera", return_value=None):
        manager = _manager()
        try:
            run(manager.acquire("0", "cliente-1"))
        except SessionCameraError:
            pass
    assert manager.session is None


# ── release ───────────────────────────────────────────────────────────────────

def test_release_limpia_la_sesion():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))
        run(manager.release("cliente-1"))

    assert manager.session is None
    capture.release.assert_called_once()


def test_release_de_cliente_incorrecto_no_hace_nada():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))
        run(manager.release("intruso"))

    assert manager.session is not None
    capture.release.assert_not_called()


def test_release_sin_sesion_activa_no_lanza():
    manager = _manager()
    run(manager.release("cualquiera"))  # no debe lanzar excepción


def test_segundo_acquire_posible_tras_release():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))
        run(manager.release("cliente-1"))
        session = run(manager.acquire("0", "cliente-2"))

    assert session.active_client == "cliente-2"


# ── update_frame ──────────────────────────────────────────────────────────────

def test_update_frame_valido_incrementa_total():
    session = CameraSession(
        camera_id="0",
        capture=_mock_capture(),
        metrics=SessionMetrics(started_at=time.monotonic()),
    )
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    session.update_frame(frame)
    session.update_frame(frame)

    assert session.metrics.frames_total == 2
    assert session.metrics.frames_dropped == 0
    assert session.last_frame is frame


def test_update_frame_none_incrementa_drops():
    session = CameraSession(
        camera_id="0",
        capture=_mock_capture(),
        metrics=SessionMetrics(started_at=time.monotonic()),
    )

    session.update_frame(None)
    session.update_frame(None)

    assert session.metrics.frames_dropped == 2
    assert session.metrics.frames_total == 0
    assert session.last_frame is None


# ── record_error ──────────────────────────────────────────────────────────────

def test_record_error_cambia_estado_y_almacena_mensaje():
    session = CameraSession(camera_id="0", capture=_mock_capture())

    session.record_error("Cámara desconectada")

    assert session.status == SessionStatus.ERROR
    assert len(session.errors) == 1
    assert session.errors[0].message == "Cámara desconectada"


def test_record_error_multiples_mensajes():
    session = CameraSession(camera_id="0", capture=_mock_capture())

    session.record_error("Error A")
    session.record_error("Error B")

    assert len(session.errors) == 2
    assert session.errors[1].message == "Error B"


# ── get_status ────────────────────────────────────────────────────────────────

def test_get_status_idle_sin_sesion():
    manager = _manager()
    status = manager.get_status()

    assert status["status"] == SessionStatus.IDLE.value
    assert status["active_client"] is None


def test_get_status_refleja_sesion_activa():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))
        status = manager.get_status()

    assert status["status"] == SessionStatus.STREAMING.value
    assert status["active_client"] == "cliente-1"
    assert status["camera_id"] == "0"
    assert "metrics" in status
    assert "errors" in status


def test_get_status_idle_tras_release():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()
        run(manager.acquire("0", "cliente-1"))
        run(manager.release("cliente-1"))
        status = manager.get_status()

    assert status["status"] == SessionStatus.IDLE.value


# ── SessionMetrics ────────────────────────────────────────────────────────────

def test_metrics_fps_se_calcula_tras_dos_frames():
    metrics = SessionMetrics(started_at=time.monotonic())
    metrics.tick_frame()
    time.sleep(0.01)  # garantiza delta > 0 en monotonic
    metrics.tick_frame()

    assert metrics.fps_current > 0.0
    assert metrics.frames_total == 2


def test_metrics_uptime_crece_con_el_tiempo():
    metrics = SessionMetrics(started_at=time.monotonic() - 2.0)
    assert metrics.uptime_seconds >= 2.0


def test_metrics_to_dict_tiene_claves_esperadas():
    metrics = SessionMetrics(started_at=time.monotonic())
    d = metrics.to_dict()

    assert set(d.keys()) == {"frames_total", "frames_dropped", "fps_current", "uptime_seconds"}


# ── Último frame y descarte (M06) ─────────────────────────────────────────────

def test_sesion_no_guarda_copia_propia_del_frame():
    # El frame más reciente vive solo en el slot de capacidad 1.
    campos = {f.name for f in dataclasses.fields(CameraSession)}
    assert "last_frame" not in campos

    session = CameraSession(camera_id="0", capture=_mock_capture())
    frames = [np.full((4, 4, 3), i, dtype=np.uint8) for i in range(3)]
    for frame in frames:
        session.update_frame(frame)

    assert session.last_frame is frames[-1]
    assert session.frames.latest.frame is frames[-1]


def test_update_frame_reemplaza_el_frame_y_cuenta_descartes():
    session = CameraSession(camera_id="0", capture=_mock_capture())
    for i in range(5):
        session.update_frame(np.full((4, 4, 3), i, dtype=np.uint8))
    session.update_frame(None)

    buffer = session.to_dict()["frame_buffer"]
    assert buffer == {
        "capacity": 1,
        "frames_retained": 1,
        "frames_published": 5,
        "frames_consumed": 0,
        "frames_discarded": 4,
    }
    # Las lecturas fallidas no se confunden con descartes.
    assert session.metrics.frames_dropped == 1


def test_get_status_expone_metricas_de_descarte():
    capture = _mock_capture()
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        manager = _manager()

        async def scenario():
            await manager.acquire("0", "cliente-1")
            await asyncio.sleep(0.1)
            status = manager.get_status()
            await manager.release("cliente-1")
            return status

        status = run(scenario())

    assert set(status["frame_buffer"]) == {
        "capacity",
        "frames_retained",
        "frames_published",
        "frames_consumed",
        "frames_discarded",
    }
    assert status["frame_buffer"]["frames_published"] == status["metrics"]["frames_total"]
    assert set(status["delivery"]) == {"frames_sent", "frames_skipped"}
    assert set(status["inference"]) == {"frames_inferred", "frames_skipped"}
