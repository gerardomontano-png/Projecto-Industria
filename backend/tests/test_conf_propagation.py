"""
Pruebas de propagación del parámetro 'conf' en routers de inferencia.

Validan que:
  (a) los endpoints /inference/classification y /inference/ocr aceptan
      el query param opcional `conf` sin devolver 422;
  (b) pasan el valor tal cual al servicio interno (el filtro real
      se valida en test_inference_service_filtering).

Usan httpx.AsyncClient con ASGITransport — nunca levantan un servidor
externo ni tocan cámaras reales.

Ejecución individual:
    pytest backend/tests/test_conf_propagation.py -v
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@contextmanager
def mock_inference_service():
    """Devuelve un MagicMock de InferenceService con métodos defaults."""
    svc_classify = MagicMock(return_value=(
        "efficient_net_b7", [
            {"class_id": 0, "class_name": "carro", "confidence": 0.95},
            {"class_id": 1, "class_name": "persona", "confidence": 0.62},
        ]
    ))
    svc_ocr = MagicMock(return_value=(
        "ocr_default_paddle", [
            {"text": "HOLA", "confidence": 0.90, "polygon": [[0,0],[50,0],[50,30],[0,30]]},
            {"text": "MENSAJE", "confidence": 0.45, "polygon": [[10,10],[60,10],[60,40],[10,40]]},
        ]
    ))
    svc_anomaly = MagicMock(return_value=("anomaly_model", []))

    # localize devuelve detecciones que cumplen Detection schema.
    def _localize(image, model_id=None, conf=None, iou=None, offset=None):
        return ("obj_det_v1", [
            {"class_id": 0, "class_name": "carro", "confidence": 0.85,
             "bbox": {"x1": 10.0, "y1": 10.0, "x2": 90.0, "y2": 90.0}},
            {"class_id": 1, "class_name": "persona", "confidence": 0.42,
             "bbox": {"x1": 50.0, "y1": 20.0, "x2": 80.0, "y2": 80.0}},
        ])

    svc = MagicMock()
    svc.classify = svc_classify
    svc.ocr = svc_ocr
    svc.anomaly_reference = svc_anomaly
    svc.localize = _localize

    with patch("app.api.routers.inference.inference_service", svc):
        yield svc


def _valid_png_bytes():
    """Genera un PNG válido mínimo (1x1 píxel rojo) para tests de UploadFile."""
    import struct, zlib
    
    sig = b'\x89PNG\r\n\x1a\n'
    
    def chunk(ct, d):
        c = zlib.crc32(ct + d) & 0xffffffff
        return struct.pack('>I', len(d)) + ct + d + struct.pack('>I', c)
    
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    raw_scanline = b'\x00\xff\x00\x00'
    
    ihdr = chunk(b'IHDR', ihdr_data)
    idat = chunk(b'IDAT', zlib.compress(raw_scanline))
    iend = chunk(b'IEND', b'')
    
    return sig + ihdr + idat + iend


def _form_payload(model_id: str):
    """Devuelve el payload de archivo para POST multipart."""
    png = _valid_png_bytes()
    return {
        "image": ("test.png", png, "image/png"),
        "model_id": model_id,
    }


# ------------------------------------------------------------------ #
#  /inference/classification -- conf
# ------------------------------------------------------------------ #

class TestClassificationConfParam:
    @pytest.mark.asyncio
    async def test_sin_conf_no_422(self) -> None:
        """Llamar sin `conf` no debe devolver 422."""
        with mock_inference_service():
            app = FastAPI()
            from app.api.routers import inference as inf_router
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("eff_b7_test")
                resp = await client.post("/inference/classification", files=form)
                assert resp.status_code == 200, f"422: {resp.text[:300]}"

    @pytest.mark.asyncio
    async def test_con_conf_aceptado_y_pasado(self) -> None:
        """conf=0.65 via query param debe llegar al servicio como arg [3]."""
        with mock_inference_service() as svc:
            app = FastAPI()
            from app.api.routers import inference as inf_router
            # Patchear el nombre exacto 'inference_service' dentro del módulo router.
            inf_router.inference_service = svc
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("eff_b7_test")
                resp = await client.post("/inference/classification?conf=0.65", files=form)
                assert resp.status_code == 200

                # Verificar que classify fue llamado con conf=0.65.
                svc.classify.assert_called_once()
                args = svc.classify.call_args[0]
                # args: (image_array, model_id, top_k, conf)
                assert len(args) >= 4, f"classify recibió argumentos insuficientes: {args}"
                assert args[3] == pytest.approx(0.65), \
                    f"conf esperado 0.65 en arg[3], recibido {args[3]}"

    @pytest.mark.asyncio
    async def test_conf_fuera_rango_da_error(self) -> None:
        """conf < 0 o conf > 1 debe ser rechazado por Pydantic."""
        with mock_inference_service():
            app = FastAPI()
            from app.api.routers import inference as inf_router
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("eff_b7_test")
                # Negative confidence → rejected.
                resp_low = await client.post("/inference/classification?conf=-0.1", files=form)
                assert resp_low.status_code in (400, 422), \
                    f"conf<0 no rechazado: {resp_low.status_code} {resp_low.text[:200]}"

                # Over 1 → rejected.
                resp_high = await client.post("/inference/classification?conf=1.5", files=form)
                assert resp_high.status_code in (400, 422), \
                    f"conf>1 no rechazado: {resp_high.status_code} {resp_high.text[:200]}"


# ------------------------------------------------------------------ #
#  /inference/ocr -- conf
# ------------------------------------------------------------------ #

class TestOcrConfParam:
    @pytest.mark.asyncio
    async def test_sin_conf_no_422(self) -> None:
        """Llamar OCR sin `conf` no debe devolver 422."""
        with mock_inference_service():
            app = FastAPI()
            from app.api.routers import inference as inf_router
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("paddle_ocr")
                resp = await client.post("/inference/ocr", files=form)
                assert resp.status_code == 200, f"422: {resp.text[:300]}"

    @pytest.mark.asyncio
    async def test_con_conf_aceptado_y_pasado(self) -> None:
        """conf=0.50 en OCR debe llegar al servicio."""
        with mock_inference_service() as svc:
            app = FastAPI()
            from app.api.routers import inference as inf_router
            inf_router.inference_service = svc
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("paddle_ocr")
                resp = await client.post("/inference/ocr?conf=0.50", files=form)
                assert resp.status_code == 200

                svc.ocr.assert_called_once()
                args = svc.ocr.call_args[0]
                # args: (image_array, model_id, offset, conf)
                assert len(args) >= 4, f"ocr recibió argumentos insuficientes: {args}"
                assert args[3] == pytest.approx(0.50), \
                    f"conf esperado 0.50 en arg[3], recibido {args[3]}"

    @pytest.mark.asyncio
    async def test_conf_no_numerico_da_error(self) -> None:
        """conf=abc (no numérico) debe rechazar con 422."""
        with mock_inference_service():
            app = FastAPI()
            from app.api.routers import inference as inf_router
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("paddle_ocr")
                resp = await client.post("/inference/ocr?conf=abc", files=form)
                assert resp.status_code in (400, 422), \
                    f"conf=abc no rechazado: {resp.status_code} {resp.text[:200]}"


# ------------------------------------------------------------------ #
#  /inference/localization -- conf ya soportado (regresión)
# ------------------------------------------------------------------ #

class TestLocalizationConfRegression:
    @pytest.mark.asyncio
    async def test_con_conf_sigue_funcionando(self) -> None:
        """Verificar que localization no se rompió al agregar conf."""
        with mock_inference_service():
            app = FastAPI()
            from app.api.routers import inference as inf_router
            app.include_router(inf_router.router, prefix="")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                form = _form_payload("obj_det_v1")
                resp = await client.post("/inference/localization?conf=0.30", files=form)
                assert resp.status_code == 200, \
                    f"localization con conf falló: {resp.text[:300]}"
