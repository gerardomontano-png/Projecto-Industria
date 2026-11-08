/**
 * T-27 / T-027 / HU-08: stream en vivo con detecciones.
 *
 * - El modelo y el umbral de confianza vienen del ConfigPanel (única fuente).
 * - El umbral se aplica en el cliente sobre cada frame: mover el slider cambia
 *   las cajas al instante sin reabrir el WebSocket. Al backend se le pide
 *   CONF_FLOOR para que bajar el umbral también muestre más detecciones.
 * - IoU e "inferir cada N frames" sí viajan al backend; useInferenceStream
 *   aplica un debounce para no reabrir la cámara en cada paso del slider.
 */
import { useMemo, useState } from 'react';
import { useInferenceStream } from '../../hooks/useInferenceStream';
import { BBoxOverlay } from './BBoxOverlay';
import { colorForClass } from '../../utils/detectionColors';
import { CONF_FLOOR, filterByConfidence } from '../../utils/confidenceFilter';

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}

function SliderField({ label, value, min, max, step, onChange }: SliderProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[12px] text-[#6b7280] w-32 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-[#2f6fe4]"
      />
      <span className="text-[12px] text-[#1f2430] w-8 tabular-nums text-right">{value}</span>
    </div>
  );
}

interface LiveInferenceViewerProps {
  /** Modelo elegido en el ConfigPanel; null usa el default del backend */
  modelId: string | null;
  /** Umbral de confianza del ConfigPanel */
  confThreshold: number;
}

export function LiveInferenceViewer({ modelId, confThreshold }: LiveInferenceViewerProps) {
  // MVP: el backend solo acepta la cámara 0
  const cameraId = '0';
  const [isActive, setIsActive] = useState(false);
  const [iou, setIou] = useState(0.45);
  const [inferEveryNFrames, setInferEveryNFrames] = useState(3);

  return (
    <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280]">
          Stream en vivo con detecciones
        </p>
        <button
          onClick={() => setIsActive((v) => !v)}
          className="text-sm py-1.5 px-3 rounded-lg border border-[#d5d8dc] bg-transparent cursor-pointer hover:bg-[#f7f8fa] transition-colors"
        >
          {isActive ? 'Detener' : 'Conectar'}
        </button>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-[12px] text-[#6b7280]">
          Confianza mín.: <span className="text-[#1f2430] tabular-nums">{confThreshold.toFixed(2)}</span>{' '}
          (se ajusta en Configuración)
        </p>
        <SliderField label="IoU" value={iou} min={0.05} max={0.95} step={0.05} onChange={setIou} />
        <SliderField
          label="Inferir cada N frames"
          value={inferEveryNFrames}
          min={1}
          max={10}
          step={1}
          onChange={setInferEveryNFrames}
        />
      </div>

      {isActive && (
        <LiveInferenceStream
          cameraId={cameraId}
          modelId={modelId}
          confThreshold={confThreshold}
          iou={iou}
          inferEveryNFrames={inferEveryNFrames}
        />
      )}
    </section>
  );
}

interface LiveInferenceStreamProps {
  cameraId: string;
  modelId: string | null;
  confThreshold: number;
  iou: number;
  inferEveryNFrames: number;
}

function LiveInferenceStream({
  cameraId,
  modelId,
  confThreshold,
  iou,
  inferEveryNFrames,
}: LiveInferenceStreamProps) {
  const { frameUrl, detections, isConnected, error } = useInferenceStream(cameraId, {
    modelId: modelId ?? undefined,
    conf: CONF_FLOOR,
    iou,
    inferEveryNFrames,
  });

  const visible = useMemo(
    () => filterByConfidence(detections, confThreshold),
    [detections, confThreshold]
  );

  if (error) {
    return <p className="text-[13px] font-semibold text-[#d64545]">{error}</p>;
  }

  if (!isConnected || !frameUrl) {
    return <p className="text-[13px] text-[#6b7280]">Conectando…</p>;
  }

  return (
    <BBoxOverlay
      imageUrl={frameUrl}
      boxes={visible.map((d) => ({
        bbox: d.bbox,
        label: `${d.className ?? `clase ${d.classId}`} ${Math.round(d.confidence * 100)}%`,
        color: colorForClass(d.classId),
      }))}
    />
  );
}
