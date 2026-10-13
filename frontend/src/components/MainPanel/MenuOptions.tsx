import type { Camera, CameraConnectionStatus } from "../../types";
import { ROICoordinatesPanel } from "./ROICoordinatesPanel";

interface MenuOptions{
    cameraId: string;
    naturalWidth?: number;
    naturalHeight?: number;
}

export function MenuOptions({cameraId, naturalWidth,
  naturalHeight,} : MenuOptions){
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
