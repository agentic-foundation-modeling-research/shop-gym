/** The format and the pixel size of a PNG or JPEG file, read from its header. */

export interface ImageInfo {
  /** File extension including the dot: `.png` or `.jpg`. */
  readonly extension: '.png' | '.jpg';
  readonly width: number;
  readonly height: number;
}

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
/** JPEG markers with no length field after them. */
const STANDALONE_MARKERS = new Set([0x01, 0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8]);

function isSofMarker(marker: number): boolean {
  return marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc;
}

function pngInfo(bytes: Buffer): ImageInfo | undefined {
  if (bytes.length < 24 || !PNG_SIGNATURE.every((b, i) => bytes[i] === b)) return undefined;
  return { extension: '.png', width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

/** Walks the JPEG segments to the first start-of-frame segment, which holds the size. */
function jpegInfo(bytes: Buffer): ImageInfo | undefined {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) return undefined;
  let at = 2;
  while (at + 3 < bytes.length) {
    if (bytes[at] !== 0xff) return undefined;
    const marker = bytes[at + 1] ?? 0;
    if (marker === 0xff) {
      at += 1;
    } else if (STANDALONE_MARKERS.has(marker)) {
      at += 2;
    } else if (isSofMarker(marker)) {
      if (at + 9 > bytes.length) return undefined;
      return {
        extension: '.jpg',
        height: bytes.readUInt16BE(at + 5),
        width: bytes.readUInt16BE(at + 7),
      };
    } else {
      at += 2 + bytes.readUInt16BE(at + 2);
    }
  }
  return undefined;
}

/** `undefined` when `bytes` is not a PNG or a JPEG file with a readable size. */
export function imageInfo(bytes: Buffer): ImageInfo | undefined {
  const info = pngInfo(bytes) ?? jpegInfo(bytes);
  return info !== undefined && info.width > 0 && info.height > 0 ? info : undefined;
}
