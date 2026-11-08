from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, WebSocket

from app.schemas.inference import (
    AnomalyResponse,
    ClassificationResponse,
    LocalizationResponse,
    ModelInfo,
    OCRResponse,
)
from app.services.camera_session_manager import camera_session_manager
from app.services.image_service import (
    ImageInputError,
    clamp_roi_points,
    decode_image,
    resolve_roi_request,
    roi_points,
)
from app.services.inference_service import InferenceError, inference_service
from app.services.model_registry import ModelRegistryError
from app.services.stream_runner import StreamTaskError, serve_camera_stream

router = APIRouter(tags=["inference"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ImageInputError, ModelRegistryError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, InferenceError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _roi_query(
    frame,
    roi: str | None,
    x1: int | None,
    y1: int | None,
    x2: int | None,
    y2: int | None,
):
    return resolve_roi_request(frame, roi, x1, y1, x2, y2)


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
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, detections = inference_service.localize(cropped, model_id, conf, iou, offset)
        height, width = frame.shape[:2]
        return {
            "model_id": selected,
            "image_width": width,
            "image_height": height,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "detections": detections,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/classification", response_model=ClassificationResponse)
async def classification(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    conf: float | None = Query(default=None, ge=0.0, le=1.0),
    top_k: int = Query(default=5, ge=1, le=20),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, _ = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, predictions = inference_service.classify(cropped, model_id, top_k, conf)
        return {
            "model_id": selected,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "predictions": predictions,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/ocr", response_model=OCRResponse)
async def ocr(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    conf: float | None = Query(default=None, ge=0.0, le=1.0),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, results = inference_service.ocr(cropped, model_id, offset, conf)
        return {
            "model_id": selected,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "results": results,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/anomaly", response_model=AnomalyResponse)
async def anomaly(
    image: UploadFile = File(...),
    reference_image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    difference_threshold: int | None = Query(default=None, ge=0, le=255),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        reference = decode_image(await reference_image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        reference_cropped, _, _ = _roi_query(reference, roi, x1, y1, x2, y2)
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
            "roi_points": roi_points(roi_value),
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
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> None:
    # Parámetros ajustables en vivo con {"type": "config", "conf": .., "iou": ..}
    # sin reconectar: la cámara no se reabre por mover un slider (HU-08).
    live = {"conf": conf, "iou": iou}

    def on_message(message: dict) -> None:
        if message.get("type") != "config":
            raise ValueError(f"tipo de mensaje desconocido: {message.get('type')!r}")
        updates = {}
        for key in ("conf", "iou"):
            if key not in message:
                continue
            value = message[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} debe ser numérico")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{key} debe estar entre 0 y 1")
            updates[key] = float(value)
        live.update(updates)

    def infer(frame) -> list[dict]:
        # La captura entrega el frame completo; el ROI se aplica solo aquí. En
        # vivo el ROI se recorta al frame: el cliente no siempre conoce la
        # resolución real de la cámara y unos píxeles de más no deben cortar
        # el video.
        try:
            cropped, _, offset = _roi_query(frame, roi, *clamp_roi_points(frame, x1, y1, x2, y2))
        except ImageInputError as exc:
            raise StreamTaskError("INVALID_ROI", str(exc)) from exc
        try:
            _, detections = inference_service.localize(
                cropped, model_id, live["conf"], live["iou"], offset
            )
        except (InferenceError, ModelRegistryError) as exc:
            raise StreamTaskError("INFERENCE_ERROR", str(exc)) from exc
        return detections

    await serve_camera_stream(
        websocket,
        camera_session_manager,
        camera_id,
        "Cámara detectada. Iniciando inferencia.",
        infer=infer,
        infer_every_n_frames=infer_every_n_frames,
        on_message=on_message,
    )
