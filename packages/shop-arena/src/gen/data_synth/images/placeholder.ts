/**
 * Offline image backend: a flat background whose hue comes from the
 * product category, with one of four accent shapes picked from the
 * product handle and image index. Same request, same bytes.
 */

import { createHash } from 'node:crypto';

import type { ImageBackend, ImageRequest } from './backend.js';
import { encodePng } from './png.js';

type Rgb = readonly [number, number, number];

function hslToRgb(h: number, s: number, l: number): Rgb {
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t: number): number => {
    const x = ((t % 1) + 1) % 1;
    if (x < 1 / 6) return p + (q - p) * 6 * x;
    if (x < 1 / 2) return q;
    if (x < 2 / 3) return p + (q - p) * (2 / 3 - x) * 6;
    return p;
  };
  return [
    Math.round(channel(h + 1 / 3) * 255),
    Math.round(channel(h) * 255),
    Math.round(channel(h - 1 / 3) * 255),
  ];
}

const SHAPES = ['circle', 'square', 'triangle', 'diamond'] as const;

function inside(shape: (typeof SHAPES)[number], dx: number, dy: number, r: number): boolean {
  switch (shape) {
    case 'circle':
      return dx * dx + dy * dy <= r * r;
    case 'square':
      return Math.abs(dx) <= r && Math.abs(dy) <= r;
    case 'triangle':
      return dy >= -r && dy <= r && Math.abs(dx) <= ((dy + r) / (2 * r)) * r;
    case 'diamond':
      return Math.abs(dx) + Math.abs(dy) <= r;
  }
}

/** Renders the placeholder bitmap; exported for determinism tests. */
export function renderPlaceholder(request: ImageRequest): Buffer {
  const { width, height } = request;
  if (width <= 0 || height <= 0) {
    throw new RangeError('image dimensions must be positive');
  }
  const categoryHash = createHash('sha256').update(request.category).digest();
  const itemHash = createHash('sha256').update(`${request.handle}|${request.index}`).digest();
  const hue = (categoryHash[0] as number) / 256;
  const background = hslToRgb(hue, 0.45, 0.85);
  const accent = hslToRgb(hue, 0.45, 0.45);
  const shape = SHAPES[(itemHash[0] as number) % SHAPES.length] as (typeof SHAPES)[number];
  const cx = Math.floor(width / 2);
  const cy = Math.floor(height / 2);
  const r = Math.floor(Math.min(width, height) / 4);
  const rgb = new Uint8Array(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const color = inside(shape, x - cx, y - cy, r) ? accent : background;
      rgb.set(color, (y * width + x) * 3);
    }
  }
  return encodePng(width, height, rgb);
}

export class PlaceholderImageBackend implements ImageBackend {
  readonly name = 'placeholder';
  readonly extension = '.png';

  async render(request: ImageRequest): Promise<Uint8Array> {
    return renderPlaceholder(request);
  }
}
