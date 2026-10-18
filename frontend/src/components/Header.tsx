import { ButtonCommon } from "./CommonComponents";
import ModeToggle from "./CommonComponents/Button/ModeToggle";
import { Basic, FlechaRegresar} from "./CommonComponents/Icons/IconCommon";

export type AppView = 'monitor' | 'inference';

interface HeaderProps {
  view: AppView;
  onViewChange: (view: AppView) => void;
  isDarkMode: boolean;
  setIsDarkMode: Dispatch<SetStateAction<boolean>>;
}

function Header({ view, onViewChange, isDarkMode, setIsDarkMode }: HeaderProps) {
  return (
    <header className="inter w-full h-[60px] flex items-center justify-between px-5 bg-white dark:bg-[#2E2D2D]">
      <div className="flex items-center">
        {view === 'monitor' ? "" : 
        <ButtonCommon
          variant="secondary"
          size="simple"
          onClick={() => onViewChange('monitor')}
          icon={<FlechaRegresar/>}
        >
          Regresar
        </ButtonCommon>}
      </div>
      <p className="absolute left-1/2 -translate-x-1/2 text-[22px] font-normal text- m-0 text-[#393939] dark:text-white">
        Título de la Herramienta (?)
      </p>

      <div className="flex items-center justify-end gap-2">
        <ModeToggle isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode}/>
        {/* <button
          type="button"
          onClick={() => onViewChange('monitor')}
          className={`h-[34px] px-[14px] rounded-lg border font-['Inter'] text-[13px] font-semibold cursor-pointer ${
            view === 'monitor'
              ? 'bg-[#2f6fe4] border-[#2f6fe4] text-white'
              : 'bg-white border-gray-200 text-gray-900'
          }`}
        >
          Monitoreo en vivo
        </button> */}
        <ButtonCommon
          size="large"
          onClick={() => onViewChange('inference')}
          icon={<Basic/>}
        >
          P. de inferencia
        </ButtonCommon>
        {/* <button
          type="button"
          onClick={() => onViewChange('inference')}
          className={`h-[34px] px-[14px] rounded-lg border font-['Inter'] text-[13px] font-semibold cursor-pointer ${
            view === 'inference'
              ? 'bg-[#2f6fe4] border-[#2f6fe4] text-white'
              : 'bg-white border-gray-200 text-gray-900'
          }`}
        >
          Pruebas de inferencia
        </button> */}
      </div>
    </header>
  );
}

export default Header;
