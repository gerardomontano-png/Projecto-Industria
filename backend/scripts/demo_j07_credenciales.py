"""
Demostración reproducible de la protección de credenciales (J07).

Toma una URL de cámara IP con contraseña y token, y muestra que la base la
rechaza, cómo se registra correctamente, y que el secreto no aparece en
ninguna superficie (respuesta, métrica, log, historial). No necesita cámara.

Ejecutar desde la carpeta backend:
    python scripts/demo_j07_credenciales.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base, create_db_engine  # noqa: E402
from app.db.models import Camera, CredentialLeakError, SourceType  # noqa: E402
from app.services.credential_guard import redact, redact_deep, redact_source  # noqa: E402
from app.services.source_admin import SourceAdminService  # noqa: E402
from app.services.source_schemas import SourceCreate, SourceValidationError  # noqa: E402

SECRETO = "Sup3rClave"
TOKEN = "T0k3nSecreto"
URL = f"rtsp://admin:{SECRETO}@10.0.0.5:554/stream?token={TOKEN}&canal=1"


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def main() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        svc = SourceAdminService(db)

        titulo("La URL de la cámara trae credenciales")
        print(f"  {URL}")
        print(f"  (contraseña: {SECRETO}, token: {TOKEN})")

        titulo("1. La base la rechaza al intentar guardarla")
        try:
            svc.register(SourceCreate(name="IP mala", source_type=SourceType.RTSP, source=URL))
        except SourceValidationError as exc:
            print(f"  ✓ Rechazada [{exc.field}]: {exc}")

        titulo("2. Registro correcto: fuente pública + nombre del secreto")
        r = svc.register(SourceCreate(
            name="Cámara IP", source_type=SourceType.RTSP,
            source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_IP_RTSP"))
        print(f"  Fuente guardada: {r.source}")
        print(f"  Credenciales: en el secreto '{r.credential_ref}', fuera de la base")
        print(f"  has_credentials: {r.has_credentials}")

        titulo("3. El secreto no aparece en ninguna superficie")
        respuesta = r.to_dict()
        metrica = redact_deep({"source": "rtsp://10.0.0.5:554/stream",
                               "last_error": f"timeout al abrir {URL}"})
        log_linea = redact(f"conectando a {URL}")
        fila = db.get(Camera, r.id)
        historial = f"{fila.source} | {fila.credential_ref} | {fila.name}"

        print(f"  Respuesta:  {json.dumps(respuesta)[:70]}…")
        print(f"  Métrica:    {json.dumps(metrica)}")
        print(f"  Log:        {log_linea}")
        print(f"  Historial:  {historial}")

        todo = json.dumps([respuesta, metrica, log_linea, historial])
        filtra = SECRETO in todo or TOKEN in todo
        print(f"\n  ¿Aparece el secreto en alguna superficie? "
              f"{'SÍ ✗' if filtra else 'No ✓'}")
        print(f"  ¿Se conserva lo útil (host 10.0.0.5)? "
              f"{'Sí ✓' if '10.0.0.5' in todo else 'No ✗'}")

        titulo("4. Enmascarado de una fuente con credenciales")
        print(f"  Original:    {URL}")
        print(f"  Enmascarada: {redact_source(URL)}")

    engine.dispose()


if __name__ == "__main__":
    main()
