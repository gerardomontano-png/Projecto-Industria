import type { ReactNode } from 'react';
import { ConnectionStatusBadge } from './ConnectionStatusBadge';
import type { CameraConnectionStatus } from '../../types/indexTypes';
import { ButtonCommon } from '../CommonComponents/Button/ButtonCommon';
import { CameraSparklesIcon } from '../CommonComponents/Icons/IconCommon.tsx';
import type { Camera } from '../../types/index';

interface TopBarProps {
  title: string;
  onSettings?: () => void;
  status?: CameraConnectionStatus;
  cameraName?: string;
  rightSlot?: ReactNode;
  camera: Camera;
}

/**
 * Sustituye el header inline de MainPanel para que el indicador
 * de estado sea un componente propio y reutilizable.
 */
export function TopBar({ status, cameraName }: TopBarProps) {
  const resolvedStatus = status ?? 'disconnected';
  const resolvedCameraName = cameraName ?? '';

  return (
    <header
      className="w-full flex justify-between shrink-0 items-center gap-4 bg-transparent" role="banner">
      <ConnectionStatusBadge status={resolvedStatus} cameraName={resolvedCameraName}/>
      <ButtonCommon
          size="large"
          // onClick={() => }
          icon={<CameraSparklesIcon/>}
        >
          Realizar trigger
        </ButtonCommon>
    </header>
  );
}
