const COLOR_NAME_TO_HEX: Record<string, string> = {
  black: '#1c1c1e',
  white: '#f4f1ec',
  ivory: '#ede4d3',
  cream: '#f0e6d2',
  blush: '#e8c5c0',
  pink: '#f0bdbf',
  rose: '#d2867f',
  red: '#b8454a',
  burgundy: '#6b2230',
  berry: '#8d3a52',
  orange: '#d97a3c',
  rust: '#a85333',
  blaze: '#c45a2b',
  butter: '#f0d977',
  yellow: '#e8c54e',
  gold: '#c5a47e',
  champagne: '#d8c19a',
  sand: '#d6c4a4',
  camel: '#b89a78',
  caramel: '#a07a4c',
  tan: '#c2a37c',
  brown: '#7a5638',
  taupe: '#a08c78',
  mocha: '#6f4e3a',
  green: '#4d6a4a',
  sage: '#9aa787',
  forest: '#2e4030',
  olive: '#6b6f3c',
  mint: '#bcd4b8',
  aqua: '#9cc7c0',
  teal: '#3e7575',
  blue: '#4a6c93',
  alpine: '#7090b8',
  navy: '#212d44',
  denim: '#5a7595',
  midnight: '#1d2538',
  slate: '#5b6671',
  carbon: '#3a3a3c',
  charcoal: '#2f2f31',
  graphite: '#404044',
  basalt: '#3e3a36',
  ash: '#a8a29a',
  grey: '#8a8a8c',
  gray: '#8a8a8c',
  silver: '#cbc6c0',
  pearl: '#ece5d8',
  amethyst: '#7c5d8a',
  purple: '#6c4c80',
  velvet: '#5a3a4d',
  storm: '#586674',
  obsidian: '#1a1a1e',
  dune: '#c8b59a',
  vendarena: '#8b6f4f',
};

const FALLBACK_HEX = '#c5a47e';

export function colorNameToHex(name: string): string {
  const lc = name.toLowerCase();
  for (const key of Object.keys(COLOR_NAME_TO_HEX)) {
    if (lc.includes(key)) return COLOR_NAME_TO_HEX[key];
  }
  return FALLBACK_HEX;
}

export function isLightColor(hex: string): boolean {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.78;
}

export function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

export function formatRating(seed: string): {stars: number; count: number} {
  const h = hashString(seed);
  const stars = Math.min(5.0, parseFloat((4.0 + ((h % 100) / 100)).toFixed(1)));
  const count = (h % 880) + 32;
  return {stars, count};
}
