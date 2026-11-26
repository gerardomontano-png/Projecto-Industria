"""
Demostración reproducible del contrato de ROI absoluto (BACKEND).

Valida una ROI correcta, muestra el rechazo de cada caso inválido, el modo
clamp, y que un ROI inválido en el stream avisa sin cerrar la conexión.
No necesita cámara ni modelo.

Ejecutar desde la carpeta backend:
    python scripts/demo_roi.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from app.services.roi_contract import validate_roi, parse_roi_request, ROIValidationError
from app.services.roi_resolver import resolve_roi_absolute

FW, FH = 640, 480

def titulo(t): print(f"\n{'─'*70}\n{t}\n{'─'*70}")

def intento(desc, fn):
    try:
        fn(); print(f"  ✗ {desc}: se aceptó (no debería)")
    except ROIValidationError as e:
        print(f"  ✓ {desc} [{e.code}]")

def main():
    titulo("1. ROI válida sobre un frame de 640x480")
    r = validate_roi(10, 20, 110, 170, frame_width=FW, frame_height=FH)
    print(f"  {r.to_dict()}  → offset {r.offset}, área {r.area} px, xywh {r.as_xywh()}")

    titulo("2. Ausencia de ROI = frame completo")
    print(f"  parse_roi_request(None,None,None,None) = {parse_roi_request(None,None,None,None)}")
    img = np.zeros((FH, FW, 3), dtype=np.uint8)
    cropped, roi, off = resolve_roi_absolute(img)
    print(f"  resolve sin ROI → imagen {cropped.shape[1]}x{cropped.shape[0]}, roi={roi}")

    titulo("3. Casos inválidos (rechazo controlado)")
    intento("no finito (NaN)", lambda: validate_roi(float('nan'), 0, 10, 10))
    intento("no numérico (texto)", lambda: validate_roi("abc", 0, 10, 10))
    intento("invertida (x2 < x1)", lambda: validate_roi(110, 20, 10, 170))
    intento("área nula (x1 == x2)", lambda: validate_roi(10, 20, 10, 170))
    intento("fuera del frame", lambda: validate_roi(0, 0, 9999, 100, frame_width=FW, frame_height=FH))
    intento("incompleta", lambda: parse_roi_request(10, 20, None, 170))

    titulo("4. Modo clamp: limitar al borde en vez de rechazar")
    rc = validate_roi(-50, -50, FW+100, FH+100, frame_width=FW, frame_height=FH, clamp=True)
    print(f"  ROI (-50,-50,{FW+100},{FH+100}) con clamp → {rc.to_dict()}")

    titulo("5. En el stream: ROI inválida avisa sin cerrar la conexión")
    import asyncio, contextlib
    from app.services.frame_slot import FrameSlot
    from app.services.stream_runner import _inference_loop, _Detections
    class FakeWS:
        def __init__(self): self.mensajes=[]; self.cerrado=False
        async def send_json(self, d): self.mensajes.append(d)
        async def close(self, code=1000): self.cerrado=True
    def infer_malo(frame): raise ROIValidationError("ROI_NOT_ORDERED", "x1 >= x2")
    async def esc():
        ws=FakeWS(); slot=FrameSlot(); dets=_Detections()
        t=asyncio.create_task(_inference_loop(ws, slot, infer_malo, 1, dets))
        for i in range(3):
            slot.publish(np.zeros((8,8,3),dtype=np.uint8), float(i)); await asyncio.sleep(0.02)
        viva=not t.done(); t.cancel()
        with contextlib.suppress(asyncio.CancelledError): await t
        return ws, viva
    ws, viva = asyncio.run(esc())
    print(f"  Frames con ROI inválida procesados; bucle vivo: {viva}, socket cerrado: {ws.cerrado}")
    print(f"  Avisos enviados: {len(ws.mensajes)} → {ws.mensajes[0]['error'] if ws.mensajes else '—'}")
    print(f"  (el video sigue; sin cerrar la conexión ✓)")

if __name__ == "__main__":
    main()
