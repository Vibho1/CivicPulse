// Generates the PWA PNG icons from the same artwork as public/icons/icon.svg.
// Pure Node (zlib only) so it works without any image library:  npm run icons
import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons');

// ---- minimal PNG encoder -----------------------------------------------------
const CRC_TABLE = new Int32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});
function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function encodePng(size, rgba) {
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0; // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ---- artwork (unit square coordinates, matches icon.svg) ---------------------
const PULSE = [
  [72, 266], [164, 266], [205, 154], [256, 368], [297, 226], [328, 266], [440, 266],
].map(([x, y]) => [x / 512, y / 512]);
const DOT = { x: 440 / 512, y: 266 / 512, r: 26 / 512 };
const STROKE = 36 / 512;

function segDist(px, py, ax, ay, bx, by) {
  const abx = bx - ax, aby = by - ay;
  const den = abx * abx + aby * aby || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - ax) * abx + (py - ay) * aby) / den));
  const cx = ax + t * abx, cy = ay + t * aby;
  return Math.hypot(px - cx, py - cy);
}
function roundedRectInside(u, v, radius) {
  const x = Math.min(u, 1 - u), y = Math.min(v, 1 - v);
  if (x >= radius || y >= radius) return true;
  return Math.hypot(radius - x, radius - y) <= radius;
}
function lerp(a, b, t) { return a + (b - a) * t; }

// Returns [r,g,b,a] for a unit-space point.
function shade(u, v, { fullBleed, contentScale }) {
  const bgRadius = fullBleed ? 0 : 112 / 512;
  if (!fullBleed && !roundedRectInside(u, v, bgRadius)) return [0, 0, 0, 0];
  const t = Math.max(0, Math.min(1, (u + v) / 2));
  let r = lerp(0x4f, 0x0d, t), g = lerp(0x46, 0x94, t), b = lerp(0xe5, 0x88, t);
  // map into the (possibly padded) artwork space
  const au = (u - 0.5) / contentScale + 0.5;
  const av = (v - 0.5) / contentScale + 0.5;
  let onInk = Math.hypot(au - DOT.x, av - DOT.y) <= DOT.r;
  if (!onInk) {
    for (let i = 0; i < PULSE.length - 1 && !onInk; i++) {
      const [ax, ay] = PULSE[i], [bx, by] = PULSE[i + 1];
      if (segDist(au, av, ax, ay, bx, by) <= STROKE / 2) onInk = true;
    }
  }
  if (onInk) { r = 255; g = 255; b = 255; }
  return [r, g, b, 255];
}

function render(size, opts) {
  const S = 3; // supersampling factor for anti-aliasing
  const out = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let j = 0; j < S; j++) {
        for (let i = 0; i < S; i++) {
          const [pr, pg, pb, pa] = shade((x + (i + 0.5) / S) / size, (y + (j + 0.5) / S) / size, opts);
          r += pr * pa; g += pg * pa; b += pb * pa; a += pa;
        }
      }
      const idx = (y * size + x) * 4;
      if (a > 0) {
        out[idx] = Math.round(r / a);
        out[idx + 1] = Math.round(g / a);
        out[idx + 2] = Math.round(b / a);
      }
      out[idx + 3] = Math.round(a / (S * S));
    }
  }
  return encodePng(size, out);
}

mkdirSync(OUT, { recursive: true });
const files = [
  ['icon-192.png', 192, { fullBleed: false, contentScale: 1 }],
  ['icon-512.png', 512, { fullBleed: false, contentScale: 1 }],
  ['maskable-512.png', 512, { fullBleed: true, contentScale: 0.8 }],
  ['apple-touch-icon.png', 180, { fullBleed: true, contentScale: 0.92 }],
];
for (const [name, size, opts] of files) {
  writeFileSync(join(OUT, name), render(size, opts));
  console.log('wrote', join(OUT, name));
}
