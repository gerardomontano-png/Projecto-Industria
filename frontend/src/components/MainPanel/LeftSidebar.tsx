import { useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Image,
  Camera,
  Cpu,
  ScanSearch,
  BarChart2,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  ChevronsLeft,
} from 'lucide-react';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';
import { Ayuda, Entrenamiento, Imagen, Inspeccion, Resultados, Submenu } from '../CommonComponents/Icons/IconCommon'

interface NavItem {
  label: string;
  icon: React.ComponentType;
  children: string[];
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Imagen', icon: Imagen, children: ['ROI'] },
  // { label: 'Comunicación cámara', icon: Camera, children: ['Diagnóstico', 'Trigger'] },
  { label: 'Entrenamiento', icon: Entrenamiento, children: ['Detección', 'Clasificación', 'Segmentación', 'OCR'] },
  { label: 'Inspección', icon: Inspeccion, children: ['Medición', 'non'] },
  { label: 'Resultados', icon: Resultados, children: [] },
  { label: 'Ayuda', icon: Ayuda, children: ['Manual de usuario', 'Contacto'] },
];

interface LeftSidebarProps {
  collapsed?: boolean;
  onCollapse?: () => void;
  cameraId: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

export function LeftSideBar({
  collapsed = false,
  onCollapse,
  cameraId,
  naturalWidth,
  naturalHeight,
}: LeftSidebarProps) {
  const [openSections, setOpenSections] = useState<string[]>(['Imagen']);
  const [activeItem, setActiveItem] = useState<string | null>(null);

  const toggle = (label: string) => {
    setOpenSections((prev) =>
      prev.includes(label) ? prev.filter((s) => s !== label) : [...prev, label]
    );
  };

  return (
    <aside className="flex flex-col bg-white rounded-2xl border-[#e2e5ea] w-52 shrink-0 overflow-y-auto max-h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3.5 border-b border-[#e2e5ea]">
        {!collapsed && (
          <span className="text-[15px] font-semibold text-[#393939]">Herramientas</span>
        )}
        <button
          type="button"
          onClick={onCollapse}
          className="text-[#6b7280] hover:text-[#393939] transition-colors cursor-pointer ml-auto"
        >
          <ChevronsLeft size={18} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex flex-col py-2 overflow-y-auto flex-1">
        {NAV_ITEMS.map(({ label, icon: Icon, children }) => {
          const isOpen = openSections.includes(label);
          const hasChildren = children.length > 0;

          return (
            <div key={label} className="mx-1 mb-2 bg-[#F7F7F7] rounded-xl">
              {/* Section header */}
              <button
                type="button"
                onClick={() => hasChildren && toggle(label)}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] font-semibold text-[#1f2430] transition-colors cursor-pointer"
              >
                {hasChildren ? (
                  isOpen ? <ChevronDown size={14} className="text-[#6b7280] shrink-0" />
                           : <ChevronRight size={14} className="text-[#6b7280] shrink-0" />
                ) : (
                  <span className="w-3.5 shrink-0" />
                )}
                <Icon size={15} className="shrink-0 text-[#6b7280]" />
                {label}
              </button>

              {/* Children */}
              {hasChildren && isOpen && (
              <div className="relative">
                {children.map((child, index) => {
                  const isActive = activeItem === child;
                  const isLast = index === children.length - 1;

                  return (
                    <div key={child} className="relative flex items-center py-1.5 mx-5.5">
                      {/* Línea vertical — no se dibuja debajo del último item */}
                      {!isLast && (
                        <div className="absolute left-[1.35rem] top-0 bottom-0 w-px bg-[#DCDCDC] h-12" />
                      )}
                      <div className="absolute left-[1.35rem] top-0 bottom-1/2 w-px bg-[#DCDCDC] h-px">
                      <Submenu></Submenu>
                       </div>
                      {isLast && (
                      <div className="absolute left-[1.35rem] top-0 bottom-0 w-px bg-[#DCDCDC] h-px" >
                        <Submenu></Submenu>
                      </div>
                      )}

                      {/* Rama horizontal */}
                      <div className="absolute left-[1.35rem]  w-3 h-px bg-transparent"> 
                      </div>

                      <button
                        type="button"
                        onClick={() => setActiveItem(child)}
                        className={`ml-10 w-full text-left px-2 text-[13px] transition-colors cursor-pointer ${
                          isActive
                            ? 'text-[#393939] font-semibold'
                            : 'border-transparent text-[#6b7280] hover:text-[#1f2430]'
                        }`}
                      >
                        {child}
                      </button>
                    </div>
                  );
                })} 

                  {label === 'Imagen' && activeItem === 'ROI' && (
                    <div className="px-3 pb-2">
                      <ROICoordinatesPanel
                        cameraId={cameraId}
                        naturalWidth={naturalWidth}
                        naturalHeight={naturalHeight}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}