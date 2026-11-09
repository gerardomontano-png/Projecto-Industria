import { useState } from 'react';
import { Pencil } from 'lucide-react';
import { ColorPickerPopup } from '../Toolbar/ColorPickerPopup';

interface AccuracyLevel {
  label: string;
  color: string;
  threshold: number;
  operator: '>=' | '<=';
}

const DEFAULT_LEVELS: AccuracyLevel[] = [
  { label: 'Alta',  color: '#B4D678', threshold: 70, operator: '≥' },
  { label: 'Media', color: '#A3C2DF', threshold: 50, operator: '≥' },
  { label: 'Baja',  color: '#BD7066', threshold: 30, operator: '≤' },
];

export function AccuracyColorPanel() {
  const [levels, setLevels] = useState<AccuracyLevel[]>(DEFAULT_LEVELS);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  const updateColor = (index: number, color: string) => {
    setLevels((prev) => prev.map((l, i) => (i === index ? { ...l, color } : l)));
    setEditingIndex(null);
  };

  const updateThreshold = (index: number, value: number) => {
    setLevels((prev) => prev.map((l, i) => (i === index ? { ...l, threshold: value } : l)));
  };

  return (
    <div className="relative bg-white rounded-2xl border border-[#e2e5ea] p-4 w-full h-40 flex flex-col items-center">
      <p className="text-[15px] font-semibold text-[#1f2430] text-center mb-4">Accuracy</p>
      <div className='flex flex-col w-7/12 border rounded-2xl p-1 border-[#F1F1F1]'>
        <div className="grid grid-cols-[1fr_auto_auto] gap-4 px-2 h-4.5">
          <span />
          <span className="text-[10px] text-[#BFBFBF] w-28 text-center font-semibold">Color</span>
          <span className="text-[10px] text-[#BFBFBF] w-24 text-center font-semibold">Puntaje</span>
        </div>

        <div className="flex flex-col ">
          {levels.map((level, index) => (
            <div key={level.label} className="relative grid grid-cols-[1fr_auto_auto] items-center gap-1 py-0.5 px-2">
              <span className="text-[13px] text-[#1f2430]">{level.label}</span>

              <div className="flex items-center gap-2 w-28 justify-center">
                <div
                  className="w-10 h-5 rounded-lg border border-[#e2e5ea]"
                  style={{ backgroundColor: level.color }}
                />

                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setEditingIndex(editingIndex === index ? null : index)}
                    className="w-5 h-5 flex items-center justify-center rounded-lg bg-[#f5f6f8] hover:bg-[#eceef1] cursor-pointer transition-colors"
                  >
                    <Pencil size={13} className="text-[#6b7280]" />
                  </button>

                  {editingIndex === index && (
                    <div className="absolute bottom-full left-0 z-50">
                      <ColorPickerPopup
                        currentColor={level.color}
                        onSave={(color) => updateColor(index, color)}
                        onClose={() => setEditingIndex(null)}
                      />
                    </div>
                  )}
                </div>
              </div>

              
              <div className="flex items-center gap-1.5 w-24 justify-center">
                <span className="text-[10.5px] text-[#6b7280] font-semibold">{level.operator}</span>
                <input
                  type="number"
                  value={level.threshold}
                  onChange={(e) => updateThreshold(index, Number(e.target.value))}
                  className="w-14 h-5 px-2 text-[13px] text-center rounded-lg bg-[#f5f6f8] border border-transparent focus:border-[#2f6fe4] focus:outline-none"
                />
              </div>

            </div>
          ))}
        </div>
      </div>
    </div>
  );
}