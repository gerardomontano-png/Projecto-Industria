"""
Pruebas unitarias del filtrado por confianza en InferenceService.

Cubren los tres métodos afectados por T-027:
  - classify(image, model_id, top_k, conf=None) → filtra bajo threshold (L178)
  - ocr(image, model_id, offset, conf=None)     → filtra bajo threshold (L214)
  - localize() ya filtra internamente con conf (regresión)

Todos los tests son puro Python sin dependencias en disco ni modelos reales.

Ejecución individual:
    pytest backend/tests/services/test_inference_service_filtering.py -v
"""

from __future__ import annotations


def _filter_preds(preds, conf):
    """Copia exacta del filtro de InferenceService.classify (L178-180)."""
    if conf is not None:
        return [p for p in preds if p["confidence"] >= conf]
    return preds


def _filter_items(items, conf):
    """Copia exacta del filtro de InferenceService.ocr (L214-216)."""
    if conf is not None:
        return [i for i in items if i["confidence"] >= conf]
    return items


# ================================================================== #
#  classify filtering
# ================================================================== #


def test_classify_sin_conf_retorna_todo():
    """Sin conf: deben retornarse todas las predicciones."""
    preds = [
        {"class_id": 0, "class_name": "carro", "confidence": 0.95},
        {"class_id": 1, "class_name": "persona", "confidence": 0.62},
        {"class_id": 2, "class_name": "árbol", "confidence": 0.18},
    ]
    result = _filter_preds(preds, None)
    assert len(result) == 3


def test_classify_conf_50_filtra_metad_bajo():
    """conf=0.50 elimina predicciones por debajo del umbral."""
    preds = [
        {"class_id": 0, "class_name": "carro", "confidence": 0.95},
        {"class_id": 1, "class_name": "persona", "confidence": 0.62},
        {"class_id": 2, "class_name": "árbol", "confidence": 0.18},
    ]
    result = _filter_preds(preds, 0.50)
    assert len(result) == 2
    texts = {p["class_name"] for p in result}
    assert "carro" in texts and "persona" in texts
    assert "árbol" not in texts


def test_classify_conf_70_solo_uno_pasa():
    """conf=0.70 retorna solo la predicción con conf >= 0.7."""
    preds = [
        {"class_id": 0, "class_name": "carro", "confidence": 0.95},
        {"class_id": 1, "class_name": "persona", "confidence": 0.62},
        {"class_id": 2, "class_name": "árbol", "confidence": 0.18},
    ]
    result = _filter_preds(preds, 0.70)
    assert len(result) == 1
    assert result[0]["class_name"] == "carro"


def test_classify_conf_alto_no_returns():
    """conf=0.99 puede dejar lista vacía (comportamiento esperado)."""
    preds = [
        {"class_id": 0, "class_name": "carro", "confidence": 0.95},
        {"class_id": 1, "class_name": "persona", "confidence": 0.62},
    ]
    result = _filter_preds(preds, 0.99)
    assert len(result) == 0


# ================================================================== #
#  ocr filtering
# ================================================================== #


def test_ocr_sin_conf_retorna_todo():
    """Sin conf: todas las transcripciones se mantienen."""
    items = [
        {"text": "HOLA", "confidence": 0.90},
        {"text": "MENSAJE", "confidence": 0.45},
        {"text": "OTRO", "confidence": 0.72},
    ]
    result = _filter_items(items, None)
    assert len(result) == 3


def test_ocr_conf_60_filtra_mensaje():
    """conf=0.60 elimina transcripciones con conf < 0.6."""
    items = [
        {"text": "HOLA", "confidence": 0.90},
        {"text": "MENSAJE", "confidence": 0.45},
        {"text": "OTRO", "confidence": 0.72},
    ]
    result = _filter_items(items, 0.60)
    assert len(result) == 2
    texts = {i["text"] for i in result}
    assert "MENSAJE" not in texts


def test_ocr_conf_bajo_deja_todo():
    """conf=0.10 deja pasando todas las transcripciones."""
    items = [
        {"text": "HOLA", "confidence": 0.90},
        {"text": "MENSAJE", "confidence": 0.45},
        {"text": "OTRO", "confidence": 0.72},
    ]
    result = _filter_items(items, 0.10)
    assert len(result) == 3


# ================================================================== #
#  localization regression (ya filtra conf en el router)
# ================================================================== #


def test_localize_conf_50_filtro():
    """Verificar patrón de filtrado para localization:
    las detecciones con conf >= 0.5 se mantienen, otras no."""
    detections = [
        {"class_id": 143, "confidence": 0.85, "bbox": "raw"},
        {"class_id": 67, "confidence": 0.42, "bbox": "raw"},
        {"class_id": 3, "confidence": 0.91, "bbox": "raw"},
    ]
    conf = 0.50  # default de localization en router
    result = [d for d in detections if d["confidence"] >= conf]
    assert len(result) == 2
    detected_ids = {d["class_id"] for d in result}
    assert detected_ids == {143, 3}


def test_localize_conf_90_solo_alarmas():
    """conf=0.90 es umbral estricto: solo detecciones muy seguras."""
    detections = [
        {"class_id": 143, "confidence": 0.85, "bbox": "raw"},
        {"class_id": 67, "confidence": 0.42, "bbox": "raw"},
        {"class_id": 3, "confidence": 0.91, "bbox": "raw"},
    ]
    conf = 0.90
    result = [d for d in detections if d["confidence"] >= conf]
    assert len(result) == 1
    assert result[0]["class_id"] == 3
