import { beforeEach, describe, expect, it } from 'vitest';
import { useCameraStore } from './cameraStore';

describe('cameraStore (T-025)', () => {
  beforeEach(() => {
    useCameraStore.setState({ activeCameraId: null });
  });

  it('arranca sin cámara activa', () => {
    expect(useCameraStore.getState().activeCameraId).toBeNull();
  });

  it('fija la cámara activa al elegirla', () => {
    useCameraStore.getState().setActiveCamera('0');
    expect(useCameraStore.getState().activeCameraId).toBe('0');
  });

  it('reemplaza la cámara activa anterior', () => {
    useCameraStore.getState().setActiveCamera('0');
    useCameraStore.getState().setActiveCamera('2');
    expect(useCameraStore.getState().activeCameraId).toBe('2');
  });
});