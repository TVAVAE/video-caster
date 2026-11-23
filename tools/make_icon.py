"""Draws the Video Caster logo: a purple tile with a white play triangle sending waves out -
'play, on the TV'. Writes the Windows icon (every size Windows asks for, simplified for the
smallest), the PNGs the window uses, and the README logo.

Run from the repository root:  python tools\\make_icon.py
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TOP, BOTTOM = QColor("#c58ef0"), QColor("#5a2a97")  # around the app's accent #a465c9


def draw(size):
    """The logo as a QImage of size x size, drawn for that size (no scaling of a big one)."""
    s = float(size)
    k = s / 256.0
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    # the tile: a rounded square with a diagonal purple gradient and a soft light on top
    pad = 10 * k if size >= 48 else (1 if size >= 24 else 0.5)
    tile = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)
    r = tile.width() * 0.23
    shape = QPainterPath()
    shape.addRoundedRect(tile, r, r)
    g = QLinearGradient(tile.topLeft(), tile.bottomRight())
    g.setColorAt(0, TOP)
    g.setColorAt(1, BOTTOM)
    p.fillPath(shape, g)
    light = QLinearGradient(0, tile.top(), 0, tile.center().y())
    light.setColorAt(0, QColor(255, 255, 255, 60))
    light.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(shape, light)

    # the mark, on a 256 grid: play triangle + waves (two from 32 px, one below)
    small = size <= 24
    if small:
        tri = [(64, 66), (64, 190), (150, 128)]
        arcs = [(118, 128, 76, 30)]                      # centre x, centre y, radius, stroke
        join = 30
    else:
        tri = [(62, 70), (62, 186), (146, 128)]
        arcs = [(118, 128, 64, 19), (118, 128, 98, 19)]
        join = 22

    def mark(color, dy=0.0, fade=True):
        poly = QPolygonF([QPointF(x * k, (y + dy) * k) for x, y in tri])
        p.setPen(QPen(color, join * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # rounds the corners
        p.setBrush(color)
        p.drawPolygon(poly)
        for i, (cx, cy, rad, w) in enumerate(arcs):
            c = QColor(color)
            if fade and i:
                c.setAlpha(int(c.alpha() * 0.72))
            p.setPen(QPen(c, w * k, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            box = QRectF((cx - rad) * k, (cy + dy - rad) * k, 2 * rad * k, 2 * rad * k)
            p.drawArc(box, -48 * 16, 96 * 16)

    if size >= 32:
        mark(QColor(45, 12, 80, 70), dy=6)  # a soft shadow below the mark
    mark(QColor("white"))
    p.end()
    return img


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def dib_bytes(img):
    """An icon image the classic way: 32-bit BGRA bitmap rows bottom-up, plus the 1-bit mask
    older parts of Windows still read (set where the pixel is fully transparent)."""
    img = img.convertToFormat(QImage.Format_ARGB32)  # straight alpha, stored B, G, R, A
    w, h = img.width(), img.height()
    rows = [bytes(img.constScanLine(y))[: w * 4] for y in range(h)]
    pixels = b"".join(reversed(rows))
    stride = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in reversed(range(h)):
        row = bytearray(stride)
        for x in range(w):
            if rows[y][x * 4 + 3] == 0:
                row[x // 8] |= 0x80 >> (x % 8)
        mask += row
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + bytes(mask)


def write_ico(path, images):
    """A Windows .ico: classic bitmaps up to 128 px (every part of Windows reads those) and a
    PNG for 256 px, as Windows expects."""
    head = struct.pack("<HHH", 0, 1, len(images))
    entries, data = b"", b""
    offset = 6 + 16 * len(images)
    for size, img in images:
        blob = png_bytes(img) if size >= 256 else dib_bytes(img)
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    Path(path).write_bytes(head + entries + data)


def main():
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - painting needs a GUI application
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [(n, draw(n)) for n in ICO_SIZES]
    write_ico(ASSETS / "videocaster.ico", images)
    for n in (16, 24, 32, 48, 64, 256):
        (ASSETS / f"icon_{n}.png").write_bytes(png_bytes(dict(images)[n]))
    draw(512).save(str(ROOT / "docs" / "logo.png"))
    print("written:", ASSETS / "videocaster.ico", "icon_*.png and docs/logo.png")


if __name__ == "__main__":
    main()
