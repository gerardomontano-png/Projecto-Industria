from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.schemas.inference import (
    AnomalyResponse,
    ClassificationResponse,
    LocalizationResponse,
    ModelInfo,
    OCRResponse,
)
from app.services.camera_service import encode_ws_message, open_camera
from app.services.image_service import ImageInputError, decode_image, resolve_roi
from app.services.inference_service import InferenceError, inference_service
from app.services.model_registry import ModelRegistryError

router = APIRouter(tags=["inference"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ImageInputError, ModelRegistryError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, InferenceError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/models", response_model=list[ModelInfo])
def list_models() -> list[dict]:
    return inference_service.list_models()


@router.post("/inference/localization", response_model=LocalizationResponse)
async def localization(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    conf: float = Query(default=0.25, ge=0.0, le=1.0),
    iou: float = Query(default=0.45, ge=0.0, le=1.0),
    roi: str | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = resolve_roi(roi, frame)
        selected, detections = inference_service.localize(cropped, model_id, conf, iou, offset)
        height, width = frame.shape[:2]
        return {
            "model_id": selected,
            "image_width": width,
            "image_height": height,
            "roi": roi_value,
            "detections": detections,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/classification", response_model=ClassificationResponse)
async def classification(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=20),
    roi: str | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, _ = resolve_roi(roi, frame)
        selected, predictions = inference_service.classify(cropped, model_id, top_k)
        return {"model_id": selected, "roi": roi_value, "predictions": predictions}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/ocr", response_model=OCRResponse)
async def ocr(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    roi: str | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = resolve_roi(roi, frame)
        selected, results = inference_service.ocr(cropped, model_id, offset)
        return {"model_id": selected, "roi": roi_value, "results": results}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/anomaly", response_model=AnomalyResponse)
async def anomaly(
    image: UploadFile = File(...),
    reference_image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    difference_threshold: int | None = Query(default=None, ge=0, le=255),
    roi: str | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        reference = decode_image(await reference_image.read())
        cropped, roi_value, offset = resolve_roi(roi, frame)
        reference_cropped, _, _ = resolve_roi(roi, reference)
        selected, score, regions = inference_service.anomaly_reference(
            cropped,
            reference_cropped,
            model_id,
            difference_threshold,
            offset,
        )
        return {
            "model_id": selected,
            "roi": roi_value,
            "anomaly_score": score,
            "regions": regions,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.websocket("/ws/inference-stream")
async def inference_stream(
    websocket: WebSocket,
    camera_id: str = Query(default="0"),
    model_id: str | None = Query(default=None),
    conf: float = Query(default=0.25, ge=0.0, le=1.0),
    iou: float = Query(default=0.45, ge=0.0, le=1.0),
    infer_every_n_frames: int = Query(default=3, ge=1, le=120),
    roi: str | None = Query(default=None),
) -> None:
    await websocket.accept()
    settings = get_settings()
    loop = asyncio.get_running_loop()
    camera = await loop.run_in_executor(None, open_camera, camera_id)
    if camera is None:
        await websocket.send_json({"connected": False, "camera_id": camera_id, "description": "No se detectó la cámara."})
        await websocket.close(code=1000)
        return
    await websocket.send_json({"connected": True, "camera_id": camera_id, "description": "Cámara detectada. Iniciando inferencia."})
    frame_count = 0
    last_detections: list[dict] = []
    timestamps: list[float] = []
    try:
        while True:
            frame = await loop.run_in_executor(None, camera.read_frame)
            if frame is None:
                await websocket.send_json({"connected": False, "camera_id": camera_id, "description": "La cámara dejó de enviar frames."})
                await websocket.close(code=1000)
                break
            now = time.monotonic()
            timestamps.append(now)
            if len(timestamps) > 30:
                timestamps.pop(0)
            fps = 0.0 if len(timestamps) < 2 else (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
            if frame_count % infer_every_n_frames == 0:
                try:
                    cropped, _, offset = resolve_roi(roi, frame)
                    _, last_detections = await loop.run_in_executor(
                        None,
                        lambda: inference_service.localize(cropped, model_id, conf, iou, offset),
                    )
                except Exception as exc:
                    await websocket.send_json({"connected": False, "camera_id": camera_id, "description": str(exc)})
                    await websocket.close(code=1011)
                    break
            message = await loop.run_in_executor(
                None,
                lambda: encode_ws_message(frame, last_detections, fps, camera_id, settings.jpeg_quality),
            )
            await websocket.send_bytes(message)
            frame_count += 1
    except WebSocketDisconnect:
        pass
    finally:
        await loop.run_in_executor(None, camera.release)
