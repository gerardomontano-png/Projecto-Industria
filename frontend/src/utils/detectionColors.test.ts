import { describe, expect, it } from 'vitest';
import type { AccuracyLevel } from '../store/detectionColorStore';
import { migrateLevels } from '../store/detectionColorStore';
import { UNKNOWN_CLASS_COLOR, colorForClass, colorForConfidence } from './detectionColors';

const ALTA = '#B4D678';
const MEDIA = '#A3C2DF';
const BAJA = '#BD7066';

function levels(mediaThreshold = 31): AccuracyLevel[] {
  return [
    { label: 'Alta', color: ALTA, threshold: 70, operator: '>=' },
    { label: 'Media', color: MEDIA, threshold: mediaThreshold, operator: '>=' },
    { label: 'Baja', color: BAJA, threshold: 30, operator: '<=' },
  ];
}

describe('colorForConfidence', () => {
  it('asigna cada rango de confianza a su nivel', () => {
    expect(colorForConfidence(0.9, levels())).toBe(ALTA);
    expect(colorForConfidence(0.7, levels())).toBe(ALTA);
    expect(colorForConfidence(0.56, levels())).toBe(MEDIA);
    expect(colorForConfidence(0.31, levels())).toBe(MEDIA);
    expect(colorForConfidence(0.3, levels())).toBe(BAJA);
    expect(colorForConfidence(0.05, levels())).toBe(BAJA);
  });

  it('ninguna detección queda en gris aunque los umbrales dejen un hueco', () => {
    // Configuración anterior: Media ≥ 50 y Baja ≤ 30 dejaban 31–49 % sin nivel.
    const conHueco = levels(50);
    for (const confidence of [0.305, 0.31, 0.41, 0.45, 0.499]) {
      expect(colorForConfidence(confidence, conHueco)).toBe(BAJA);
    }
  });

  it('cubre valores con decimales entre Baja y Media', () => {
    expect(colorForConfidence(0.305, levels())).toBe(BAJA);
  });

  it('no depende del orden en que vengan los niveles', () => {
    const desordenados = [...levels()].reverse();
    expect(colorForConfidence(0.9, desordenados)).toBe(ALTA);
    expect(colorForConfidence(0.4, desordenados)).toBe(MEDIA);
    expect(colorForConfidence(0.1, desordenados)).toBe(BAJA);
  });

  it('usa el color neutro solo si no hay niveles configurados', () => {
    expect(colorForConfidence(0.5, [])).toBe(UNKNOWN_CLASS_COLOR);
  });
});

describe('migrateLevels', () => {
  it('corrige el umbral de Media guardado por la versión anterior', () => {
    const migrated = migrateLevels({ levels: levels(50) }, 0);
    expect(migrated.levels.find((l) => l.label === 'Media')?.threshold).toBe(31);
  });

  it('respeta un umbral que el usuario cambió a propósito', () => {
    const migrated = migrateLevels({ levels: levels(45) }, 0);
    expect(migrated.levels.find((l) => l.label === 'Media')?.threshold).toBe(45);
  });

  it('no toca la configuración ya migrada', () => {
    const current = levels(50);
    expect(migrateLevels({ levels: current }, 1).levels).toBe(current);
  });
});

describe('colorForClass', () => {
  it('da siempre el mismo color a la misma clase', () => {
    expect(colorForClass(2)).toBe(colorForClass(2));
    expect(colorForClass(0)).not.toBe(colorForClass(1));
  });
});
