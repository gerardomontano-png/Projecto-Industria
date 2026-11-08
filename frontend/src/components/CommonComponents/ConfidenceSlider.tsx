/**
 * T-027 / HU-08: control deslizante del umbral de confianza.
 * Se usa en el ConfigPanel (Inferencia) y bajo el visor en vivo (Monitor).
 */
import { CONF_MAX, CONF_MIN } from '../../utils/confidenceFilter';

interface ConfidenceSliderProps {
  value: number;
  onChange: (value: number) => void;
  label?: string;
  hint?: string;
  disabled?: boolean;
}

export function ConfidenceSlider({
  value,
  onChange,
  label = 'Umbral de confianza',
  hint,
  disabled = false,
}: ConfidenceSliderProps) {
  return (
    <div className="flex flex-col gap-1.5 w-full">
      <label className="text-[13px] font-semibold text-[#6b7280]">{label}</label>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={CONF_MIN}
          max={CONF_MAX}
          step={0.01}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label={label}
          className="flex-1 accent-[#2f6fe4] disabled:opacity-50"
        />
        <span className="text-[13px] tabular-nums font-medium text-[#1f2430] dark:text-white w-12 text-right">
          {value.toFixed(2)}
        </span>
      </div>
      {hint && <p className="text-[11px] text-[#6b7280]">{hint}</p>}
    </div>
  );
}
