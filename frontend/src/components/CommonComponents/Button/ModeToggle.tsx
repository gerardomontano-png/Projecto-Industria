import type { Dispatch, SetStateAction } from "react";
import { Moon, Sun } from "lucide-react";

interface ModeToggleProps {
    isDarkMode: boolean;
    setIsDarkMode: Dispatch<SetStateAction<boolean>>;
}

const ModeToggle = ({isDarkMode, setIsDarkMode}: ModeToggleProps) => {
    return (
        <label className = "top-2 right-0">
            <input className="h-0 w-0" type="checkbox" checked={isDarkMode} onChange={() => setIsDarkMode((prev) => !prev)}>
            </input>
            <span className="relative flex w-16 h-8 items-center justify-between rounded-2xl border border-[#DCDCDC] p-1 content-evenly">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${!isDarkMode ? "bg-[#F7F7F7]" : ""}`}>
                    <Sun className={`w-4 h-4 ${isDarkMode ? "text-[#BFBFBF]" : ""}`} />
                </span>
                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${isDarkMode ? "bg-[#F7F7F7]" : ""}`}>
                    <Moon className={`w-4 h-4 ${!isDarkMode ? "text-[#BFBFBF]" : ""}`} />
                </span>
            </span>
        </label>
    )
};

export default ModeToggle;