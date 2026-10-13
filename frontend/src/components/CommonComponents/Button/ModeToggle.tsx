import { Moon, Sun } from "lucide-react";


const ModeToggle = ({isDarkMode, setIsDarkMode}) => {
    return (
        <label className="flex h-[34px] items-center cursor-pointer">
            <input className="h-0 w-0" type="checkbox" checked={isDarkMode} onChange={() => setIsDarkMode((prev) => !prev)}>
            </input>
            <span className=" flex w-16 h-8 items-center justify-between rounded-2xl border border-[#DCDCDC] dark:bg-[#404040] dark:border-[#404040] p-1 content-evenly">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${!isDarkMode ? "bg-[#F7F7F7]" : ""}`}>
                    <Sun className={`w-4 h-4 ${isDarkMode ? "text-[#BFBFBF]" : ""}`} />
                </span>
                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${isDarkMode ? "bg-[#F7F7F7] dark:bg-[#6D6D6D]" : ""}`}>
                    <Moon className={`w-4 h-4 ${!isDarkMode ? "text-[#BFBFBF]" : "dark:text-white"}`} />
                </span>
            </span>
        </label>
    )
};

export default ModeToggle;