import type { Camera, Job } from '../../types/index';
import type { ApiModel } from '../../types';
import { useCameraStream } from '../../hooks/useCameraStream';
import { useMemo } from 'react';
import { useROIStore } from '../../store/roiStore';
import { useInferenceSettingsStore } from '../../store/inferenceSettingsStore';
import { ConfidenceSlider } from '../CommonComponents';
import { ButtonCommon } from '../CommonComponents';
import { ROICanvas } from './ROICanvas';
import { TopBar } from '../Toolbar';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';
import { MenuOptions } from './MenuOptions';
import { DetectionCanvas } from './DetectionCanvas';

interface LiveViewerProps {
  camera: Camera;
  cameraId: string;
  job: Job;
  onToggleInspection: () => void;
  // Props nuevas para el TopBar
  models: ApiModel[];
  isLoadingModels: boolean;
  effectiveModelId: string;
  onModelChange: (modelId: string) => void;
  selectedCameraId: string;
  apiCameras: { id: string }[];
  onCameraChange: (cameraId: string) => void;
  naturalWidth?: number;
  naturalHeight?: number;
  activeItem: string | null;
}

const SELECT_CLASS =
  'shrink-0 h-8 px-2 rounded-lg border border-[#e2e5ea] bg-white text-[13px] text-[#393939] cursor-pointer focus:outline-[2px] focus:outline-[#2f6fe4] focus:outline-offset-1 disabled:opacity-50 disabled:cursor-not-allowed';

const TASK_LABELS: Record<string, string> = {
  localization: 'Detección YOLO',
  classification: 'Clasificación',
  ocr: 'OCR',
  anomaly: 'Anomalías',
};

export function LiveViewer({
  camera,
  cameraId,
  job,
  onToggleInspection,
  models,
  isLoadingModels,
  effectiveModelId,
  onModelChange,
  selectedCameraId,
  apiCameras,
  onCameraChange,
  naturalWidth,
  naturalHeight,
  activeItem,
}: LiveViewerProps) {
  const isInspectionRunning = job.status === 'running';
  const rois = useROIStore((s) => s.rois);
  // HU-08: mismo umbral que el ConfigPanel de la vista Inferencia
  const confThreshold = useInferenceSettingsStore((s) => s.confThreshold);
  const setConfThreshold = useInferenceSettingsStore((s) => s.setConfThreshold);

  // ROI normalizado (0–1): useCameraStream lo pasa a píxeles con la resolución
  // REAL del frame. Antes se usaba camera.resolution (respaldo fijo 1920x1080):
  // con una webcam de 640x480 el ROI quedaba fuera de la imagen, la inferencia
  // fallaba y el WebSocket se cerraba y reabría en bucle.
  const streamRoi = useMemo(() => {
    const activeRoi = rois.find((roi) => roi.cameraId === cameraId && roi.isEnabled);
    if (!activeRoi) return null;
    const { x, y, width, height } = activeRoi;
    return { x, y, width, height };
  }, [rois, cameraId]);

  // El stream de inferencia en vivo solo devuelve detecciones de modelos de localización
  const jobModel = models.find((m) => m.id === job.modelId);
  const isDetectionModel = jobModel?.task === 'localization';
  const isLiveInference = isInspectionRunning && isDetectionModel;

  const streamOptions = useMemo(
    () =>
      isLiveInference
        ? {
            mode: 'inference' as const,
            modelId: job.modelId,
            roiNormalized: streamRoi,
            conf: confThreshold,
          }
        : {
            mode: 'stream' as const,
          },
    [isLiveInference, job.modelId, streamRoi, confThreshold]
  );

  const { canvasRef, detectionCanvasRef, isConnected, error, displaySize } = useCameraStream(
    cameraId,
    streamOptions
  );

  return (
    <div className="flex flex-col items-center gap-3 min-h-0 mt-10">

      {/* TopBar ahora vive aquí */}
      <TopBar
        status={camera.status}
        cameraName={camera.name}
        job={job}
        onToggleInspection={onToggleInspection}
      />

      {/* Canvas container — igual que antes */}
      <div className="relative w-full aspect-video bg-[#ffffff] dark:bg-[#6D6D6D] rounded-[10px] overflow-hidden flex items-center justify-center">
        {error && <div className="text-sm font-semibold text-[#d64545]">{error}</div>}
        {!isConnected && !error && (
          <div className="text-[13px] text-[#6b7280]">Conectando stream…</div>
        )}
        <canvas
          ref={canvasRef}
          aria-label={`Stream de ${camera.name}`}
          className="absolute inset-0 w-full h-full"
          style={{ display: 'block' }}
        />
        <DetectionCanvas ref={detectionCanvasRef} />
        {displaySize.width > 0 && (
          <ROICanvas width={displaySize.width} height={displaySize.height} cameraId={cameraId} />
        )}
        {isInspectionRunning && (
          <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-[#d64545] text-white text-[11px] font-bold uppercase tracking-widest rounded-full px-3 py-1">
            <span className="block w-2 h-2 rounded-full bg-white opacity-90 animate-pulse" />
            Inspección activa
          </div>
        )}
      </div>
      {/* HU-08: sensibilidad de detección, se aplica en vivo sin reconectar */}
      <div className="w-full max-w-md self-start">
        <ConfidenceSlider
          value={confThreshold}
          onChange={setConfThreshold}
          label="Sensibilidad (confianza mínima)"
          hint={
            isLiveInference
              ? 'Se aplica en vivo a las detecciones.'
              : 'Se aplicará al iniciar la inspección con un modelo de detección.'
          }
        />
      </div>
      {activeItem &&(
        <MenuOptions
          cameraId={cameraId}
          naturalWidth={naturalWidth}
          naturalHeight={naturalHeight}
          menuOptionSelected={activeItem}
        />
      )}
    </div>
  );
}