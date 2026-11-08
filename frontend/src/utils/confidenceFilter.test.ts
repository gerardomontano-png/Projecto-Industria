import { describe, expect, it } from 'vitest';
import { filterByConfidence, filterResultByConfidence } from './confidenceFilter';
import type { InferenceResult } from '../types';

const bbox = { x1: 0, y1: 0, x2: 10, y2: 10 };

describe('filterByConfidence', () => {
  it('conserva los elementos con confianza >= umbral (incluye el borde)', () => {
    const items = [{ confidence: 0.2 }, { confidence: 0.5 }, { confidence: 0.9 }];
    expect(filterByConfidence(items, 0.5)).toEqual([{ confidence: 0.5 }, { confidence: 0.9 }]);
  });
});

describe('filterResultByConfidence', () => {
  it('filtra detecciones de localización y vuelve a mostrarlas al bajar el umbral', () => {
    const raw: InferenceResult = {
      task: 'localization',
      modelId: 'm',
      roi: null,
      detections: [
        { classId: 0, confidence: 0.3, bbox },
        { classId: 1, confidence: 0.8, bbox },
      ],
    };
    const alto = filterResultByConfidence(raw, 0.6);
    expect(alto.task === 'localization' && alto.detections).toHaveLength(1);
    const bajo = filterResultByConfidence(raw, 0.1);
    expect(bajo.task === 'localization' && bajo.detections).toHaveLength(2);
  });

  it('filtra predicciones de clasificación', () => {
    const raw: InferenceResult = {
      task: 'classification',
      modelId: 'm',
      roi: null,
      predictions: [
        { classId: 0, confidence: 0.7 },
        { classId: 1, confidence: 0.1 },
      ],
    };
    const out = filterResultByConfidence(raw, 0.5);
    expect(out.task === 'classification' && out.predictions.map((p) => p.classId)).toEqual([0]);
  });

  it('filtra líneas de OCR', () => {
    const raw: InferenceResult = {
      task: 'ocr',
      modelId: 'm',
      roi: null,
      results: [
        { text: 'A', confidence: 0.95 },
        { text: 'B', confidence: 0.4 },
      ],
    };
    const out = filterResultByConfidence(raw, 0.5);
    expect(out.task === 'ocr' && out.results.map((r) => r.text)).toEqual(['A']);
  });

  it('no modifica el resultado original', () => {
    const raw: InferenceResult = {
      task: 'ocr',
      modelId: 'm',
      roi: null,
      results: [{ text: 'B', confidence: 0.4 }],
    };
    filterResultByConfidence(raw, 0.9);
    expect(raw.task === 'ocr' && raw.results).toHaveLength(1);
  });
});
