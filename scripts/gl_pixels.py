#!/usr/bin/env python3
"""Tiny screenshot reader for the YouTube like/comment flows (standard library only).

The phone's UI text cannot be read reliably while a video plays, so flows check what they did by looking at the pixels of the
screenshot they already take. Every probe works on RELATIVE positions (fractions of width/height), so it is not tied to one
screen size, and every probe can answer "unknown" (None / "unknown"): callers must treat unknown as "carry on, but say so",
never as proof either way.

Only 8-bit, non-interlaced PNG is decoded (that is what GeeLark sends). Anything else returns None from `decode_png`.
Not related to gl_vision.py, which captures and OCRs the desktop app's window.
"""

import struct
import zlib


class Image:
    """Decoded screenshot: .w, .h and a pixel accessor returning (r, g, b)."""

    def __init__(self, w, h, rows, channels):
        self.w, self.h, self._rows, self._ch = w, h, rows, channels

    def px(self, x, y):
        x = min(self.w - 1, max(0, int(x)))
        y = min(self.h - 1, max(0, int(y)))
        row, c = self._rows[y], self._ch
        i = x * c
        if c >= 3:
            return row[i], row[i + 1], row[i + 2]
        return row[i], row[i], row[i]                        # grey / grey+alpha

    def at(self, fx, fy):
        """Pixel at a relative position (0..1, 0..1)."""
        return self.px(fx * self.w, fy * self.h)


def decode_png(data):
    """Return an Image, or None if `data` is not a PNG this reader understands."""
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if not ihdr:
        return None
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or channels is None or w * h > 12_000_000:
        return None
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    stride = w * channels
    if len(raw) < h * (stride + 1):
        return None
    rows, prev = [], bytearray(stride)
    p = 0
    for _ in range(h):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif f != 0:
            return None
        rows.append(line)
        prev = line
    return Image(w, h, rows, channels)


def encode_png(w, h, rgb_rows):
    """Minimal RGB PNG writer (used to make small test fixtures)."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(row) for row in rgb_rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def downscale(img, factor):
    """Nearest-neighbour downscale by an integer factor; returns (w, h, rows of RGB bytes)."""
    w, h = img.w // factor, img.h // factor
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row.extend(img.px(x * factor + factor // 2, y * factor + factor // 2))
        rows.append(row)
    return w, h, rows


def _lum(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def _is_red(p):
    return p[0] > 190 and p[1] < 70 and p[2] < 100 and p[0] - p[1] > 140


# ---------------------------------------------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------------------------------------------
def dark_fraction(img, fx, fy, half_w, half_h, threshold=90):
    """Share of dark pixels in a box around a relative point (box size relative to the image width)."""
    cx, cy = fx * img.w, fy * img.h
    hw, hh = half_w * img.w, half_h * img.w
    step = max(1, img.w // 180)
    total = dark = 0
    y = cy - hh
    while y <= cy + hh:
        x = cx - hw
        while x <= cx + hw:
            total += 1
            if _lum(img.px(x, y)) < threshold:
                dark += 1
            x += step
        y += step
    return dark / total if total else 0.0


def like_fraction(img, fx=0.486, fy=0.446):
    return dark_fraction(img, fx, fy, 0.039, 0.039)


def like_state(img, fx=0.486, fy=0.446):
    """'filled' | 'outline' | 'unknown' for the Like thumb. Only trusted on the normal watch page: on an ad or any other screen
    the same spot shows unrelated pixels (one ad panel looked 'filled'), so the answer there is always 'unknown'."""
    if not watch_page_ready(img):
        return "unknown"
    f = like_fraction(img, fx, fy)
    if f >= LIKE_FILLED_MIN:
        return "filled"
    if f <= LIKE_OUTLINE_MAX:
        return "outline"
    return "unknown"


def red_blob(img, region=(0.78, 0.33, 1.0, 0.63), min_share=0.0025):
    """Centre (fx, fy) of the red Send arrow's circle inside a relative region, or None. Needs a solid red area."""
    x0, y0, x1, y1 = region
    xs, ys, n = 0.0, 0.0, 0
    step = max(1, img.w // 180)
    y = int(y0 * img.h)
    while y < int(y1 * img.h):
        x = int(x0 * img.w)
        while x < int(x1 * img.w):
            if _is_red(img.px(x, y)):
                xs += x
                ys += y
                n += 1
            x += step
        y += step
    area = ((x1 - x0) * img.w / step) * ((y1 - y0) * img.h / step)
    if n == 0 or n / area < min_share:
        return None
    return xs / n / img.w, ys / n / img.h


def watch_page_ready(img):
    """True when the page under the player is the normal watch page (the grey 'Comments' card is there), False when an ad
    panel or another screen covers it. Colours: card #F2F2F2, 'Comment...' pill about #E5E5E5, page white."""
    card = img.at(0.5, 0.505)
    pill = img.at(0.55, 0.566)
    page = img.at(0.5, 0.62)
    near = lambda p, ref, tol: all(abs(p[i] - ref[i]) <= tol for i in range(3))
    return near(card, (242, 242, 242), 7) and near(pill, (229, 229, 229), 9) and near(page, (255, 255, 255), 6)


def watch_page_basic(img):
    """Looser than watch_page_ready: the grey Comments card sits under the player and white page below it, with no check of what
    is inside the card. Some videos show a featured comment there instead of the 'Add a comment' pill, which fails the strict
    check. An ad panel, My Ad Center or an error page has no grey card at that height, so it is still told apart."""
    card = img.at(0.5, 0.505)
    page = img.at(0.5, 0.62)
    near = lambda p, ref, tol: all(abs(p[i] - ref[i]) <= tol for i in range(3))
    above, margin = img.at(0.5, 0.48), img.at(0.03, 0.52)      # the card has white above it and a white margin at its left
    return (near(card, (242, 242, 242), 7) and near(page, (255, 255, 255), 6)
            and near(above, (255, 255, 255), 6) and near(margin, (255, 255, 255), 6))


# Calibrated on real 720x1440 screenshots from 7 different videos: the outline thumb measures 0.138 every time and the filled
# thumb 0.236 every time, so the cut-offs sit in between with a gap that answers "unknown" (see tests/test_pixels.py).
LIKE_FILLED_MIN = 0.21
LIKE_OUTLINE_MAX = 0.165


# --- the video description sheet (used by the description-link task) -----------------------------------------------------
# Calibrated on a real 720x1440 screenshot: the description box is #E4EFFB and link text is exactly #065FD4.
DESC_BOX = (228, 239, 251)
LINK_BLUE = (6, 95, 212)


def _near(p, ref, tol):
    return all(abs(p[i] - ref[i]) <= tol for i in range(3))


def description_open(img):
    """True when the description sheet is showing: at least half of a strip inside its light-blue box has the box colour.
    The normal watch page, an ad panel, My Ad Center and an error page have no such strip."""
    hits = total = 0
    for k in range(10):
        fy = 0.64 + 0.16 * k / 9
        for fx in (0.07, 0.5, 0.93):
            total += 1
            hits += _near(img.at(fx, fy), DESC_BOX, 8)
    return hits / total >= 0.5


def link_bands(img, top=0.45, bottom=0.86):
    """Blue link text lines on the description sheet, top to bottom, as relative (x, y) centres to tap. A link that wraps onto
    a second line counts twice; the sheet shows each link on one line with an ellipsis, so that is rare."""
    bands, cur = [], None
    for y in range(int(img.h * top), int(img.h * bottom)):
        xs = [x for x in range(0, img.w, 2) if _near(img.px(x, y), LINK_BLUE, 25)]
        if len(xs) >= 4:
            if cur and y - cur["last"] <= 4:
                cur["last"] = y
                cur["xs"] += xs
            else:
                cur = {"first": y, "last": y, "xs": list(xs)}
                bands.append(cur)
    out = []
    for b in bands:
        if b["last"] - b["first"] < 8 or max(b["xs"]) - min(b["xs"]) < 0.15 * img.w:
            continue                                   # a few stray pixels or a blue emoji, not a line of link text
        out.append((sum(b["xs"]) / len(b["xs"]) / img.w, (b["first"] + b["last"]) / 2 / img.h))
    return out
