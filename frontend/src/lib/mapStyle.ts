/* Basemap for the planner map: OpenFreeMap vector tiles with the labels
 * rewritten into the reader's language.
 *
 * Raster tiles have their labels baked in. OSM's are in each place's local
 * script (北京, Oslo kommune), and CARTO's are Latin/English for everyone, so
 * neither one can follow the profile's locale. The vector tiles carry
 * `name:pt` / `name:en` beside `name`. We fetch the published style and point
 * every text label at the reader's language, falling back to the Latin
 * transliteration and then to the local name. Without the Latin step a place
 * with no Portuguese name would come back in its own script. */

export const OPENFREEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';

/** The OSM `name:*` suffix for an app locale. */
export function mapLanguage(appLocale: string | null | undefined): 'pt' | 'en' {
  return appLocale?.toLowerCase().startsWith('pt') ? 'pt' : 'en';
}

/** The label expression for one language. */
export function labelExpression(lang: string): unknown[] {
  return ['coalesce', ['get', `name:${lang}`], ['get', 'name:latin'], ['get', 'name']];
}

interface StyleLayer {
  layout?: Record<string, unknown>;
  [k: string]: unknown;
}
interface Style {
  layers?: StyleLayer[];
  [k: string]: unknown;
}

/** A copy of `style` whose name labels read in `lang`. Labels that are not
 *  place names, such as road shields (`ref`), are left as they are. */
export function localizeStyle<T extends Style>(style: T, lang: string): T {
  const layers = (style.layers ?? []).map((layer) => {
    const field = layer.layout?.['text-field'];
    if (field === undefined || !JSON.stringify(field).includes('name')) return layer;
    return { ...layer, layout: { ...layer.layout, 'text-field': labelExpression(lang) } };
  });
  return { ...style, layers };
}

/** True when the browser can draw a WebGL map at all. */
export function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}
