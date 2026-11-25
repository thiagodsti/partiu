import { describe, expect, it } from 'vitest';
import { labelExpression, localizeStyle, mapLanguage } from './mapStyle';

describe('mapLanguage', () => {
  it('maps the app locales onto OSM language suffixes', () => {
    expect(mapLanguage('pt-BR')).toBe('pt');
    expect(mapLanguage('en')).toBe('en');
    expect(mapLanguage(null)).toBe('en');
    expect(mapLanguage(undefined)).toBe('en');
  });
});

describe('localizeStyle', () => {
  const style = {
    version: 8,
    layers: [
      { id: 'bg', type: 'background' },
      {
        id: 'place_city',
        type: 'symbol',
        layout: { 'text-field': ['coalesce', ['get', 'name_en'], ['get', 'name']], 'text-size': 14 },
      },
      { id: 'road_shield', type: 'symbol', layout: { 'text-field': '{ref}' } },
    ],
  };

  it('points name labels at the chosen language, then Latin, then local', () => {
    const out = localizeStyle(style, 'pt');
    const city = out.layers.find((l) => l.id === 'place_city') as { layout: Record<string, unknown> };
    expect(city.layout['text-field']).toEqual(labelExpression('pt'));
    expect(labelExpression('pt')).toEqual([
      'coalesce',
      ['get', 'name:pt'],
      ['get', 'name:latin'],
      ['get', 'name'],
    ]);
    // Other layout properties survive.
    expect(city.layout['text-size']).toBe(14);
  });

  it('leaves non-name labels and unlabelled layers alone', () => {
    const out = localizeStyle(style, 'en');
    expect(out.layers.find((l) => l.id === 'road_shield')).toEqual(style.layers[2]);
    expect(out.layers.find((l) => l.id === 'bg')).toEqual(style.layers[0]);
  });

  it('does not mutate the input', () => {
    const before = JSON.stringify(style);
    localizeStyle(style, 'pt');
    expect(JSON.stringify(style)).toBe(before);
  });
});
