import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  ChevronsLeft,
} from 'lucide-react';
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
}

export function LeftSideBar({
  collapsed = false,
  onCollapse,
}: LeftSidebarProps) {
  const [openSections, setOpenSections] = useState<string[]>(['Imagen']);
  const [activeItem, setActiveItem] = useState<string | null>(null);

  const toggle = (label: string) => {
    setOpenSections((prev) =>
      prev.includes(label) ? prev.filter((s) => s !== label) : [...prev, label]
    );
  };

  return (
    <aside className="flex flex-col bg-white dark:bg-[#2E2D2D] rounded-2xl w-52 border-[#e2e5ea] shrink-0 overflow-y-auto h-screen">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3.5">
        {!collapsed && (
          <span className="text-[18px] font-semibold text-[#393939] dark:text-white">Herramientas</span>
        )}
        <button
          type="button"
          onClick={onCollapse}
          className="text-[#6b7280] hover:text-[#393939] dark:text-white dark:hover:text-[#d9d9d9] transition-colors cursor-pointer ml-auto"
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
            <div key={label} className="mx-1 mb-2 bg-[#F7F7F7] dark:bg-[#404040] rounded-xl">
              {/* Section header */}
              <button
                type="button"
                onClick={() => hasChildren && toggle(label)}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] font-semibold text-[#1f2430] dark:text-white transition-colors cursor-pointer"
              >
                {hasChildren ? (
                  isOpen ? <ChevronDown size={14} className="text-[#6b7280] dark:text-white shrink-0" />
                           : <ChevronRight size={14} className="text-[#6b7280] dark:text-white shrink-0" />
                ) : (
                  <span className="w-3.5 shrink-0" />
                )}
                <Icon size={15} className="shrink-0 text-[#6b7280] dark:text-white" />
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
                          // aqui mandar llamar el menu de opciones [onlcick] (MenuOptions.tsx) que se muestre el correspondiente, hay que poner que 
                          // mientras no se este activo alguno entonces no se podrá acceder a la funcionalidad, por ejemplo, los ROI, si no se tiene
                          // seleccionada la funcionalidad en la barra entonces no se deberían poder cambiar los roi, solo la iluminación
                          isActive
                            ? 'text-[#393939] dark:text-white font-semibold'
                            : 'border-transparent text-[#6b7280] dark:text-white hover:text-[#1f2430] dark:hover:text-[#D9D9D9]'
                        }`}
                      >
                        {child}
                      </button>
                    </div>
                  );
                })} 
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}