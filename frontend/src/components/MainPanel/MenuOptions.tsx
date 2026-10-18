import type { Camera, CameraConnectionStatus } from "../../types";
import { ROICoordinatesPanel } from "./ROICoordinatesPanel";

interface MenuOptions{
    cameraId: string;
    naturalWidth?: number;
    naturalHeight?: number;
    menuOptionSelected: string;
}

export function MenuOptions({cameraId, naturalWidth, naturalHeight, menuOptionSelected} : MenuOptions){
    switch(menuOptionSelected){
        case "ROI":
        return(
            <div className="w-5/6">    
                <ROICoordinatesPanel
                cameraId={cameraId}
                naturalWidth={naturalWidth}
                naturalHeight={naturalHeight}
                />
            </div>
        )
        case "Clasificación":
            return(
            <div className="w-5/6">    
                <ROICoordinatesPanel
                cameraId={cameraId}
                naturalWidth={naturalWidth}
                naturalHeight={naturalHeight}
                />
            </div>
        )
    }
}
