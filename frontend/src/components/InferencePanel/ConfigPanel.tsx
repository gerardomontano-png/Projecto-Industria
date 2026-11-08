/**
 * T-026 + T-027: Panel de configuración del motor de inferencia.
 *
 * Contiene:
 *   - Selector desplegable de modelo (habilitado solo si está disponible y cargado).
 *     Las columnas muestran id, backend, status (disponible/cargado) y un indicador visual.
 *   - Control deslizante de umbral de confianza (0 – 1, paso 0.01).
 *     El valor se transmite tanto a los endpoints REST de infería como al stream WebSocket
 *     para filtrar detecciones en tiempo real.
 */
import type { ApiModel, ModelTask } from '../../types';
import { useModels } from '../../hooks/useModels';

interface ConfigPanelProps {
  /** Tarea actual: determina cuál sublist de modelos se muestra */
  activeTask: ModelTask;
  /** Modelo actualmente seleccionado */
  selectedModelId: string | null;
  onChangeModel: (modelId: string) => void;
  /** Umbral mínimo de confianza para filtrar detecciones en el stream en vivo */
  confThreshold: number;
  onConfChange: (value: number) => void;
}

/** Estado visual del modelo con la lógica consolidada de disponibilidad */
interface ModelState {
  id: string;
  backend: string;
  available: boolean;
  loaded: boolean;
  enabled: boolean;
  disabledReason: string;
}

/** Determina si un modelo puede usarse y por qué se bloquearía */
function modelState(model: ApiModel): ModelState {
  const available = model.available && model.enabled;
  const reason: string[] = [];
  if (!model.enabled) reason.push('deshabilitado');
  if (!model.available) reason.push(`backend "${model.backend}" no disponible`);
  return {
    id: model.id,
    backend: model.backend,
    available,
    loaded: model.loaded,
    enabled: model.enabled,
    disabledReason: reason.join(' · '),
  };
}

export function ConfigPanel({
  activeTask,
  selectedModelId,
  onChangeModel,
  confThreshold,
  onConfChange,
}: ConfigPanelProps) {
  const { models, isLoading } = useModels();

  // Filtrar modelos de la tarea activa
  const taskModels = models.filter((m) => m.task === activeTask);

  return (
    <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-4">
      {/* ── Título ── */}
      <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280] mb-0">
        Configuración
      </p>

      {/* ── Selector de modelo (T-026) ── */}
      <div className="flex flex-col gap-2">
        <label className="text-[13px] font-semibold text-[#6b7280]">Modelo</label>
        {isLoading ? (
          <p className="text-[13px] text-[#6b7280]">Cargando modelos…</p>
        ) : taskModels.length === 0 ? (
          <p className="text-[13px] text-[#6b7280]">No hay modelos para esta tarea.</p>
        ) : (
          <select
            value={selectedModelId ?? ''}
            onChange={(e) => {
              if (e.target.value) onChangeModel(e.target.value);
            }}
            className="h-9 px-3 rounded-lg border border-[#e2e5ea] text-[13px] focus:border-[#2f6fe4] focus:ring-1 focus:ring-[#2f6fe4]/30 outline-none"
          >
            {taskModels.map((model) => {
              const info = modelState(model);
              return (
                <option
                  key={model.id}
                  value={model.id}
                  disabled={!info.available}
                  title={info.disabledReason || undefined}
                >
                  {model.id + (!info.available ? ` — ${info.disabledReason}` : '')}
                </option>
              );
            })}
          </select>
        )}

        {/* Indicador de disponibilidad del modelo seleccionado */}
        {taskModels.length > 0 && (
          <div className="flex items-center gap-2 text-[11px]">
            {(() => {
              const current = taskModels.find((m) => m.id === selectedModelId);
              if (!current) return null;
              const info = modelState(current);
              return (
                <>
                  <span
                    className={`shrink-0 w-2 h-2 rounded-full ${info.loaded ? 'bg-green-500' : info.available ? 'bg-amber-400' : 'bg-red-400'}`}
                  />
                  <span className="text-[#6b7280]">
                    {info.available
                      ? `Backend listo` + (info.loaded ? ' · carga en memoria' : '')
                      : info.disabledReason}
                  </span>
                </>
              );
            })()}
          </div>
        )}
      </div>

      {/* ── Umbral de confianza (T-027) ── */}
      <div className="flex flex-col gap-1.5">
        <label className="text-[13px] font-semibold text-[#6b7280]">
          Umbral de confianza
        </label>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0.05}
            max={0.95}
            step={0.01}
            value={confThreshold}
            onChange={(e) => onConfChange(Number(e.target.value))}
            className="flex-1 accent-[#2f6fe4]"
          />
          <span className="text-[13px] tabular-nums font-medium text-[#1f2430] w-12 text-right">
            {confThreshold.toFixed(2)}
          </span>
        </div>
      </div>
    </section>
  );
}
