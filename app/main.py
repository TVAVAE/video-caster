"""Video Caster - cast local videos to a Chromecast or Apple TV.

A compact player window: now-playing header with a frame preview, transport
controls, a seek bar, playlists with drag and drop, a device menu and a settings
panel for audio, subtitles and conversion. The engine is in backend.py."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend as be  # noqa: E402

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QIcon, QImage, QKeySequence,  # noqa: E402
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut,
                           QGuiApplication)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup,  # noqa: E402
                               QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSizeGrip, QSlider, QStyle, QStyledItemDelegate, QTabBar,
                               QToolButton, QToolTip, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
                               QWidgetAction)

APP_NAME = be.APP_NAME
DEFAULT_STATE = be.DATA_DIR / "state.json"

ACCENT = QColor("#a465c9")
ACCENT_DARK = QColor("#8a4db0")
HEADER_BG = "#3c3d48"
LIST_BG = "#e5e5e8"
TOP_H, HEADER_H, THUMB_W = 128, 68, 200
WINDOW_W = 490


# --------------------------------------------------------------------------- small helpers

class Bridge(QObject):
    """Runs a function on the window's thread when emitted from a worker thread."""
    call = Signal(object)


def worker(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def draw_icon(name, color, size=28, disabled="#c6c6cd"):
    """The icon in `color`, with a light grey version Qt shows while the button is disabled."""
    icon = QIcon()
    icon.addPixmap(_icon_pixmap(name, color, size), QIcon.Normal)
    icon.addPixmap(_icon_pixmap(name, disabled, size), QIcon.Disabled)
    return icon


def _icon_pixmap(name, color, size=28):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2 * size / 28.0, 2 * size / 28.0)  # draw on a 28x28 grid
    c = QColor(color)
    pen = QPen(c, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if name == "list":
        for y in (8, 14, 20):
            p.fillRect(QRectF(3, y - 1.5, 3, 3), c)
            p.drawLine(QPointF(9, y), QPointF(25, y))
    elif name == "rewind":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 20, 20), 110)
        path.arcTo(QRectF(4, 4, 20, 20), 110, 300)
        p.drawPath(path)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(4.5, 6), QPointF(11.5, 5.2), QPointF(7.5, 11)]))
        f = QFont("Segoe UI", 7)
        f.setBold(True)
        p.setFont(f)
        p.setPen(c)
        p.drawText(QRectF(4, 8, 20, 13), Qt.AlignCenter, "10")
    elif name == "play":
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(24, 14), QPointF(7, 24)]))
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(7, 5, 5, 18), 1, 1)
        p.drawRoundedRect(QRectF(16, 5, 5, 18), 1, 1)
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 6, 16, 16), 1.5, 1.5)
    elif name == "next":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(5, 5), QPointF(18, 14), QPointF(5, 23)]))
        p.drawRoundedRect(QRectF(19.5, 5, 3.5, 18), 1, 1)
    elif name == "gear":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        path = QPainterPath()
        path.addEllipse(QPointF(14, 14), 8, 8)
        for i in range(8):
            p.save()
            p.translate(14, 14)
            p.rotate(i * 45)
            p.drawRoundedRect(QRectF(-2.6, -12, 5.2, 6), 1, 1)
            p.restore()
        hole = QPainterPath()
        hole.addEllipse(QPointF(14, 14), 3.6, 3.6)
        p.drawPath(path.subtracted(hole))
    elif name == "cast":
        p.drawRoundedRect(QRectF(3.5, 5, 21, 14), 2, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(9, 25), QPointF(14, 18.5), QPointF(19, 25)]))
    elif name == "screen":  # a PC screen with an arrow going out of it
        p.drawRoundedRect(QRectF(3.5, 4.5, 21, 14.5), 2, 2)
        p.drawLine(QPointF(14, 19), QPointF(14, 23))
        p.drawLine(QPointF(9, 23.5), QPointF(19, 23.5))
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawLine(QPointF(9.5, 15), QPointF(17, 8.5))
        p.drawPolyline(QPolygonF([QPointF(12.5, 8.3), QPointF(17.2, 8.3), QPointF(17.2, 13)]))
    elif name == "screens":  # this PC's screen and the TV next to it: the TV as a second display
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(2.5, 9.5, 10, 8), 1.5, 1.5)
        p.drawLine(QPointF(7.5, 17.5), QPointF(7.5, 20.5))
        p.drawLine(QPointF(5, 21), QPointF(10, 21))
        p.drawRoundedRect(QRectF(14.5, 5.5, 11.5, 13), 1.5, 1.5)
        p.drawLine(QPointF(20.25, 18.5), QPointF(20.25, 22))
        p.drawLine(QPointF(17, 22.5), QPointF(23.5, 22.5))
    elif name == "bolt":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(16, 3), QPointF(6, 16), QPointF(13, 16), QPointF(11, 25),
                                 QPointF(22, 11), QPointF(15, 11)]))
    elif name in ("speaker", "speaker-off"):
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(4, 11), QPointF(9, 11), QPointF(15, 5.5), QPointF(15, 22.5),
                                 QPointF(9, 17), QPointF(4, 17)]))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if name == "speaker":
            p.drawArc(QRectF(12, 9, 8, 10), -50 * 16, 100 * 16)
            p.drawArc(QRectF(12, 5, 13, 18), -50 * 16, 100 * 16)
        else:
            p.drawLine(QPointF(18.5, 10.5), QPointF(25, 17.5))
            p.drawLine(QPointF(25, 10.5), QPointF(18.5, 17.5))
    elif name == "close":
        p.drawLine(QPointF(8, 8), QPointF(20, 20))
        p.drawLine(QPointF(20, 8), QPointF(8, 20))
    elif name == "minimize":
        p.drawLine(QPointF(8, 15), QPointF(20, 15))
    elif name == "plus":
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawEllipse(QPointF(14, 14), 9, 9)
        p.drawLine(QPointF(14, 9.5), QPointF(14, 18.5))
        p.drawLine(QPointF(9.5, 14), QPointF(18.5, 14))
    elif name == "x-small":
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawEllipse(QPointF(14, 14), 9, 9)
        p.drawLine(QPointF(10.5, 10.5), QPointF(17.5, 17.5))
        p.drawLine(QPointF(17.5, 10.5), QPointF(10.5, 17.5))
    elif name == "check":
        pen.setWidthF(2.6)
        p.setPen(pen)
        p.drawEllipse(QPointF(14, 14), 11.5, 11.5)
        p.drawPolyline(QPolygonF([QPointF(8.5, 14.5), QPointF(12.5, 18.5), QPointF(20, 9.5)]))
    elif name == "convert":
        pen.setWidthF(2.4)
        p.setPen(pen)
        p.drawArc(QRectF(5, 5, 18, 18), 30 * 16, 150 * 16)
        p.drawArc(QRectF(5, 5, 18, 18), 210 * 16, 150 * 16)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(20, 3.5), QPointF(23.5, 10), QPointF(16.5, 9.5)]))
        p.drawPolygon(QPolygonF([QPointF(8, 24.5), QPointF(4.5, 18), QPointF(11.5, 18.5)]))
    p.end()
    return pm


def dot_icon(color, hollow=False, size=14):
    """A small status dot (the TV chip: connected, connecting, ...)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    if hollow:
        p.setPen(QPen(c, 2.6))
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(c)
    p.drawEllipse(QRectF(size * 0.55, size * 0.55, size * 0.9, size * 0.9))
    p.end()
    return QIcon(pm)


def app_icon():
    """The Video Caster logo (app/assets, drawn by tools/make_icon.py) in every size it has."""
    icon = QIcon()
    folder = Path(__file__).resolve().parent / "assets"
    for n in (16, 24, 32, 48, 64, 256):
        f = folder / f"icon_{n}.png"
        if f.exists():
            icon.addFile(str(f), QSize(n, n))
    return icon


def tool_button(icon_name, tip, size=30, color=None):
    b = QToolButton()
    b.setIcon(draw_icon(icon_name, color or ACCENT))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def _upnext_card(title, frame_png=None):
    """The 'Up next' card shown on the TV while the next video loads (QImage only, so it can
    be drawn outside the window's thread)."""
    img = QImage(1920, 1080, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    grad = QLinearGradient(0, 0, 0, 1080)
    grad.setColorAt(0, QColor("#3c3d48"))
    grad.setColorAt(1, QColor("#16161c"))
    p.fillRect(img.rect(), grad)
    frame = QImage()
    if frame_png and frame.loadFromData(frame_png):
        frame = frame.scaled(1120, 630, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x, y = (1920 - frame.width()) // 2, 170
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, frame.width(), frame.height()), 18, 18)
        p.save()
        p.setClipPath(path)
        p.drawImage(x, y, frame)
        p.restore()
        text_y = y + frame.height() + 50
    else:
        text_y = 420
    f = QFont("Segoe UI", 26)
    f.setBold(True)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 6)
    p.setFont(f)
    p.setPen(ACCENT.lighter(130))
    p.drawText(QRectF(0, text_y, 1920, 60), Qt.AlignCenter, "UP NEXT")
    f = QFont("Segoe UI", 46)
    f.setWeight(QFont.DemiBold)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(80, text_y + 60, 1760, 110), Qt.AlignCenter,
               QFontMetrics(f).elidedText(title, Qt.ElideRight, 1760))
    p.end()
    return img


def collect_videos(paths):
    """Video files in `paths`, folders searched recursively, in name order."""
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs.sort(key=str.lower)
                for f in sorted(files, key=str.lower):
                    if Path(f).suffix.lower() in be.VIDEO_EXTS:
                        out.append(str(Path(root) / f))
        elif p.suffix.lower() in be.VIDEO_EXTS and p.is_file():
            out.append(str(p))
    return out


# --------------------------------------------------------------------------- state

def load_state(path):
    try:
        st = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if "playlists" not in st:  # older versions kept one playlist
        st["playlists"] = [{"name": "Playlist", "items": list(st.pop("playlist", []))}]
    if not st["playlists"]:
        st["playlists"] = [{"name": "Playlist", "items": []}]
    for key, default in (("current_playlist", 0), ("resume", {}), ("durations", {}), ("file_settings", {}),
                         ("global", {}), ("known_devices", []), ("device_id", None), ("playlist_visible", True)):
        st.setdefault(key, default)
    st["current_playlist"] = max(0, min(st["current_playlist"], len(st["playlists"]) - 1))
    if not st.get("hls_failed_v3"):
        # older versions also gave up HLS when a weak connection made it stall, or when a heavy
        # (4K) conversion was slow to start; forget those marks
        st["hls_failed"] = []
        st["hls_failed_v2"] = st["hls_failed_v3"] = True
    st["global"] = {**be.GLOBAL_DEFAULTS, **st["global"]}
    return st


def save_state(path, st):
    try:
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


# --------------------------------------------------------------------------- widgets

class SeekBar(QWidget):
    """Thin progress bar; click or drag to seek."""
    scrubbing = Signal(float)   # fraction while dragging
    seekTo = Signal(float)      # fraction on release

    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.fraction = 0.0
        self.drag = None
        self.duration = 0.0

    def set_fraction(self, f):
        if self.drag is None:
            self.fraction = max(0.0, min(1.0, f))
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#c9c9ce"))
        f = self.drag if self.drag is not None else self.fraction
        p.fillRect(QRectF(0, 0, self.width() * f, self.height()), ACCENT)

    def _frac(self, e):
        return max(0.0, min(1.0, e.position().x() / max(1, self.width())))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.duration > 0:
            self.drag = self._frac(e)
            self.scrubbing.emit(self.drag)
            self.update()

    def mouseMoveEvent(self, e):
        if self.duration > 0:
            self.setToolTip(be.fmt_time(self._frac(e) * self.duration))
        if self.drag is not None:
            self.drag = self._frac(e)
            self.scrubbing.emit(self.drag)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            f = self._frac(e)
            self.drag = None
            self.fraction = f
            self.update()
            self.seekTo.emit(f)


class Thumb(QLabel):
    """Frame preview in the top-right corner; carries the minimize/close buttons."""

    def __init__(self, window):
        super().__init__()
        self.setFixedSize(THUMB_W, TOP_H)
        self.setStyleSheet("background: #1d1d24;")
        self.pix = None
        self.btn_min = tool_button("minimize", "Minimize", 18, "#ffffff")
        self.btn_close = tool_button("close", "Close", 18, "#ffffff")
        for b in (self.btn_min, self.btn_close):
            b.setParent(self)
            b.setStyleSheet("QToolButton { background: rgba(0,0,0,90); border-radius: 3px; }"
                            "QToolButton:hover { background: rgba(0,0,0,160); }")
            b.hide()
        self.btn_min.move(THUMB_W - 62, 6)
        self.btn_close.move(THUMB_W - 32, 6)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_close.clicked.connect(window.close)

    def set_png(self, data):
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.pix = pm
        else:
            self.pix = None
        self.update()

    def show_buttons(self, on):
        self.btn_min.setVisible(on)
        self.btn_close.setVisible(on)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1d1d24"))
        if self.pix:
            scaled = self.pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            p.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
        else:
            p.setPen(QColor("#5c5c6a"))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(self.rect(), Qt.AlignCenter, APP_NAME)


class PlaylistDelegate(QStyledItemDelegate):
    def __init__(self, win):
        super().__init__()
        self.win = win

    ROW = 25

    def has_next_line(self, index):
        return bool(self.win.next_suggestion) and index.data(Qt.UserRole) == self.win.next_anchor

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW * (2 if self.has_next_line(index) else 1))

    def paint(self, p, option, index):
        path = index.data(Qt.UserRole)
        selected = bool(option.state & QStyle.State_Selected)
        # bold: the video playing, or when nothing plays, the one played last (like Airflow)
        playing = (path == self.win.now_path and self.win.player is not None) or \
            (self.win.player is None and path == self.win.state.get("last_played"))
        full = option.rect
        r = full.adjusted(0, 0, 0, -(full.height() - self.ROW))  # the video's own line
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if self.has_next_line(index):
            f = QFont("Segoe UI", 9)
            p.setFont(f)
            p.setPen(QColor("#9a9aa2"))
            line = QRectF(full.left() + 44, r.bottom() + 1, full.width() - 54, self.ROW)
            p.drawText(line, Qt.AlignVCenter | Qt.AlignLeft, QFontMetrics(f).elidedText(
                f"Possible Next: {Path(self.win.next_suggestion).name}", Qt.ElideRight, int(line.width())))
        if selected:
            p.fillRect(r, ACCENT)
        fg = QColor("#ffffff") if selected else QColor("#2a2a30")
        # watched-progress icon
        dur = self.win.state["durations"].get(path) or 0
        pos = self.win.state["resume"].get(path) or 0
        frac = max(0.0, min(1.0, pos / dur)) if dur else 0.0
        box = QRectF(r.left() + 8.5, r.center().y() - 4, 26, 8)
        line = QColor("#ffffff") if selected else QColor("#7d7d86")
        p.setPen(QPen(line, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 2, 2)
        if frac > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(line)
            p.drawRoundedRect(QRectF(box.left() + 2, box.top() + 2, (box.width() - 4) * frac, box.height() - 4), 1, 1)
        f = QFont("Segoe UI", 9)
        f.setBold(selected or playing)
        p.setFont(f)
        p.setPen(fg)
        dur_txt = be.fmt_short(dur) if dur else ""
        fm = QFontMetrics(f)
        dur_w = fm.horizontalAdvance(dur_txt) + 14 if dur_txt else 8
        name_rect = QRectF(r.left() + 44, r.top(), r.width() - 44 - dur_w, r.height())
        p.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(Path(path).name, Qt.ElideRight, int(name_rect.width())))
        if dur_txt:
            p.drawText(QRectF(r.right() - dur_w, r.top(), dur_w - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight, dur_txt)
        p.restore()


class PlaylistView(QListWidget):
    filesDropped = Signal(list, int)     # paths, row
    moveRequested = Signal(list, int)    # rows, target row
    subtitleDropped = Signal(str, int)   # subtitle file, row
    suggestionActivated = Signal()       # double-click on the "Possible Next" line

    def on_next_line(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid() or not self.itemDelegate().has_next_line(idx):
            return False
        return pos.y() > self.visualRect(idx).top() + PlaylistDelegate.ROW

    def mouseDoubleClickEvent(self, e):
        if self.on_next_line(e.position().toPoint()):
            e.accept()
            self.suggestionActivated.emit()
            return
        super().mouseDoubleClickEvent(e)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QListWidget {{ background: {LIST_BG}; outline: 0; }}")

    def _external(self, e):
        return e.source() is None and e.mimeData().hasUrls()

    def dragEnterEvent(self, e):
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def _target_row(self, e):
        idx = self.indexAt(e.position().toPoint())
        if not idx.isValid():
            return self.count()
        rect = self.visualRect(idx)
        return idx.row() + (1 if e.position().y() > rect.center().y() else 0)

    def dropEvent(self, e):
        if e.source() is self:
            rows = sorted({i.row() for i in self.selectedIndexes()})
            target = self._target_row(e)
            e.setDropAction(Qt.IgnoreAction)  # the window moves the items itself
            e.accept()
            self.moveRequested.emit(rows, target)
            return
        if e.mimeData().hasUrls():
            paths = [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
            subs = [p for p in paths if Path(p).suffix.lower() in be.SUB_EXTS]
            idx = self.indexAt(e.position().toPoint())
            if subs and idx.isValid():
                self.subtitleDropped.emit(subs[0], idx.row())
            vids = [p for p in paths if p not in subs]
            if vids:
                self.filesDropped.emit(vids, self._target_row(e))
            e.acceptProposedAction()

    empty = None  # the EmptyState shown over the list while it has no videos

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.empty is not None:
            self.empty.setGeometry(self.viewport().rect())

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0 and self.empty is None:
            p = QPainter(self.viewport())
            p.setPen(QColor("#8a8a92"))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       "Drop videos or folders here\nor right-click to add files")


class EmptyState(QWidget):
    """What an empty playlist shows: the three things Video Caster puts on the TV. Dropped
    files still reach the playlist (this widget doesn't take drops), right-click still gives
    the playlist's menu."""

    def __init__(self, view, win):
        super().__init__(view.viewport())
        self.view = view
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(10)
        lay.addStretch(1)
        head = QLabel("What would you like on the TV?")
        head.setStyleSheet("font-size: 13px; font-weight: bold; color: #3a3a42; background: transparent;")
        lay.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.play = ChoiceCard("play", "Play videos", "Drop them here")
        self.mirror = ChoiceCard("screen", "Mirror my screen", "Show what you see")
        self.extend = ChoiceCard("screens", "Second display", "Work here, show there")
        self.play.setToolTip("Add videos or folders, then double-click one to play it on the TV")
        self.mirror.setToolTip("The TV shows your screen as you see it, with the PC's sound")
        self.extend.setToolTip("An extra screen next to yours, on the TV: drag windows onto it")
        for c in (self.play, self.mirror, self.extend):
            c.setCheckable(False)
            c.setMinimumWidth(96)
            row.addWidget(c)
        lay.addLayout(row)
        hint = QLabel("Drop videos and folders anywhere here. Right-click for more.")
        hint.setStyleSheet("font-size: 11px; color: #85858d; background: transparent;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(2)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: view.customContextMenuRequested.emit(self.mapTo(view.viewport(), pos)))
        self.play.clicked.connect(win.add_files_dialog)
        self.mirror.clicked.connect(lambda: win.share_panel.open_at(win.btn_screen, "mirror"))
        self.extend.clicked.connect(lambda: win.share_panel.open_at(win.btn_screen, "extend"))


class DeviceRow(QWidget):
    def __init__(self, device, selected, on_click):
        super().__init__()
        self.device = device
        self.selected = selected
        self.on_click = on_click
        self.setFixedHeight(34)
        self.setMinimumWidth(230)
        self.setToolTip(device.describe())
        self.hover = False
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.on_click(self.device)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hover:
            p.fillRect(self.rect(), QColor("#f0eaf5"))
        p.setPen(QColor("#e6e6e9"))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        f = QFont("Segoe UI", 9)
        f.setBold(self.selected)
        p.setFont(f)
        p.setPen(QColor("#222") if self.device.online else QColor("#9a9aa2"))
        p.drawText(QRectF(16, 0, self.width() - 50, self.height()), Qt.AlignVCenter, self.device.name)
        c = QPointF(self.width() - 22, self.height() / 2)
        if self.device.online:
            p.setPen(QPen(QColor("#3fbf55"), 1))
            p.setBrush(QColor("#4cd964"))
        else:
            p.setPen(QPen(QColor("#9a9aa2"), 1.2))
            p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, 5, 5)


class HelpButton(QToolButton):
    def __init__(self, text):
        super().__init__()
        self.setText("?")
        self.setToolTip(text)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.WhatsThisCursor)
        self.setStyleSheet("QToolButton { border: 1px solid #b9b9c0; border-radius: 10px; color: #8a8a92;"
                           " background: white; font-size: 11px; }")
        # a tooltip, not a dialog: a dialog would close the settings popup
        self.clicked.connect(lambda: QToolTip.showText(QCursor.pos(), text, self))


# --------------------------------------------------------------------------- connected-TV panel

class DevicePanel(QFrame):
    """The TV button's panel while connected: receiver, mute, volume, Disconnect, Speed Test."""

    def __init__(self, win):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.win = win
        self.player = None
        self.loading = False
        self.setObjectName("devpanel")
        self.setFixedWidth(208)
        self.setStyleSheet(f"""
            #devpanel {{ background: white; border: 1px solid #b8b8c0; }}
            QLabel {{ font-size: 12px; color: #222; }}
            QPushButton {{ min-height: 24px; padding: 2px 10px; border: 1px solid #3a3a42; background: white;
                          font-size: 12px; font-weight: bold; color: #222; }}
            QPushButton:hover {{ background: #f1eaf6; }}
            QSlider::groove:horizontal {{ height: 3px; background: #c9c9ce; }}
            QSlider::sub-page:horizontal {{ background: {ACCENT.name()}; }}
            QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -7px 0; border-radius: 8px;
                                          background: {ACCENT.name()}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(8)
        head = QWidget()
        head.setStyleSheet(f"background: {ACCENT.name()};")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 8, 12, 8)
        self.name = QLabel()
        self.name.setStyleSheet("color: white; font-weight: bold; background: transparent;")
        dot = QPixmap(12, 12)
        dot.fill(Qt.transparent)
        dp = QPainter(dot)
        dp.setRenderHint(QPainter.Antialiasing)
        dp.setPen(QPen(QColor("#2fae47"), 1))
        dp.setBrush(QColor("#4cd964"))
        dp.drawEllipse(QRectF(1, 1, 10, 10))
        dp.end()
        self.dot = QLabel()
        self.dot.setPixmap(dot)
        self.dot.setStyleSheet("background: transparent;")
        hl.addWidget(self.name, 1)
        hl.addWidget(self.dot)
        lay.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(12, 2, 12, 0)
        body.setSpacing(8)
        self.receiver = QLabel()
        body.addWidget(self.receiver)
        vol = QHBoxLayout()
        self.mute = QToolButton()
        self.mute.setIconSize(QSize(20, 20))
        self.mute.setFixedSize(30, 24)
        self.mute.setCheckable(True)
        self.mute.setToolTip("Mute the TV")
        self.mute.setStyleSheet("QToolButton { border: 1px solid #c8c8cf; background: #f4f4f6; }")
        self.mute.toggled.connect(self._mute)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setToolTip("TV volume")
        self.slider.valueChanged.connect(lambda v: self.vol_timer.start())
        self.vol_timer = QTimer(self, singleShot=True, interval=150, timeout=self._volume)
        vol.addWidget(self.mute)
        vol.addWidget(self.slider, 1)
        body.addLayout(vol)
        btns = QHBoxLayout()
        b1, b2 = QPushButton("Disconnect"), QPushButton("Speed Test")
        b1.clicked.connect(lambda: (self.hide(), self.win.disconnect_device()))
        b2.clicked.connect(lambda: (self.hide(), self.win.run_speed_test()))
        btns.addWidget(b1)
        btns.addWidget(b2)
        body.addLayout(btns)
        lay.addLayout(body)

    def open_for(self, player):
        self.player = player
        self.loading = True
        self.name.setText(player.device.name)
        self.receiver.setText(player.receiver_name())
        v = player.volume()
        self.slider.setEnabled(v is not None)
        self.slider.setValue(round((v or 0) * 100))
        self.mute.setChecked(player.muted())
        self.mute.setIcon(draw_icon("speaker-off" if player.muted() else "speaker", ACCENT, 20))
        self.loading = False

    def _mute(self, on):
        self.mute.setIcon(draw_icon("speaker-off" if on else "speaker", ACCENT, 20))
        if not self.loading and self.player:
            worker(MainWindow._safe, self.player.set_muted, on)

    def _volume(self):
        if not self.loading and self.player:
            worker(MainWindow._safe, self.player.set_volume, self.slider.value() / 100.0)


# --------------------------------------------------------------------------- sharing the screen

class ToggleSwitch(QAbstractButton):
    """A small on/off switch."""

    def __init__(self, tip=""):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(36, 20)
        self.setToolTip(tip)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush((ACCENT if on else QColor("#c4c4cb")) if self.isEnabled() else QColor("#e2e2e6"))
        p.drawRoundedRect(QRectF(0, 2, 36, 16), 8, 8)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(19 if on else 3, 4, 12, 12))


class ChoiceCard(QAbstractButton):
    """One of the share panel's two big choices: an icon, a title and one line under it."""

    def __init__(self, icon, title, line):
        super().__init__()
        self.icon_name, self.title, self.line = icon, title, line
        self.setText(title)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover)
        self.setFixedHeight(88)
        self.setMinimumWidth(160)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        p.setPen(QPen(ACCENT if on else QColor("#d4d4da"), 2 if on else 1))
        p.setBrush(QColor("#f7f1fb") if on else QColor("#fafafb") if self.underMouse() else QColor("white"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        pm = _icon_pixmap(self.icon_name, ACCENT if on else QColor("#8a8a92"), 26)
        p.drawPixmap(QRectF(12, 11, 26, 26), pm, QRectF(pm.rect()))
        f = QFont("Segoe UI", 10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#222"))
        p.drawText(QRectF(12, 42, self.width() - 20, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        f = QFont("Segoe UI", 9)
        p.setFont(f)
        p.setPen(QColor("#6b6b73"))
        p.drawText(QRectF(12, 62, self.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(self.line, Qt.ElideRight, self.width() - 22))


class SharePanel(QFrame):
    """The screen button's panel: mirror this PC's screen or use the TV as a second display,
    which screen, sound and delay - then Start sharing (or Switch / Stop while it's on)."""

    def __init__(self, win):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.win = win
        self.loading = False
        self.muted = False
        self.screen_list = []
        self.setObjectName("sharepanel")
        self.setFixedWidth(392)
        self.setStyleSheet(f"""
            #sharepanel {{ background: white; border: 1px solid #b8b8c0; }}
            QLabel {{ font-size: 12px; color: #222; background: transparent; }}
            QLabel#hint, QLabel#section {{ font-size: 11px; color: #75757d; }}
            QFrame#sep {{ background: #e8e8eb; border: none; }}
            QPushButton {{ min-height: 26px; padding: 2px 14px; border: 1px solid #b8b8c0; border-radius: 4px;
                          background: white; font-size: 12px; color: #222; }}
            QPushButton:hover {{ background: #f4eef8; }}
            QPushButton#start {{ background: {ACCENT.name()}; border: 1px solid {ACCENT.name()}; color: white;
                                font-weight: bold; }}
            QPushButton#start:hover {{ background: {ACCENT_DARK.name()}; }}
            QPushButton#stop {{ color: #b3261e; border-color: #e3b0ab; }}
            QPushButton#stop:hover {{ background: #fbeeec; }}
            QPushButton#screen {{ padding: 2px 10px; font-size: 11px; }}
            QPushButton#screen:checked {{ border: 2px solid {ACCENT.name()}; color: {ACCENT_DARK.name()};
                                         background: #f7f1fb; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)
        head = QWidget()
        head.setStyleSheet(f"background: {ACCENT.name()};")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(14, 9, 14, 9)
        hl.setSpacing(1)
        heading = QLabel("Show your screen on the TV")
        heading.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        self.tv = QLabel()
        self.tv.setStyleSheet("color: #f3e9f9; font-size: 11px;")
        hl.addWidget(heading)
        hl.addWidget(self.tv)
        lay.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 0)
        body.setSpacing(8)
        cards = QHBoxLayout()
        cards.setSpacing(8)
        self.mirror = ChoiceCard("screen", "Mirror my screen", "The TV shows what you see")
        self.extend = ChoiceCard("screens", "Second display", "Drag windows onto the TV")
        self.modes = QButtonGroup(self)
        for c in (self.mirror, self.extend):
            self.modes.addButton(c)
            cards.addWidget(c)
            c.toggled.connect(lambda on: on and self._refresh())
        body.addLayout(cards)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        body.addWidget(self.info)
        self.which = QLabel("Which screen")
        self.which.setObjectName("section")
        body.addWidget(self.which)
        self.screens_box = QWidget()
        self.screens_row = QHBoxLayout(self.screens_box)
        self.screens_row.setContentsMargins(0, 0, 0, 0)
        self.screens_row.setSpacing(6)
        self.screen_buttons = QButtonGroup(self)
        self.screen_buttons.buttonToggled.connect(lambda b, on: on and self._refresh())
        body.addWidget(self.screens_box)
        self.sound, self.sound_hint = self._option(body, "speaker", "PC sound on the TV")
        self.low, self.low_hint = self._option(body, "bolt", "Low delay")
        self.sound.toggled.connect(self._sound)
        self.low.toggled.connect(self._low)
        btns = QHBoxLayout()
        btns.setContentsMargins(0, 6, 0, 0)
        btns.setSpacing(8)
        self.stop = QPushButton("Stop sharing")
        self.stop.setObjectName("stop")
        self.close_btn = QPushButton("Cancel")
        self.start = QPushButton("Start sharing")
        self.start.setObjectName("start")
        btns.addWidget(self.stop)
        btns.addStretch()
        btns.addWidget(self.close_btn)
        btns.addWidget(self.start)
        body.addLayout(btns)
        lay.addLayout(body)
        self.stop.clicked.connect(lambda: (self.hide(), self.win.end_screen(stop_tv=True)))
        self.close_btn.clicked.connect(self.hide)
        self.start.clicked.connect(self._start)

    def _option(self, body, icon, title):
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFixedHeight(1)
        body.addWidget(sep)
        row = QHBoxLayout()
        row.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(draw_icon(icon, QColor("#8a8a92"), 18).pixmap(18, 18))
        ic.setFixedWidth(20)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(QLabel(title))
        hint = QLabel()
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        texts.addWidget(hint)
        switch = ToggleSwitch(title)
        row.addWidget(ic, 0, Qt.AlignTop)
        row.addLayout(texts, 1)
        row.addWidget(switch, 0, Qt.AlignVCenter)
        body.addLayout(row)
        return switch, hint

    # ----- opening
    def open_at(self, button, mode=None):
        """Open under `button`; mode 'mirror' or 'extend' picks that choice (else: what's on now)."""
        w = self.win
        self.loading = True
        dev = w.current_device()
        self.tv.setText(f"to {dev.name}" if dev else "No TV chosen yet")
        s = w.screen
        # the screens to mirror: every screen but the TV display ('Second display' is that one)
        tv_rect = w._tv_display_rect()
        screens = QGuiApplication.screens()
        self.screen_list = [(i, sc) for i, sc in enumerate(screens) if not (tv_rect and w._screen_rect(sc) == tv_rect)]
        for b in list(self.screen_buttons.buttons()):
            self.screen_buttons.removeButton(b)
            b.deleteLater()
        current = s["index"] if s is not None and not s.get("tv") else screens.index(QGuiApplication.primaryScreen())
        for i, sc in self.screen_list:
            x, y, sw, sh = w._screen_rect(sc)
            b = QPushButton(f"Screen {i + 1}  ·  {sw} × {sh}")
            b.setObjectName("screen")
            b.setCheckable(True)
            b.setProperty("qt_index", i)
            b.setToolTip("Your main screen" if sc is QGuiApplication.primaryScreen() else "")
            self.screen_buttons.addButton(b)
            self.screens_row.addWidget(b)
            b.setChecked(i == current)
        self.screens_row.addStretch()
        if not self.screen_buttons.checkedButton() and self.screen_buttons.buttons():
            self.screen_buttons.buttons()[0].setChecked(True)
        extend = mode == "extend" if mode else bool(s is not None and s.get("tv"))
        (self.extend if extend else self.mirror).setChecked(True)
        g = w.state["global"]
        self.sound.setChecked(bool(g.get("screen_sound", True)))
        self.low.setChecked(bool(g.get("screen_mirror", True)))
        self.low.setEnabled(dev is None or dev.kind == "chromecast")
        try:
            self.muted = bool((be.speaker_state() or (False,))[0])
        except Exception:
            self.muted = False
        self.loading = False
        self._refresh()
        self.adjustSize()
        pos = button.mapToGlobal(QPoint(button.width() // 2 - self.width() // 2, button.height()))
        area = (button.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        pos.setX(max(area.left(), min(pos.x(), area.right() - self.width())))
        self.move(pos)
        self.show()

    def _chosen(self):
        """('extend',) or ('mirror', Qt screen index) as picked in the panel."""
        if self.extend.isChecked():
            return ("extend",)
        b = self.screen_buttons.checkedButton()
        return ("mirror", int(b.property("qt_index")) if b is not None else 0)

    def _current(self):
        s = self.win.screen
        if s is None:
            return None
        return ("extend",) if s.get("tv") else ("mirror", s["index"])

    def _refresh(self):
        if self.loading:
            return
        w = self.win
        extend = self.extend.isChecked()
        self.which.setVisible(not extend and len(self.screen_list) > 1)
        self.screens_box.setVisible(not extend and len(self.screen_list) > 1)
        if extend:
            first = be.virtual_display() is None
            self.info.setText("An extra screen appears to the right of yours; what you put there shows on the TV."
                              + (" The first time, Windows asks to install a display driver for it." if first else ""))
        self.info.setVisible(extend)
        if not self.sound.isChecked():
            self.sound_hint.setText("The TV shows the picture only")
        elif self.muted:
            self.sound_hint.setText("This PC is muted - unmute it to hear the sound on the TV")
        else:
            self.sound_hint.setText("A low PC volume is fine: the TV gets full strength")
        self.sound_hint.setStyleSheet("color: #b3261e;" if self.sound.isChecked() and self.muted else "")
        if not self.low.isEnabled():
            self.low_hint.setText("An Apple TV shows the screen a few seconds late")
        elif self.low.isChecked():
            self.low_hint.setText(f"About {be.MIRROR_DELAY_MS / 1000:.1f} s behind the PC")
        else:
            self.low_hint.setText("About 6 s behind - steadier on weak Wi-Fi")
        current, chosen = self._current(), self._chosen()
        sharing = current is not None
        self.stop.setVisible(sharing)
        self.close_btn.setText("Close" if sharing else "Cancel")
        if w.current_device() is None:
            self.start.setText("Choose a TV")
            self.start.setVisible(True)
        else:
            self.start.setText("Switch" if sharing else "Start sharing")
            self.start.setVisible(not sharing or chosen != current)
        self.adjustSize()

    # ----- actions
    def _sound(self, on):
        if not self.loading:
            self.win._set_screen_sound(on)  # (casts again with the new choice while sharing)
            self._refresh()

    def _low(self, on):
        if not self.loading:
            self.win._set_screen_mirror(on)
            self._refresh()

    def _start(self):
        w = self.win
        chosen = self._chosen()
        self.hide()
        if w.current_device() is None:
            w.show_devices()
            return
        if chosen[0] == "extend":
            w.cast_tv_display()
            return
        if w.tv_display is not None:  # back from the second display to mirroring: switch it off
            w._tv_display_off()
        w.cast_screen(chosen[1])


# --------------------------------------------------------------------------- settings panel

class SettingsPanel(QFrame):
    """Per-video audio/subtitle/picture options and app-wide conversion options."""

    def __init__(self, win):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.win = win
        self.path = None
        self.loading = False
        self.setFixedWidth(540)
        self.setObjectName("panel")
        self.setStyleSheet("""
            #panel { background: white; border: 1px solid #b8b8c0; }
            QLabel { color: #333; font-size: 12px; }
            QLabel[bold="true"] { font-weight: bold; color: #111; }
            QComboBox { min-height: 22px; padding: 1px 6px; border: 1px solid #c4c4cc; border-radius: 2px;
                        background: #f4f4f6; font-size: 12px; }
            QComboBox:disabled { color: #aaa; }
            QCheckBox { font-size: 12px; color: #222; }
            QPushButton { min-height: 24px; padding: 2px 12px; border: 1px solid #b8b8c0; background: #f4f4f6;
                          font-size: 12px; }
            QPushButton:hover { background: #ebe3f1; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title = QLabel()
        self.title.setStyleSheet(f"background: {ACCENT.name()}; color: white; padding: 9px 12px; font-size: 12px;")
        outer.addWidget(self.title)

        body = QHBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(14)
        left, right = QGridLayout(), QGridLayout()
        for g in (left, right):
            g.setHorizontalSpacing(8)
            g.setVerticalSpacing(7)
        body.addLayout(left, 11)
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setStyleSheet("color: #e2e2e6;")
        body.addWidget(vline)
        body.addLayout(right, 10)
        outer.addLayout(body)

        def label(text, bold=False):
            lb = QLabel(text)
            if bold:
                lb.setProperty("bold", "true")
            return lb

        def hline(color="#e2e2e6"):
            ln = QFrame()
            ln.setFixedHeight(1)
            ln.setStyleSheet(f"background: {color};")
            return ln

        def combo(items, key, scope="file"):
            cb = QComboBox()
            for text, value in items:
                cb.addItem(text, value)
            cb.currentIndexChanged.connect(lambda _=0, c=cb, k=key, s=scope: self._changed(k, c.currentData(), s))
            return cb

        # ---- left: audio
        self.audio = combo([], "audio_track")
        left.addWidget(label("Audio", True), 0, 0)
        left.addWidget(self.audio, 0, 1, 1, 2)
        left.addWidget(hline(), 1, 0, 1, 3)
        self.surround = combo([("Stereo Downmix", "stereo"), ("Surround (AAC 5.1)", "surround"),
                               ("Passthrough (Dolby)", "passthrough")], "surround", scope="global")
        left.addWidget(label("Surround"), 2, 0)
        left.addWidget(self.surround, 2, 1)
        left.addWidget(HelpButton(
            "For all videos. Stereo Downmix: plays everywhere. Surround: 5.1 the TV decodes itself. "
            "Passthrough: Dolby Digital and Dolby Digital Plus (Atmos included) go to the TV untouched, for a "
            "soundbar or receiver; other surround (DTS, TrueHD, AAC 5.1) is sent as Dolby Digital 5.1. "
            "If you hear no sound with Passthrough, go back to Stereo Downmix."), 2, 2)
        self.volume = combo([("Normal", "normal"), ("Boost (+6 dB)", "boost"), ("Normalize", "normalize")], "volume")
        left.addWidget(label("Volume"), 3, 0)
        left.addWidget(self.volume, 3, 1)
        left.addWidget(HelpButton("Boost makes quiet videos louder. Normalize evens out loud and quiet scenes "
                                  "(handy at night). Both convert the audio, not the video."), 3, 2)
        delays = [(f"{d / 100:+.2f}s".replace("+0.00", "0.00"), d / 100) for d in range(-200, 201, 10)]
        self.adelay = combo(delays, "audio_delay")
        left.addWidget(label("Delay"), 4, 0)
        left.addWidget(self.adelay, 4, 1)
        left.addWidget(hline(ACCENT.name()), 5, 0, 1, 3)
        # ---- left: subtitles
        self.subs = QComboBox()
        self.subs.currentIndexChanged.connect(self._sub_chosen)
        left.addWidget(label("Subtitles", True), 6, 0)
        left.addWidget(self.subs, 6, 1, 1, 2)
        self.enc_btn = QPushButton("Change...")
        self.enc_btn.clicked.connect(self._change_encoding)
        left.addWidget(label("Encoding"), 7, 0)
        left.addWidget(self.enc_btn, 7, 1, Qt.AlignLeft)
        self.render = combo([("Soft Subtitles", "soft"), ("Burned In", "burn")], "sub_render")
        left.addWidget(label("Rendering"), 8, 0)
        left.addWidget(self.render, 8, 1)
        left.addWidget(HelpButton("Soft subtitles are drawn by the TV and cost nothing. Burned in draws them into "
                                  "the picture: works everywhere, but the video has to be converted."), 8, 2)
        self.size = combo([(f"{s}%", s) for s in (50, 75, 100, 125, 150, 175, 200)], "sub_size")
        left.addWidget(label("Size"), 9, 0)
        left.addWidget(self.size, 9, 1)
        self.color = combo([(c, c) for c in be.SUB_COLORS], "sub_color")
        left.addWidget(label("Color"), 10, 0)
        left.addWidget(self.color, 10, 1)
        self.font_box = combo([(f, f) for f in be.SUB_FONTS], "sub_font", scope="global")
        left.addWidget(label("Font"), 11, 0)
        left.addWidget(self.font_box, 11, 1)
        left.addWidget(HelpButton("The subtitle font, for all videos. These are the font styles every "
                                  "Chromecast has; burned-in subtitles use a matching Windows font. "
                                  "Changes show on the TV straight away."), 11, 2)
        self.font_style_box = combo([(s, s) for s in be.SUB_FONT_STYLES], "sub_font_style", scope="global")
        left.addWidget(label("Style"), 12, 0)
        left.addWidget(self.font_style_box, 12, 1)
        sd = QHBoxLayout()
        sd.setSpacing(4)
        self.sd_minus, self.sd_plus = QPushButton("-"), QPushButton("+")
        for b in (self.sd_minus, self.sd_plus):
            b.setFixedWidth(28)
            b.setStyleSheet("padding: 0;")
        self.sd_label = QLabel("0.00s")
        self.sd_minus.clicked.connect(lambda: self._nudge_sub_delay(-0.1))
        self.sd_plus.clicked.connect(lambda: self._nudge_sub_delay(0.1))
        sd.addWidget(self.sd_minus)
        sd.addWidget(self.sd_plus)
        sd.addWidget(self.sd_label)
        sd.addStretch()
        left.addWidget(label("Delay"), 13, 0)
        left.addLayout(sd, 13, 1)
        left.setColumnStretch(1, 1)

        # ---- right: picture and conversion
        self.deint = combo([("None", "none"), ("On (Yadif)", "yadif")], "deinterlace")
        right.addWidget(label("Deinterlace"), 0, 0)
        right.addWidget(self.deint, 0, 1, 1, 2)
        self.aspect = combo([("Default", "default"), ("16:9", "16:9"), ("4:3", "4:3"), ("2.35:1", "2.35:1"),
                             ("1.85:1", "1.85:1"), ("1:1", "1:1")], "aspect")
        right.addWidget(label("Aspect"), 1, 0)
        right.addWidget(self.aspect, 1, 1, 1, 2)
        right.addWidget(hline(), 2, 0, 1, 3)
        self.quality = combo([("Original", "original"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")],
                             "quality")
        right.addWidget(label("Quality"), 3, 0)
        right.addWidget(self.quality, 3, 1)
        right.addWidget(HelpButton("Picture size when the video is converted (Original keeps it, up to 1080p). "
                                   "Only used while converting: lower it if playback stutters."), 3, 2)
        self.force = QCheckBox("Force Conversion")
        self.force.toggled.connect(lambda v: self._changed("force_convert", v, "file"))
        right.addWidget(self.force, 4, 1, 1, 2)
        right.addWidget(hline(), 5, 0, 1, 3)
        self.acc_dec, self.acc_enc, self.acc_scrub = QCheckBox("Decoding"), QCheckBox("Encoding"), QCheckBox("Scrubbing")
        for cb, key in ((self.acc_dec, "accel_decode"), (self.acc_enc, "accel_encode"), (self.acc_scrub, "scrubbing")):
            cb.toggled.connect(lambda v, k=key: self._changed(k, v, "global"))
        right.addWidget(label("Accelerate"), 6, 0)
        right.addWidget(self.acc_dec, 6, 1)
        right.addWidget(self.acc_enc, 7, 1)
        right.addWidget(HelpButton("Decoding and Encoding use the graphics chip (Intel Quick Sync on this PC) when "
                                   "converting, so the processor stays cool. Scrubbing shows frame previews while "
                                   "you drag the seek bar."), 7, 2)
        right.addWidget(self.acc_scrub, 8, 1)
        right.addWidget(hline(), 9, 0, 1, 3)
        self.hevc = QCheckBox("Native Playback")
        self.hevc.toggled.connect(lambda v: self._changed("hevc_native", v, "global"))
        right.addWidget(label("H.265 (HEVC)"), 10, 0)
        right.addWidget(self.hevc, 10, 1)
        right.addWidget(HelpButton("Send H.265 video to the TV without converting it. Turn this on if your TV plays "
                                   "H.265 itself; if those videos then stay black, turn it off again."), 10, 2)
        self.up_next = QCheckBox("Up next at the credits")
        self.up_next.toggled.connect(lambda v: self._changed("up_next", v, "global"))
        right.addWidget(label("Episodes"), 11, 0)
        right.addWidget(self.up_next, 11, 1)
        right.addWidget(HelpButton("When the end credits start (found from the picture), a 10-second countdown "
                                   "starts the next video in the playlist or the next episode. Cancel it in the "
                                   "window, or pause with the TV remote."), 11, 2)
        self.skip_intro = QCheckBox("Skip intros")
        self.skip_intro.toggled.connect(lambda v: self._changed("skip_intro", v, "global"))
        right.addWidget(self.skip_intro, 12, 1)
        right.addWidget(HelpButton("A series' opening titles are found by comparing the sound of two episodes in "
                                   "the same folder. When they start, a 5-second countdown skips them. Watch them "
                                   "anyway: click 'Watch intro' in the window, or pause with the TV remote."), 12, 2)
        right.setRowStretch(13, 1)
        btns = QHBoxLayout()
        about = QPushButton(f"About {APP_NAME}")
        about.clicked.connect(self.win.show_about)
        trouble = QPushButton("Troubleshooting")
        trouble.clicked.connect(self.win.show_troubleshooting)
        btns.addWidget(about)
        btns.addWidget(trouble)
        right.addLayout(btns, 14, 0, 1, 3)
        right.setColumnStretch(1, 1)

        # ---- footer
        foot = QFrame()
        foot.setStyleSheet("background: #e8f0fb; border-top: 1px solid #d5e2f3;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(12, 8, 12, 8)
        self.foot_icon = QLabel()
        self.foot_icon.setFixedSize(34, 34)
        fl.addWidget(self.foot_icon)
        tl = QVBoxLayout()
        tl.setSpacing(1)
        self.foot_head = QLabel()
        self.foot_head.setStyleSheet("font-weight: bold; color: #111; background: transparent; border: none;")
        self.foot_text = QLabel()
        self.foot_text.setWordWrap(True)
        self.foot_text.setStyleSheet("color: #333; background: transparent; border: none;")
        tl.addWidget(self.foot_head)
        tl.addWidget(self.foot_text)
        fl.addLayout(tl, 1)
        outer.addWidget(foot)

    # ----- filling in
    def open_for(self, path):
        self.path = path
        self.loading = True
        try:
            fs = self.win.file_settings(path)
            gs = self.win.state["global"]
            info = be.probe(path) if path else None
            self.title.setText(QFontMetrics(self.title.font()).elidedText(
                Path(path).name if path else "No video selected", Qt.ElideMiddle, 500))
            self.audio.clear()
            for i, text in enumerate(be.audio_track_labels(info)):
                self.audio.addItem(text, i)
            self._select(self.audio, fs["audio_track"])
            self._select(self.surround, gs.get("surround", "stereo"))
            self._select(self.volume, fs["volume"])
            self._select(self.adelay, round(float(fs["audio_delay"]), 1))
            self.subs.clear()
            choices = be.subtitle_choices(path, info) if path else [("none", "None")]
            current = be.resolve_subtitle(path, info, fs, gs)["key"] if path else "none"
            if path:
                worker(be.prefetch_subtitles, path, info)  # switching between them is then quick
            if current not in [k for k, _ in choices] and current.startswith("ext:"):  # loaded from elsewhere
                p = Path(current[4:])
                choices.append((current, f"{p.stem} ({p.suffix[1:].lower()})"))
            for key, text in choices:
                self.subs.addItem(text, key)
            self.subs.addItem("Load subtitle file...", "__load__")
            self.subs.addItem("Search online...", "__search__")
            self._select(self.subs, current)
            self._select(self.render, fs["sub_render"])
            self._select(self.size, int(fs["sub_size"]))
            self._select(self.color, fs["sub_color"])
            self._select(self.font_box, gs.get("sub_font", "Sans-serif"))
            self._select(self.font_style_box, gs.get("sub_font_style", "Normal"))
            self.sd_label.setText(f"{float(fs['sub_delay']):.2f}s")
            self._select(self.deint, fs["deinterlace"])
            self._select(self.aspect, fs["aspect"])
            self._select(self.quality, str(fs["quality"]))
            self.force.setChecked(bool(fs["force_convert"]))
            self.acc_dec.setChecked(bool(gs["accel_decode"]))
            self.acc_enc.setChecked(bool(gs["accel_encode"]))
            self.acc_scrub.setChecked(bool(gs["scrubbing"]))
            self.hevc.setChecked(bool(gs["hevc_native"]))
            self.up_next.setChecked(bool(gs.get("up_next", True)))
            self.skip_intro.setChecked(bool(gs.get("skip_intro", True)))
            self._enable(bool(path))
        finally:
            self.loading = False
        self.refresh_footer()

    def _enable(self, on):
        for w in (self.audio, self.surround, self.volume, self.adelay, self.subs, self.enc_btn, self.render, self.size,
                  self.color, self.font_box, self.font_style_box, self.sd_minus, self.sd_plus, self.deint, self.aspect,
                  self.force):
            w.setEnabled(on)

    @staticmethod
    def _select(cb, value):
        for i in range(cb.count()):
            d = cb.itemData(i)
            if d == value or (isinstance(d, float) and isinstance(value, (int, float)) and abs(d - value) < 1e-6):
                cb.setCurrentIndex(i)
                return
        if cb.count():
            cb.setCurrentIndex(0)

    def refresh_footer(self):
        if not self.path:
            self.foot_icon.setPixmap(draw_icon("check", "#b0b0b8").pixmap(34, 34))
            self.foot_head.setText("No video selected")
            self.foot_text.setText("Select a video in the playlist to see and change its settings.")
            self.quality.setEnabled(False)
            return
        plan = be.plan_stream(self.path, be.probe(self.path), self.win.file_settings(self.path),
                              self.win.state["global"], self.win.encoder)
        convert = plan["mode"] == "transcode"
        if plan["sub"]["kind"] == "emb" and not plan["sub"]["text"]:
            plan["detail"] += " Picture subtitles can only be shown burned in."
        self.foot_icon.setPixmap(draw_icon("convert" if convert else "check", ACCENT).pixmap(34, 34))
        self.foot_head.setText(plan["headline"])
        self.foot_text.setText(plan["detail"])
        self.quality.setEnabled(convert)

    # ----- changes
    def _changed(self, key, value, scope):
        if self.loading:
            return
        if scope == "global":
            self.win.state["global"][key] = value
            self.win.settings_changed(None, key)
        elif self.path:
            self.win.set_file_setting(self.path, key, value)
        self.refresh_footer()

    def _sub_chosen(self, _=0):
        if self.loading or not self.path:
            return
        key = self.subs.currentData()
        if key == "__load__":
            path = self.path
            self.hide()  # the file dialog would close this popup anyway
            f, _filter = QFileDialog.getOpenFileName(self.win, "Load subtitles", str(Path(path).parent),
                                                     "Subtitles (*.srt *.vtt)")
            if f:
                self.win.set_file_setting(path, "subtitle", f"ext:{os.path.normpath(f)}")
            self.win.show_settings()
            return
        if key == "__search__":
            path = self.path
            self.hide()
            self.win.search_subtitles(path)
            return
        # remember the language, so the next episodes get the same subtitles
        pref = be.subtitle_language(self.path, be.probe(self.path), key)
        if pref:
            self.win.state["global"]["sub_pref"] = list(pref)
        self.win.set_file_setting(self.path, "subtitle", key)
        self.refresh_footer()

    def _change_encoding(self):
        if not self.path:
            return
        path = self.path
        names = [label for _, label in be.SUB_ENCODINGS]
        cur = self.win.file_settings(path)["sub_encoding"]
        idx = next((i for i, (k, _) in enumerate(be.SUB_ENCODINGS) if k == cur), 0)
        self.hide()
        choice, ok = QInputDialog.getItem(self.win, "Subtitle encoding",
                                          "Character set of the subtitle file (if letters look wrong):",
                                          names, idx, False)
        if ok:
            key = be.SUB_ENCODINGS[names.index(choice)][0]
            self.win.set_file_setting(path, "sub_encoding", key)
        self.win.show_settings()

    def _nudge_sub_delay(self, d):
        if not self.path:
            return
        v = round(float(self.win.file_settings(self.path)["sub_delay"]) + d, 2)
        self.sd_label.setText(f"{v:.2f}s")
        self.win.set_file_setting(self.path, "sub_delay", v)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.win.btn_gear.setDown(False)


# --------------------------------------------------------------------------- main window

class SubtitleSearchDialog(QDialog):
    """Find subtitles for a video online: OpenSubtitles through Stremio's free add-on (no
    account), plus the OpenSubtitles API itself for viewers who saved their own key. By the
    file's fingerprint (exact matches for this very release) and its name; the chosen one is
    downloaded next to the video and used right away."""

    def __init__(self, win, path):
        super().__init__(win)
        self.win, self.path, self.results, self.closed = win, path, [], False
        self.setWindowTitle("Find subtitles online")
        self.setMinimumSize(620, 420)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{MainWindow._short_title(path)}</b><br><span style='color:#666'>Searches "
                      "OpenSubtitles by this file's fingerprint and name - no account needed.</span>")
        head.setTextFormat(Qt.RichText)
        lay.addWidget(head)

        # optional: the viewer's own OpenSubtitles API key, for the official API as well
        self.account = QFrame()
        self.account.setStyleSheet("QFrame { background: #f3eefa; border-radius: 4px; }")
        al = QGridLayout(self.account)
        info = QLabel("<b>Optional.</b> The search works without an account (through Stremio's free "
                      "OpenSubtitles service). With your own OpenSubtitles <b>API key</b> it also asks the official "
                      "API - more results, with download counts: sign up at "
                      "<a href='https://www.opensubtitles.com'>opensubtitles.com</a>, open "
                      "<a href='https://www.opensubtitles.com/consumers'>API consumers</a> in your profile and "
                      "create one. User name and password are optional too - logged in, you get more downloads per "
                      "day. They're kept in this app's settings, encrypted for your Windows account. Empty the key "
                      "and Save to stop using it.")
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setTextFormat(Qt.RichText)
        al.addWidget(info, 0, 0, 1, 2)
        saved = self.win.state.get("opensubtitles") or {}
        self.key_edit = QLineEdit(be.unprotect(saved.get("api_key", "")))
        self.key_edit.setPlaceholderText("API key")
        self.user_edit = QLineEdit(saved.get("username", ""))
        self.user_edit.setPlaceholderText("optional")
        self.pass_edit = QLineEdit(be.unprotect(saved.get("password", "")))
        self.pass_edit.setPlaceholderText("optional")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        for row, (text, w) in enumerate((("API key", self.key_edit), ("User name", self.user_edit),
                                         ("Password", self.pass_edit)), 1):
            al.addWidget(QLabel(text), row, 0)
            al.addWidget(w, row, 1)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save_account)
        al.addWidget(self.save_btn, 4, 1, Qt.AlignRight)
        lay.addWidget(self.account)

        row = QHBoxLayout()
        row.addWidget(QLabel("Language"))
        self.lang = QComboBox()
        self.lang.addItems(list(be.OS_LANGS))
        self.lang.setCurrentText(be.os_language_for(self.win.state["global"].get("sub_pref")))
        row.addWidget(self.lang, 1)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.search)
        row.addWidget(self.search_btn)
        lay.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Release", "Downloads", "Notes"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        hv = self.tree.header()
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.download())
        lay.addWidget(self.tree, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        bb = QDialogButtonBox()
        self.get_btn = bb.addButton("Download && use", QDialogButtonBox.AcceptRole)
        self.get_btn.setEnabled(False)
        self.get_btn.clicked.connect(self.download)
        self.acct_btn = bb.addButton("Account...", QDialogButtonBox.ActionRole)
        self.acct_btn.clicked.connect(lambda: self.account.setVisible(not self.account.isVisible()))
        close = bb.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.reject)
        lay.addWidget(bb)

        self.account.hide()
        QTimer.singleShot(0, self.search)

    def done(self, r):
        self.closed = True
        super().done(r)

    def _client(self):
        if getattr(self.win, "os_client", None) is None:
            self.win.os_client = be.opensubtitles_from(self.win.state.get("opensubtitles"))
        return self.win.os_client

    def _save_account(self):
        key = self.key_edit.text().strip()
        if key:
            self.win.state["opensubtitles"] = {"api_key": be.protect(key), "username": self.user_edit.text().strip(),
                                               "password": be.protect(self.pass_edit.text())}
        else:  # no key: back to the free service only
            self.win.state.pop("opensubtitles", None)
        self.win.save()
        self.win.os_client = None  # a new client (and login) with these details
        self.account.hide()
        self.search()

    def _busy(self, on, text=""):
        for w in (self.search_btn, self.lang, self.acct_btn):
            w.setEnabled(not on)
        self.get_btn.setEnabled(not on and bool(self.tree.selectedItems()))
        if text:
            self.status.setText(text)

    def _later(self, fn):
        """Run fn on the window's thread, unless this window was closed meanwhile."""
        self.win.bridge.call.emit(lambda: None if self.closed else fn())

    def search(self):
        client = self._client()
        lang_name = self.lang.currentText()
        self.tree.clear()
        self._busy(True, f"Searching {lang_name} subtitles...")

        def work():
            try:
                res, others, problems = be.find_subtitles(self.path, lang_name, client)
            except Exception as e:  # never leave the window stuck on "Searching..."
                res, others, problems = [], [], [f"The search failed ({e.__class__.__name__}: {e})."]
            self._later(lambda: self._show(res, others, problems, lang_name))

        worker(work)

    def _show(self, results, others, problems, lang_name):
        self.results = results
        self.tree.clear()
        for s in results:
            notes = [n for n, on in (("same release", s["same_release"] and not s["exact"]),
                                     (s["variant"], bool(s["variant"])),
                                     ("hearing impaired", s["hearing_impaired"]),
                                     ("machine translated", s["machine"]), ("trusted", s["trusted"]),
                                     ("from your API key", s["source"] == "opensubtitles")) if on]
            downloads = f"{s['downloads']:,}" if s["downloads"] is not None else ""
            it = QTreeWidgetItem(["✓" if s["exact"] else "", s["release"], downloads, ", ".join(notes)])
            it.setToolTip(0, "Made for exactly this file" if s["exact"] else "")
            it.setToolTip(1, s["release"])
            if s["exact"]:
                it.setForeground(0, QColor("#2e8b57"))
            self.tree.addTopLevelItem(it)
        if results:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        exact = sum(s["exact"] for s in results)
        if not results:
            text = f"No {lang_name} subtitles found."
            if others:
                text += " There are some in " + ", ".join(others[:8]) + ("..." if len(others) > 8 else ".")
        else:
            text = (f"{len(results)} found" + (f", {exact} made for exactly this file (✓)" if exact else "")
                    + ". Double-click one to use it.")
        if problems:
            text += ("\n" if text else "") + "\n".join(problems)
        self._busy(False, text)
        if any("API key" in p for p in problems):
            self.account.show()

    def _selection(self):
        self.get_btn.setEnabled(bool(self.tree.selectedItems()) and self.search_btn.isEnabled())

    def download(self):
        items = self.tree.selectedItems()
        client = self._client()
        if not items or not self.search_btn.isEnabled():
            return
        sub = self.results[self.tree.indexOfTopLevelItem(items[0])]
        self._busy(True, "Downloading...")

        def work():
            try:
                (f, remaining), err = be.fetch_subtitle(sub, self.path, client), None
            except be.SubtitleError as e:
                f, remaining, err = None, None, str(e)
            self._later(lambda: self._downloaded(f, err, remaining))

        worker(work)

    def _downloaded(self, f, err, remaining):
        if err:
            self._busy(False, err)
            return
        be.log(f"subtitles downloaded for {Path(self.path).name}: {Path(f).name}"
               + (f" ({remaining} downloads left today)" if remaining is not None else ""))
        self.win.use_online_subtitle(self.path, f, remaining)
        self.accept()


class MainWindow(QWidget):
    devicesChanged = Signal()

    def __init__(self, state_path, discover=True):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.state_path = state_path
        self.state = load_state(state_path)
        self.bridge = Bridge()
        self.bridge.call.connect(lambda fn: fn())
        self.server = be.MediaServer()
        self.server.start()
        self.encoder = "libx264"
        self.discovery = be.Discovery(lambda: self.bridge.call.emit(self.devicesChanged.emit),
                                      self.state["known_devices"])
        # connection to the TV (kept between videos) and playback
        self.conn = None
        self.connecting = False
        self._splash_url = None
        self.load_time = 0.0
        self.wd_pos, self.wd_time = 0.0, 0.0
        self.last_recover = 0.0
        self.gen = 0
        self.intro_busy = set()  # videos whose intro is being looked for
        self.intro_for = None    # the video whose intro countdown ran (or was cancelled)
        self.screen = None       # while the PC screen is cast: {index, sound, player, since, playing}
        self.tv_display = None   # the TV as a second display: {name, ours (Video Caster switched it on)}
        self.tv_display_busy = False
        self.screen_timer = QTimer(self, interval=2000, timeout=self._screen_poll)
        self.load_lock = threading.Lock()
        self.pending_seek = None
        self.seek_timer = QTimer(self, singleShot=True, interval=600, timeout=self._do_pending_seek)
        self.restart_reason = "Changing settings..."
        self.next_anchor = None       # the playlist video "Possible Next" hangs under
        self.next_suggestion = None   # the next episode found next to it on disk
        self.preparer = be.Preparer()  # makes a seekable copy of a live-streamed video
        self.prepared_pending = None
        worker(self._clean_cache)  # what earlier runs left behind (closed mid-video, for example)
        self.server.on_rerequest = lambda entry: self.bridge.call.emit(lambda: self._tv_restarted(entry))
        self.player = None
        self.now_path = None
        self.stream = None
        self.duration = 0.0
        self.position = 0.0
        self.play_state = "idle"
        self.seen_playing = False
        self.loading = False
        self.last_resume_save = 0.0
        self.last_thumb = 0.0
        self.restart_timer = QTimer(self, singleShot=True, interval=700, timeout=self._restart_after_settings)
        self.scrub_want = None
        self.scrub_busy = False
        self.message_until = 0.0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(draw_icon("cast", ACCENT, 32))
        self.setAcceptDrops(True)
        self.setMinimumWidth(420)
        self._build()
        self.devicesChanged.connect(self._devices_changed)
        self.settings_panel = SettingsPanel(self)
        self.device_panel = DevicePanel(self)
        self.share_panel = SharePanel(self)
        self.splash_path = self._make_splash()
        self._load_playlist_tabs()
        self._restore_geometry()

        self.poll = QTimer(self, interval=500, timeout=self._poll)
        self.poll.start()
        self._shortcuts()
        if discover:
            self.discovery.start()
        worker(self._detect_encoder)
        self._probe_durations()
        self._update_header()

    # ----- layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setFixedHeight(TOP_H)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        leftcol = QVBoxLayout()
        leftcol.setSpacing(0)
        header = QWidget()
        header.setFixedHeight(HEADER_H)
        header.setStyleSheet(f"background: {HEADER_BG};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 9, 10, 7)
        hl.setSpacing(2)
        self.title = QLabel(APP_NAME)
        self.title.setStyleSheet("color: white; font-size: 15px; font-weight: 600;")
        self.time = QLabel("Not Playing")
        self.time.setStyleSheet("color: #b9bac6; font-size: 11px;")
        hl.addWidget(self.title)
        hrow = QHBoxLayout()  # the time, and the TV chip on the right: the title keeps the whole width
        hrow.setSpacing(8)
        hrow.addWidget(self.time, 1)
        hl.addLayout(hrow)
        # the TV: its name and whether it's connected; opens the TV list or the TV's panel
        self.btn_cast = QPushButton()
        self.btn_cast.setObjectName("tvchip")
        self.btn_cast.setCursor(Qt.PointingHandCursor)
        self.btn_cast.setFocusPolicy(Qt.NoFocus)
        self.btn_cast.setIconSize(QSize(14, 14))
        self.btn_cast.setStyleSheet("QPushButton#tvchip { color: white; background: rgba(255,255,255,18);"
                                    " border: 1px solid rgba(255,255,255,70); border-radius: 11px;"
                                    " padding: 2px 10px 2px 7px; font-size: 11px; min-height: 18px; }"
                                    "QPushButton#tvchip:hover { background: rgba(255,255,255,45); }")
        hrow.addWidget(self.btn_cast, 0, Qt.AlignVCenter)
        self.tv_chip_state = None
        self.header = header
        leftcol.addWidget(header)

        bar = QWidget()
        bar.setStyleSheet("background: white;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 8, 0)
        bl.setSpacing(4)
        self.btn_list = tool_button("list", "Show or hide the playlist")
        self.btn_back = tool_button("rewind", "Back 10 seconds (Left arrow)")
        self.btn_play = tool_button("play", "Play / pause (Space)", 32)
        self.btn_stop = tool_button("stop", "Stop")
        self.btn_next = tool_button("next", "Next video")
        self.btn_gear = tool_button("gear", "Settings for this video")
        self.btn_screen = tool_button("screen", "Show your screen on the TV: mirror it, or use the TV as a second display")
        for b in (self.btn_list, self.btn_back, self.btn_play, self.btn_stop, self.btn_next):
            bl.addWidget(b)
        bl.addStretch()
        bl.addWidget(self.btn_screen)
        bl.addWidget(self.btn_gear)
        leftcol.addWidget(bar)
        tl.addLayout(leftcol, 1)
        self.thumb = Thumb(self)
        tl.addWidget(self.thumb)
        root.addWidget(top)
        self.top = top

        self.seek = SeekBar()
        root.addWidget(self.seek)

        # "Up next" bar: shown during the countdown at the end credits
        bar_style = (f"QFrame {{ background: {ACCENT_DARK.name()}; }}"
                     "QLabel { color: white; font-size: 12px; background: transparent; }"
                     "QPushButton { color: white; border: 1px solid rgba(255,255,255,150);"
                     " padding: 2px 10px; font-size: 11px; background: transparent; }"
                     "QPushButton:hover { background: rgba(255,255,255,40); }")
        self.upnext_bar = QFrame()
        self.upnext_bar.setStyleSheet(bar_style)
        ub = QHBoxLayout(self.upnext_bar)
        ub.setContentsMargins(12, 5, 10, 5)
        self.upnext_label = QLabel()
        self.upnext_play = QPushButton("Play now")
        self.upnext_cancel = QPushButton("Cancel")
        ub.addWidget(self.upnext_label, 1)
        ub.addWidget(self.upnext_play)
        ub.addWidget(self.upnext_cancel)
        self.upnext_bar.hide()
        root.addWidget(self.upnext_bar)
        # "Skipping intro" bar: shown during the countdown at a series' opening titles
        self.intro_bar = QFrame()
        self.intro_bar.setStyleSheet(bar_style)
        ib = QHBoxLayout(self.intro_bar)
        ib.setContentsMargins(12, 5, 10, 5)
        self.intro_label = QLabel()
        self.intro_skip = QPushButton("Skip now")
        self.intro_watch = QPushButton("Watch intro")
        ib.addWidget(self.intro_label, 1)
        ib.addWidget(self.intro_skip)
        ib.addWidget(self.intro_watch)
        self.intro_bar.hide()
        root.addWidget(self.intro_bar)
        # "Live" bar: while this PC's screen is on the TV - what's shown where, and Stop
        self.live_bar = QFrame()
        self.live_bar.setObjectName("livebar")
        self.live_bar.setStyleSheet("QFrame#livebar { background: #b3261e; }"
                                    "QLabel { color: white; background: transparent; }"
                                    "QPushButton { color: white; border: 1px solid rgba(255,255,255,170);"
                                    " padding: 3px 12px; font-size: 11px; font-weight: bold; background: transparent; }"
                                    "QPushButton:hover { background: rgba(255,255,255,45); }"
                                    "QToolButton { border: none; background: transparent; }"
                                    "QToolButton:hover { background: rgba(255,255,255,45); }")
        lb = QHBoxLayout(self.live_bar)
        lb.setContentsMargins(12, 6, 8, 6)
        lb.setSpacing(9)
        self.live_tag = QLabel("LIVE")
        self.live_tag.setStyleSheet("background: white; color: #b3261e; font-size: 9px; font-weight: bold;"
                                    " padding: 1px 5px; border-radius: 3px;")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.live_title = QLabel()
        self.live_title.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.live_sub = QLabel()
        self.live_sub.setStyleSheet("font-size: 11px; color: #ffdcd8;")
        texts.addWidget(self.live_title)
        texts.addWidget(self.live_sub)
        self.live_sound = QToolButton()
        self.live_sound.setIconSize(QSize(18, 18))
        self.live_sound.setFixedSize(28, 26)
        self.live_sound.setCursor(Qt.PointingHandCursor)
        self.live_sound.setFocusPolicy(Qt.NoFocus)
        self.live_stop = QPushButton("Stop sharing")
        self.live_stop.setCursor(Qt.PointingHandCursor)
        self.live_stop.setFocusPolicy(Qt.NoFocus)
        lb.addWidget(self.live_tag, 0, Qt.AlignVCenter)
        lb.addLayout(texts, 1)
        lb.addWidget(self.live_sound)
        lb.addWidget(self.live_stop)
        self.live_bar.hide()
        root.addWidget(self.live_bar)
        self.live_stop.clicked.connect(lambda: self.end_screen(stop_tv=True))
        self.live_sound.clicked.connect(
            lambda: self._set_screen_sound(not self.state["global"].get("screen_sound", True)))

        self.list_area = QWidget()
        self.list_area.setStyleSheet(f"background: {LIST_BG};")
        la = QVBoxLayout(self.list_area)
        la.setContentsMargins(0, 6, 0, 0)
        la.setSpacing(2)
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(8, 0, 10, 0)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setStyleSheet("""
            QTabBar::tab { background: transparent; border: none; padding: 3px 4px 3px 4px; margin-right: 8px;
                           color: #6a6a72; font-size: 12px; }
            QTabBar::tab:selected { color: #111; font-weight: bold; }
        """)
        tabs_row.addWidget(self.tabs)
        tabs_row.addStretch()
        self.btn_newlist = QToolButton()
        self.btn_newlist.setText(" New Playlist")
        self.btn_newlist.setIcon(draw_icon("plus", "#7a7a82", 14))
        self.btn_newlist.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_newlist.setAutoRaise(True)
        self.btn_newlist.setCursor(Qt.PointingHandCursor)
        self.btn_newlist.setStyleSheet("QToolButton { color: #7a7a82; font-size: 11px; border: none; }"
                                       "QToolButton:hover { color: #333; }")
        tabs_row.addWidget(self.btn_newlist)
        la.addLayout(tabs_row)
        self.list = PlaylistView()
        self.list.setItemDelegate(PlaylistDelegate(self))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.empty = EmptyState(self.list, self)
        for sig in (self.list.model().rowsInserted, self.list.model().rowsRemoved, self.list.model().modelReset):
            sig.connect(lambda *a: self._update_empty())
        la.addWidget(self.list, 1)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_row.addWidget(grip)
        la.addLayout(grip_row)
        root.addWidget(self.list_area, 1)

        # signals
        self.btn_list.clicked.connect(self.toggle_playlist)
        self.btn_back.clicked.connect(lambda: self.seek_relative(-10))
        self.btn_play.clicked.connect(self.play_pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_next.clicked.connect(self.play_next)
        self.btn_gear.clicked.connect(self.show_settings)
        self.btn_screen.clicked.connect(self.screen_menu)
        self.btn_cast.clicked.connect(self.show_devices)
        self.btn_newlist.clicked.connect(self.new_playlist)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.tabBarDoubleClicked.connect(self.rename_playlist)
        self.list.itemDoubleClicked.connect(lambda it: self.play_path(it.data(Qt.UserRole)))
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.list.filesDropped.connect(self.add_paths)
        self.list.moveRequested.connect(self._move_rows)
        self.list.subtitleDropped.connect(self._attach_subtitle)
        self.list.suggestionActivated.connect(self.play_suggestion)
        self.seek.scrubbing.connect(self._scrubbing)
        self.seek.seekTo.connect(lambda f: self.seek_to(f * self.duration))
        self.upnext_play.clicked.connect(self._upnext_go)
        self.upnext_cancel.clicked.connect(lambda: self._upnext_cancel("cancelled"))
        self.intro_skip.clicked.connect(self._intro_go)
        self.intro_watch.clicked.connect(lambda: self._intro_cancel("watching the intro"))

    def _shortcuts(self):
        for key, fn in (("Space", self.play_pause), ("Left", lambda: self.seek_relative(-10)),
                        ("Right", lambda: self.seek_relative(30)), ("Ctrl+Up", lambda: self.change_volume(0.05)),
                        ("Ctrl+Down", lambda: self.change_volume(-0.05)), ("Delete", self.remove_selected),
                        ("Return", self._play_selected), ("Enter", self._play_selected)):
            QShortcut(QKeySequence(key), self, activated=fn)
        QShortcut(QKeySequence.Open, self, activated=self.add_files_dialog)

    # ----- window chrome
    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32":
            try:
                import ctypes
                pref = ctypes.c_int(2)  # DWMWCP_ROUND
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), 4)
            except Exception:
                pass

    def enterEvent(self, e):
        self.thumb.show_buttons(True)

    def leaveEvent(self, e):
        self.thumb.show_buttons(False)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < TOP_H:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    @staticmethod
    def _clean_cache():
        items, freed = be.clean_cache()
        if items:
            be.log(f"cache: removed {items} leftover item(s), {freed / 1e6:.0f} MB")

    def _restore_geometry(self):
        g = self.state.get("geometry")
        self.resize(WINDOW_W, 420)
        if g:
            x, y = g.get("x", 200), g.get("y", 200)
            w, h = max(420, g.get("w", WINDOW_W)), max(TOP_H + 8, g.get("h", 420))
            # The screen it was on last time may be gone (a second monitor unplugged): only use
            # that spot if the top of the window lands on a screen now, else the main screen.
            top = QRect(x, y, w, HEADER_H)
            if not any(s.availableGeometry().intersected(top).width() >= 120
                       and s.availableGeometry().intersected(top).height() >= 30 for s in QGuiApplication.screens()):
                avail = QGuiApplication.primaryScreen().availableGeometry()
                w, h = min(w, avail.width()), min(h, avail.height())
                x, y = avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 3
            self.move(x, y)
            self.resize(w, h)
        if not self.state.get("playlist_visible", True):
            self.list_area.hide()
            self.setFixedHeight(TOP_H + 8)

    def toggle_playlist(self):
        if self.list_area.isVisible():
            self.state["expanded_h"] = self.height()
            self.list_area.hide()
            self.setFixedHeight(TOP_H + 8)
            self.state["playlist_visible"] = False
        else:
            self.setMinimumHeight(TOP_H + 120)
            self.setMaximumHeight(16777215)
            self.list_area.show()
            self.resize(self.width(), max(TOP_H + 160, self.state.get("expanded_h", 420)))
            self.setMinimumHeight(TOP_H + 8)
            self.state["playlist_visible"] = True
        self.save()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_header()

    def closeEvent(self, e):
        self._save_resume()
        self.preparer.cancel()  # don't leave ffmpeg running after the app closes
        self.screen_timer.stop()
        self.server.stop_transcodes()  # quick: every conversion and screen capture ends now
        if self.screen is not None and self.screen.get("mirror") is not None:
            self.screen["mirror"].close()  # (the goodbye below closes the receiver on the TV)
        if self.tv_display is not None and self.tv_display["ours"]:
            self._safe(be.detach_virtual_display)  # no windows left on a screen nobody sees
            self.tv_display = None
        self.settings_panel.hide()
        self.save()
        # Saying goodbye to the TV and stopping the TV search can take long: a TV the app
        # saw before that doesn't answer (switched off, or another network) holds the search
        # up for up to 30 s. Do it in the background and wait a few seconds at most, so
        # closing never freezes the window.
        conn, server, discovery = self.conn, self.server, self.discovery

        def goodbye():
            if conn is not None:  # the TV streams from this app: close the receiver before the server goes
                try:
                    conn.disconnect()
                except Exception:
                    pass
            for fn in (server.stop, discovery.stop):
                try:
                    fn()
                except Exception:
                    pass

        t = threading.Thread(target=goodbye, daemon=True)
        t.start()
        self.hide()
        QApplication.processEvents()
        t.join(3)
        super().closeEvent(e)

    def save(self):
        if self.list_area.isVisible():
            self.state["geometry"] = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
        else:
            g = self.state.get("geometry") or {}
            self.state["geometry"] = {**g, "x": self.x(), "y": self.y(), "w": self.width()}
        self.state["known_devices"] = self.discovery.known()
        save_state(self.state_path, self.state)

    # ----- drag and drop onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        subs = [p for p in paths if Path(p).suffix.lower() in be.SUB_EXTS]
        if subs:
            target = self.now_path or self.selected_path()
            if target:
                self._attach_subtitle_to(subs[0], target)
        vids = [p for p in paths if p not in subs]
        if vids:
            self.add_paths(vids, self.list.count())

    # ----- playlists
    @property
    def playlist(self):
        return self.state["playlists"][self.state["current_playlist"]]["items"]

    def _load_playlist_tabs(self):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for pl in self.state["playlists"]:
            i = self.tabs.addTab(pl["name"])
            self._add_tab_close(i)
        self.tabs.setCurrentIndex(self.state["current_playlist"])
        self.tabs.blockSignals(False)
        self._fill_list()

    def _add_tab_close(self, i):
        b = QToolButton()
        b.setIcon(draw_icon("x-small", "#6a6a72", 12))
        b.setIconSize(QSize(12, 12))
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip("Close this playlist")
        b.setStyleSheet("QToolButton { border: none; }")
        b.clicked.connect(lambda _=False, btn=b: self.close_playlist(self._tab_index_of(btn)))
        self.tabs.setTabButton(i, QTabBar.RightSide, b)

    def _tab_index_of(self, btn):
        for i in range(self.tabs.count()):
            if self.tabs.tabButton(i, QTabBar.RightSide) is btn:
                return i
        return -1

    def _tab_changed(self, i):
        if 0 <= i < len(self.state["playlists"]):
            self.state["current_playlist"] = i
            self._fill_list()
            self.save()

    def _tab_moved(self, frm, to):
        pls = self.state["playlists"]
        pls.insert(to, pls.pop(frm))
        self.state["current_playlist"] = self.tabs.currentIndex()
        self.save()

    def new_playlist(self):
        names = {p["name"] for p in self.state["playlists"]}
        n = 2
        while f"Playlist {n}" in names:
            n += 1
        self.state["playlists"].append({"name": f"Playlist {n}", "items": []})
        i = self.tabs.addTab(f"Playlist {n}")
        self._add_tab_close(i)
        self.tabs.setCurrentIndex(i)

    def rename_playlist(self, i):
        if i < 0:
            return
        name, ok = QInputDialog.getText(self, "Rename playlist", "Name:", text=self.state["playlists"][i]["name"])
        if ok and name.strip():
            self.state["playlists"][i]["name"] = name.strip()
            self.tabs.setTabText(i, name.strip())
            self.save()

    def close_playlist(self, i):
        if i < 0:
            return
        pl = self.state["playlists"][i]
        if pl["items"] and QMessageBox.question(
                self, APP_NAME, f"Close \"{pl['name']}\" with {len(pl['items'])} video(s)?") != QMessageBox.Yes:
            return
        if len(self.state["playlists"]) == 1:
            pl["items"].clear()
            pl["name"] = "Playlist"
            self.tabs.setTabText(0, "Playlist")
            self._fill_list()
        else:
            self.state["playlists"].pop(i)
            self.state["current_playlist"] = min(self.state["current_playlist"], len(self.state["playlists"]) - 1)
            self._load_playlist_tabs()
        self.save()

    def _update_empty(self):
        """The 'What would you like on the TV?' cards: only while the playlist is empty."""
        try:
            e = self.list.empty
            e.setGeometry(self.list.viewport().rect())
            e.setVisible(self.list.count() == 0)
        except RuntimeError:  # the window is being closed and its playlist taken down
            pass

    def _fill_list(self, select=None):
        self.list.clear()
        for p in self.playlist:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            self.list.addItem(it)
        for row in select or []:
            if 0 <= row < self.list.count():
                self.list.item(row).setSelected(True)
        self._update_empty()
        self._refresh_next()

    def _refresh_next(self):
        """Like Airflow: what comes after the playlist ends - the next episode on disk of
        the playlist's last video, if it isn't in the playlist yet. Shown as a grey
        'Possible Next' line under that video, and played when the playlist runs out."""
        anchor = self.playlist[-1] if self.playlist else None
        sug = be.next_episode(anchor) if anchor else None
        if sug and (sug in self.playlist or not os.path.exists(sug)):
            sug = None
        if (anchor, sug) != (self.next_anchor, self.next_suggestion):
            self.next_anchor, self.next_suggestion = anchor, sug
            self.list.doItemsLayout()
        self.list.viewport().update()
        self._update_buttons()

    def play_suggestion(self):
        anchor, sug = self.next_anchor, self.next_suggestion
        if not sug or anchor not in self.playlist:
            return
        i = self.playlist.index(anchor) + 1
        self.playlist.insert(i, sug)
        self._fill_list(select=[i])
        self.save()
        self._probe_durations()
        self.play_path(sug)

    def add_paths(self, paths, row=None):
        files = [p for p in dict.fromkeys(collect_videos(paths)) if p not in self.playlist]
        if not files:
            return
        row = len(self.playlist) if row is None else max(0, min(row, len(self.playlist)))
        self.playlist[row:row] = files
        self._fill_list(select=range(row, row + len(files)))
        self.save()
        self._probe_durations()

    def add_files_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(be.VIDEO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add videos", "", f"Videos ({exts});;All files (*.*)")
        if files:
            self.add_paths(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder")
        if d:
            self.add_paths([d])

    def _move_rows(self, rows, target):
        items = [self.playlist[r] for r in rows]
        before = sum(1 for r in rows if r < target)
        for r in reversed(rows):
            self.playlist.pop(r)
        target -= before
        self.playlist[target:target] = items
        self._fill_list(select=range(target, target + len(items)))
        self.save()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()}, reverse=True)
        for r in rows:
            self.playlist.pop(r)
        self._fill_list()
        self.save()

    def selected_path(self):
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _selection_changed(self):
        if self.player is None:
            self._update_header()
            p = self.selected_path()
            if p:
                self._load_thumb(p, None)

    def _list_menu(self, pos):
        m = QMenu(self)
        it = self.list.itemAt(pos)
        if it and self.list.on_next_line(pos):
            sug = self.next_suggestion
            m.addAction("Play next episode", self.play_suggestion)
            m.addAction("Add to playlist", lambda: self.add_paths([sug], self.playlist.index(self.next_anchor) + 1))
            m.exec(self.list.viewport().mapToGlobal(pos))
            return
        if it:
            path = it.data(Qt.UserRole)
            m.addAction("Play", lambda: self.play_path(path))
            m.addAction("Play from the beginning", lambda: self.play_path(path, from_start=True))
            m.addSeparator()
            m.addAction("Mark as watched", lambda: self._mark(path, True))
            m.addAction("Mark as not watched", lambda: self._mark(path, False))
            m.addAction("Find subtitles online...", lambda: self.search_subtitles(path, False))
            m.addAction("Show in Explorer", lambda: subprocess.Popen(["explorer", "/select,", os.path.normpath(path)]))
            m.addAction("Remove from playlist", self.remove_selected)
            m.addSeparator()
        m.addAction("Add videos...", self.add_files_dialog)
        m.addAction("Add a folder...", self.add_folder_dialog)
        if self.playlist:
            m.addAction("Clear playlist", self._clear_playlist)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _clear_playlist(self):
        self.playlist.clear()
        self._fill_list()
        self.save()

    def _mark(self, path, watched):
        if watched:
            self.state["resume"][path] = self.state["durations"].get(path) or 0
        else:
            self.state["resume"].pop(path, None)
        self.list.viewport().update()
        self.save()

    def _attach_subtitle(self, sub, row):
        if 0 <= row < len(self.playlist):
            self._attach_subtitle_to(sub, self.playlist[row])

    def _attach_subtitle_to(self, sub, path):
        self.set_file_setting(path, "subtitle", f"ext:{os.path.normpath(sub)}")
        self.flash(f"Subtitles: {Path(sub).name}")

    def search_subtitles(self, path, back_to_settings=True):
        """The 'Find subtitles online' window for a video (opened from the settings, they come back after)."""
        if not path:
            return
        SubtitleSearchDialog(self, path).exec()
        if back_to_settings:
            self.show_settings()

    def use_online_subtitle(self, path, sub, remaining=None):
        """Use subtitles just downloaded for `path` (restarts it if it's playing), and remember
        the language so the next episodes pick the same."""
        key = f"ext:{os.path.normpath(sub)}"
        pref = be.subtitle_language(path, be.probe(path), key)
        if pref:
            self.state["global"]["sub_pref"] = list(pref)
        self.set_file_setting(path, "subtitle", key)
        label = next((lb for p, lb, _ in be.external_subtitles(path) if os.path.normpath(p) == os.path.normpath(sub)),
                     Path(sub).name)
        self.flash(f"Subtitles: {label}" + (f" - {remaining} downloads left today" if remaining is not None else ""), 5)

    def _probe_durations(self):
        todo = [p for pl in self.state["playlists"] for p in pl["items"] if p not in self.state["durations"]]
        if not todo:
            return

        def work():
            for p in todo:
                if os.path.exists(p):
                    d = be.duration_of(be.probe(p))
                    if d:
                        self.bridge.call.emit(lambda p=p, d=d: self._got_duration(p, d))

        worker(work)

    def _got_duration(self, path, d):
        self.state["durations"][path] = d
        self.list.viewport().update()
        if path == (self.now_path or self.selected_path()):
            self._update_header()

    # ----- settings
    def file_settings(self, path):
        return {**be.FILE_DEFAULTS, **(self.state["file_settings"].get(path or "", {}))}

    def set_file_setting(self, path, key, value):
        fs = self.state["file_settings"].setdefault(path, {})
        fs[key] = value
        self.save()
        self.settings_changed(path, key)

    def settings_changed(self, path, key):
        """Apply a settings change to what is playing: the subtitles' look (size, colour,
        font) changes live on the TV; anything that changes the stream restarts it at the
        current position (burned-in subtitles are part of the picture, so they restart too)."""
        if self.player is None or not self.now_path or (path and path != self.now_path):
            return
        if key in be.SUB_STYLE_KEYS and self.stream and self.stream.get("sub_url"):
            style = be.subtitle_style(self.file_settings(self.now_path), self.state["global"])
            self.stream["sub_style"] = style
            worker(self.player.set_sub_style, style)
            return
        if key == "scrubbing":
            return
        burned = bool(self.stream and self.stream["plan"].get("burn"))
        if key == "skip_intro" and not self.state["global"].get("skip_intro", True):
            self._intro_cancel(None)
        if (key in ("subtitle", "sub_encoding", "sub_delay", "sub_render", "up_next")
                or (key == "skip_intro" and (self.stream or {}).get("intro_window"))
                or (burned and key in be.SUB_STYLE_KEYS)
                or self._plan_changed()):
            self.restart_reason = "Changing subtitles..." if key.startswith("sub") else "Changing settings..."
            self.restart_timer.start()

    @staticmethod
    def _plan_key(plan):
        convert = plan["mode"] == "transcode"
        return (plan["mode"], plan["audio_index"], plan["audio_copy"], plan.get("audio_out"), plan["audio_channels"],
                tuple(plan["afilters"]),
                plan["deinterlace"], plan["aspect"], plan["burn"],
                plan["target_h"] if convert else None, plan["encoder"] if convert else None,
                plan["hw_decode"] if convert else None)

    def _plan_changed(self):
        if not self.stream:
            return True
        new = be.plan_stream(self.now_path, be.probe(self.now_path), self.file_settings(self.now_path),
                             self.state["global"], self.encoder)
        return self._plan_key(new) != self._plan_key(self.stream["plan"])

    def _restart_after_settings(self):
        if self.player is not None and self.now_path:
            self._start(self.now_path, self.pending_seek if self.pending_seek is not None else self.position,
                        status=self.restart_reason)

    def show_settings(self):
        p = self.settings_panel
        if p.isVisible():
            p.hide()
            return
        p.open_for(self.now_path or self.selected_path())
        p.adjustSize()
        g = self.mapToGlobal(QPoint(0, TOP_H - 6))
        x = g.x() + (self.width() - p.width()) // 2
        screen = QGuiApplication.screenAt(g) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = max(avail.left(), min(x, avail.right() - p.width()))
        p.move(x, g.y())
        p.show()

    # ----- devices
    def current_device(self):
        did = self.state.get("device_id")
        for d in self.discovery.snapshot():
            if d.id == did:
                return d
        return None

    def _devices_changed(self):
        if not self.state.get("device_id"):
            video = [d for d in self.discovery.snapshot() if d.online and d.video]
            if len(video) == 1:  # one TV on the network: use it
                self.state["device_id"] = video[0].id
        self._update_header()

    def show_devices(self):
        dev = self.current_device()
        if self.conn is not None and dev is not None and self.conn.device is dev:
            p = self.device_panel
            p.open_for(self.conn)
            p.adjustSize()
            g = self.btn_cast.mapToGlobal(QPoint(self.btn_cast.width() // 2 - p.width() // 2, self.btn_cast.height()))
            p.move(g)
            p.show()
            return
        self.discovery.scan_airplay()
        self.device_menu().exec(self.btn_cast.mapToGlobal(QPoint(-90, self.btn_cast.height())))

    # ----- connecting (like Airflow: a fresh receiver on the TV and a picture, before any video)
    def _make_splash(self):
        be.CACHE_DIR.mkdir(exist_ok=True)
        path = be.CACHE_DIR / "splash.png"
        img = QImage(1920, 1080, QImage.Format_RGB32)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 0, 1080)
        grad.setColorAt(0, QColor("#3c3d48"))
        grad.setColorAt(1, QColor("#1d1d24"))
        p.fillRect(img.rect(), grad)
        p.drawPixmap(960 - 90, 300, draw_icon("cast", ACCENT, 180).pixmap(180, 180))
        f = QFont("Segoe UI", 54)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, 520, 1920, 110), Qt.AlignCenter, APP_NAME)
        p.setFont(QFont("Segoe UI", 24))
        p.setPen(QColor("#b9bac6"))
        p.drawText(QRectF(0, 640, 1920, 60), Qt.AlignCenter, "Connected - choose a video on your PC")
        p.end()
        img.save(str(path))
        return path

    def splash_url(self):
        if self._splash_url is None:
            self._splash_url = self.server.register(str(self.splash_path), "media", name="splash.png", mime="image/png")
        return self._splash_url

    def connect_device(self, dev, then=None):
        """Restart the receiver on the TV and show the Video Caster picture; then run `then`."""
        if self.connecting:
            return
        self.connecting = True
        self._update_header(f"Connecting to {dev.name}...")
        splash = self.splash_url()

        def work():
            try:
                p = be.make_player(dev, self.discovery)
                p.connect(fresh=True)
                p.show_picture(splash)
                self.bridge.call.emit(lambda: self._connected(p, then))
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                self.bridge.call.emit(lambda: self._connect_failed(dev, msg))

        worker(work)

    def _connected(self, player, then):
        self.connecting = False
        self.conn = player
        self.flash(f"Connected to {player.device.name}")
        self._update_header()
        if then:
            then()

    def _connect_failed(self, dev, msg):
        self.connecting = False
        self._update_header()
        QMessageBox.warning(self, APP_NAME, f"Couldn't connect to {dev.name}.\n\n{msg}")

    def disconnect_device(self):
        conn = self.conn
        if conn is None:
            return
        if self.screen is not None:
            self.end_screen(stop_tv=False)
        if self.player is not None:
            self.stop(picture=False)
        self.conn = None
        worker(self._safe, conn.disconnect)
        self.flash(f"Disconnected from {conn.device.name}")
        self._update_header()

    # ----- casting the PC screen
    def screen_menu(self):
        """The screen button: the share panel (mirror or second display, screen, sound, delay)."""
        self.share_panel.open_at(self.btn_screen)

    def _set_screen_sound(self, on):
        self.state["global"]["screen_sound"] = bool(on)
        self.save()
        if self.screen is not None:  # cast again, now with (or without) the sound
            self.cast_screen(self.screen["index"])

    def _set_screen_mirror(self, on):
        self.state["global"]["screen_mirror"] = bool(on)
        self.save()
        if self.screen is not None:  # cast again the other way
            self.cast_screen(self.screen["index"])

    # ----- the TV as a second display
    @staticmethod
    def _screen_rect(sc):
        g, r = sc.geometry(), sc.devicePixelRatio()
        return round(g.x() * r), round(g.y() * r), round(g.width() * r), round(g.height() * r)

    @staticmethod
    def _tv_display_rect():
        """Where the TV's virtual display is on the desktop (x, y, w, h), or None when it's off."""
        try:
            vd = be.virtual_display()
        except Exception:
            return None
        return tuple(vd["rect"]) if vd and vd["attached"] and vd["rect"] else None

    def cast_tv_display(self):
        """The TV as a second display: a virtual display to the right of this PC's screen, mirrored
        to the TV - windows dragged there show on the TV. The first time, the bundled Virtual
        Display Driver is installed (Windows asks for permission)."""
        dev = self.current_device()
        if dev is None:
            QMessageBox.information(self, APP_NAME, "Choose a TV first: click the TV button at the top right.")
            self.show_devices()
            return
        if self.connecting or self.tv_display_busy:
            return
        if self.conn is None or self.conn.device is not dev:  # connect first, then come back here
            if not dev.online:
                QMessageBox.warning(self, APP_NAME, f"{dev.name} isn't available right now. Check that it's switched on.")
                return
            self.connect_device(dev, then=self.cast_tv_display)
            return
        vd = be.virtual_display()
        if vd is None:
            if be.display_driver_files() is None:
                QMessageBox.information(self, APP_NAME, "Using the TV as a second display needs the Virtual Display "
                                        "Driver, which this copy of Video Caster doesn't include.\n\nUse the Video "
                                        "Caster installer, or install the driver from "
                                        "github.com/VirtualDrivers/Virtual-Display-Driver.")
                return
            if QMessageBox.question(
                    self, APP_NAME, "To use the TV as a second display, Windows needs an extra screen that isn't "
                    "really there - a virtual display - which Video Caster then shows on the TV.\n\nVideo Caster "
                    "includes the free, open-source Virtual Display Driver for this "
                    "(github.com/VirtualDrivers/Virtual-Display-Driver). Windows asks for permission to install it - "
                    "only this once.\n\nInstall it now?") != QMessageBox.Yes:
                return
        self.tv_display_busy = True
        self.flash("Installing the virtual display..." if vd is None else "Switching the TV display on...", 60)

        def work():
            try:
                if vd is None:
                    res = be.install_virtual_display()
                    if not res.get("ok"):
                        raise RuntimeError("" if res.get("cancelled") else res.get("error") or "unknown error")
                    end = time.time() + 15
                    while be.virtual_display() is None and time.time() < end:
                        time.sleep(0.5)
                on = be.attach_virtual_display()
                self.bridge.call.emit(lambda: self._tv_display_on(on))
            except Exception as e:
                msg = str(e)
                self.bridge.call.emit(lambda: self._tv_display_failed(msg))

        worker(work)

    def _tv_display_on(self, on, tries=0):
        """Windows switched the TV display on: once Qt lists it, cast it."""
        screens = QGuiApplication.screens()
        rects = [self._screen_rect(sc) for sc in screens]
        index = rects.index(tuple(on["rect"])) if tuple(on["rect"]) in rects else None
        if index is None:  # other scaling: the virtual screen by its monitor name, or by its size
            named = [i for i, sc in enumerate(screens) if "vdd" in sc.name().lower()]
            sized = [i for i, rc in enumerate(rects) if rc[2:] == tuple(on["rect"][2:]) and i > 0]
            index = (named or (sized if len(sized) == 1 else [None]))[0]
        if index is None and tries < 24:
            QTimer.singleShot(250, lambda: self._tv_display_on(on, tries + 1))
            return
        self.tv_display_busy = False
        self.message_until = 0  # the 'Switching the TV display on...' note is done
        if index is None:
            if on["ours"]:
                worker(be.detach_virtual_display)
            QMessageBox.warning(self, APP_NAME, "Windows switched the TV display on, but it didn't show up. "
                                                "Please try again.")
            return
        self.tv_display = {"name": on["name"], "ours": on["ours"]}
        be.log(f"TV display: casting {on['name']} (screen {index + 1}) as a second display")
        self.cast_screen(index)
        if self.screen is not None:
            self.screen["tv"] = True
            self._update_header()
        elif on["ours"]:  # casting couldn't start (e.g. no TV connection): don't leave it on
            self._tv_display_off()

    def _tv_display_failed(self, msg):
        self.tv_display_busy = False
        self.message_until = 0
        if not msg:
            self.flash("Not installed")
            return
        be.log(f"TV display: {msg}")
        QMessageBox.warning(self, APP_NAME, f"Couldn't switch the TV display on.\n\n{msg}")

    def _tv_display_off(self):
        """Casting ended: switch the TV display off again if Video Caster switched it on."""
        tvd, self.tv_display = self.tv_display, None
        if tvd is not None and tvd["ours"]:
            worker(be.detach_virtual_display)

    def cast_screen(self, index=0, allow_mirror=True):
        """Show this PC's screen (and play its sound) on the TV, live, until Stop."""
        dev = self.current_device()
        if dev is None:
            QMessageBox.information(self, APP_NAME, "Choose a TV first: click the TV button at the top right.")
            self.show_devices()
            return
        if not dev.online and not (self.conn is not None and self.conn.device is dev):
            QMessageBox.warning(self, APP_NAME, f"{dev.name} isn't available right now. Check that it's switched on.")
            return
        if self.connecting:
            return
        if self.conn is None or self.conn.device is not dev:
            self.connect_device(dev, then=lambda: self.cast_screen(index))
            return
        sound = bool(self.state["global"].get("screen_sound", True))
        try:  # a muted PC has no sound to send: the share panel warns before, the live bar while sharing
            muted = sound and bool((be.speaker_state() or (False,))[0])
        except Exception:
            muted = False
        # whatever played on the TV makes way (the new load replaces it there)
        if self.player is not None:
            self._save_resume()
            self._upnext_cancel(None)
            self._intro_cancel(None)
            self.player, self.stream, self.now_path = None, None, None
            self.play_state, self.loading = "idle", False
        self.screen_timer.stop()
        self.gen += 1
        gen = self.gen
        self.server.stop_transcodes()
        if self.screen is not None and self.screen.get("mirror") is not None:
            self.screen["mirror"].close()  # cast again (other sound/way): the new offer replaces it on the TV
        player = self.conn
        was_tv = bool(self.screen is not None and self.screen.get("tv") and self.screen["index"] == index)
        s = self.screen = {"index": index, "sound": sound, "player": player, "since": time.time(), "playing": False,
                           "mirror": None, "tv": was_tv, "muted": muted}
        be.log(f"casting screen {index + 1} to {dev.name} {'with' if sound else 'without'} sound")
        screens = QGuiApplication.screens()
        tv_rect = self._tv_display_rect()  # (the TV display isn't a screen of yours to mirror)
        s["single"] = sum(1 for sc in screens if not (tv_rect and self._screen_rect(sc) == tv_rect)) <= 1
        src = None
        name = screens[index].name() if index < len(screens) else None  # \\.\DISPLAYn, or the monitor's name
        rect = None
        if index < len(screens):  # the screen itself as the picture next to the title
            pm = screens[index].grabWindow(0)
            self.thumb.pix = pm.scaled(THUMB_W * 2, TOP_H * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb.update()
            g, r = screens[index].geometry(), screens[index].devicePixelRatio()
            src = (round(g.width() * r), round(g.height() * r))
            rect = (round(g.x() * r), round(g.y() * r)) + src
        self.btn_screen.setIcon(draw_icon("screen", ACCENT_DARK))
        self._update_header("Starting...")
        self._update_buttons()
        mirror = (allow_mirror and bool(self.state["global"].get("screen_mirror", True))
                  and getattr(player, "kind", "") == "chromecast" and getattr(player, "cast", None) is not None)

        def work():
            cast = None
            # which display to capture: Qt's and the capture's lists of displays can differ in
            # order, and a virtual display (the TV as a second screen) has an adapter of its own
            target = be.capture_target(name, index, rect)
            if target != (0, index):
                be.log(f"screen: {name} is display {target[1]} of graphics adapter {target[0]}")
            if mirror:  # Google's mirroring first: a fraction of a second behind
                m = None
                with self.load_lock:
                    if gen != self.gen:
                        return
                    host = player.device.host or getattr(getattr(player.cast, "cast_info", None), "host", None)
                    try:
                        m = be.ScreenMirror(player.cast, host, self.encoder, target, sound, src)
                    except Exception as e:
                        be.log(f"screen: mirroring isn't possible on {player.device.name} ({e}) - "
                               "sending the screen as a video stream instead")
                if m is not None:
                    s["mirror"] = m
                    if gen != self.gen or self.screen is not s:
                        m.close()
                        return
                    be.log(f"screen: mirroring to {player.device.name} at {m.size[0]}x{m.size[1]}, "
                           f"{be.MIRROR_DELAY_MS} ms behind" + ("" if m.with_sound or not sound else
                                                                ", without sound (it can't be recorded)"))
                    self.bridge.call.emit(lambda: self._update_header() if self.screen is s else None)
                    return
            try:
                # the screen as live HLS: capturing starts now, the TV fetches the pieces
                cast = be.ScreenCast(self.encoder, target, sound)
                url = self.server.add_screen(cast)
                stream = {"url": url, "mime": "application/x-mpegurl", "title": "PC screen", "live": True, "hls": True,
                          "screen": True}
                if sound and not cast.with_sound:
                    be.log("screen: the PC's sound can't be recorded - casting without it")
                with self.load_lock:
                    if gen != self.gen:
                        cast.close()
                        return
                    player.connect()
                    player.load(stream, 0)
            except Exception as e:
                if cast is not None:
                    cast.close()
                msg = str(e) or e.__class__.__name__
                self.bridge.call.emit(lambda: self.end_screen(stop_tv=False, why=f"Couldn't cast the screen: {msg}")
                                      if gen == self.gen else None)

        worker(work)
        self.screen_timer.start()

    def _screen_poll(self):
        """Every 2 s while the screen is cast: has the TV started it, or stopped it?"""
        s = self.screen
        if s is None:
            self.screen_timer.stop()
            return
        p, m = s["player"], s.get("mirror")
        if m is not None:  # mirroring: the TV's own reports say whether it plays
            self._screen_state(s, {"playing": "playing", "starting": "loading"}.get(m.state(), "mirror stopped"))
            return

        def work():
            try:
                if int(time.time()) % 6 < 2:
                    p.refresh()
                st = p.state()[0]
            except Exception:
                st = "error"
            self.bridge.call.emit(lambda: self._screen_state(s, st))

        worker(work)

    def _screen_state(self, s, st):
        if s is not self.screen:
            return
        if st == "mirror stopped":
            why = s["mirror"].why or be.ScreenMirror.STOPPED_TV
            if not s["playing"] and why != be.ScreenMirror.STOPPED_TV:
                be.log(f"screen: mirroring didn't start on {s['player'].device.name} ({why}) - "
                       "sending the screen as a video stream instead")
                self.cast_screen(s["index"], allow_mirror=False)
                return
            # stopped on the TV: leave it be; else (TV silent, capture ended) close the receiver there
            self.end_screen(stop_tv=why != be.ScreenMirror.STOPPED_TV, why=why)
            return
        if st in ("playing", "buffering", "paused"):
            if not s["playing"] and st == "playing":
                be.log(f"screen on the TV after {time.time() - s['since']:.1f}s")
            s["playing"] = s["playing"] or st == "playing"
        elif st in ("idle", "finished", "error") and (s["playing"] or time.time() - s["since"] > 45):
            self.end_screen(stop_tv=False, why="The TV couldn't show the screen" if st == "error" and not s["playing"]
                            else "Screen casting stopped on the TV")
            return
        self._update_header()

    def end_screen(self, stop_tv=True, picture=True, why=None):
        """Stop casting the screen (and stop the TV showing it, unless something else takes over)."""
        s, self.screen = self.screen, None
        if s is None:
            return
        self.screen_timer.stop()
        self.gen += 1
        self.server.stop_transcodes()
        m = s.get("mirror")
        if m is not None:
            m.close()  # quick: capturing and sending end now
        self._tv_display_off()  # its windows move back to this PC's screen
        if stop_tv:
            p, splash = s["player"], (self.splash_url() if picture else None)

            def work():
                with self.load_lock:
                    if m is None:
                        self._safe(p.stop)
                    elif not splash:
                        self._safe(lambda: m.close(quit_tv=True))  # the TV back to its home screen
                    if splash:
                        self._safe(p.show_picture, splash)  # (after mirroring: the media receiver again)

            worker(work)
        be.log("screen casting ended" + (f": {why}" if why else ""))
        self.btn_screen.setIcon(draw_icon("screen", ACCENT))
        self.thumb.set_png(None)
        self._update_header()
        self._update_buttons()
        if why:
            self.flash(why, 5)

    def run_speed_test(self):
        conn = self.conn
        if conn is None:
            return
        if self.player is not None and self.now_path:
            if QMessageBox.question(self, APP_NAME, "The speed test stops the video that's playing. Continue?") \
                    != QMessageBox.Yes:
                return
            self.stop(keep_header=True, picture=False)
        self.flash("Speed test - about 15 seconds...", 60)
        splash = self.splash_url()

        def work():
            try:
                mbps = be.speed_test(self.server, conn)
                self.bridge.call.emit(lambda: self._speed_result(conn, mbps))
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                self.bridge.call.emit(lambda: (self.flash("Speed test failed"),
                                               QMessageBox.warning(self, APP_NAME, f"Speed test failed.\n\n{msg}")))
            finally:
                self._safe(conn.show_picture, splash)

        worker(work)

    def _speed_result(self, conn, mbps):
        self.flash(f"Speed test: {mbps:.0f} Mbit/s")
        if mbps >= 40:
            verdict = "Excellent: even 4K files can be sent as they are."
        elif mbps >= 20:
            verdict = "Good: 1080p files and converted video play smoothly."
        elif mbps >= 10:
            verdict = ("OK: converted video (about 8 Mbit/s) plays smoothly; very high-bitrate files may stutter - "
                       "tick Force Conversion for those.")
        else:
            verdict = "Slow: set Quality to 720p or 480p in the settings (gear button) to avoid stuttering."
        QMessageBox.information(self, "Speed Test",
                                f"{conn.device.name} receives about <b>{mbps:.0f} Mbit/s</b> from this PC.<br><br>{verdict}")

    def device_menu(self):
        m = QMenu(self)
        m.setStyleSheet("QMenu { background: white; border: 1px solid #c8c8cf; padding: 0; }")
        devices = self.discovery.snapshot()
        if not devices:
            a = m.addAction("Searching for TVs...")
            a.setEnabled(False)
        cur = self.state.get("device_id")
        for d in devices:
            act = QWidgetAction(m)
            act.setDefaultWidget(DeviceRow(d, d.id == cur, lambda dev, menu=m: (menu.close(), self.choose_device(dev))))
            m.addAction(act)
        m.addSeparator()
        m.addAction("Search again", lambda: (self.discovery.scan_airplay(force=True), self.flash("Searching...")))
        return m

    def choose_device(self, dev):
        if self.conn is not None and self.conn.device is dev:
            return
        if not dev.online:
            QMessageBox.warning(self, APP_NAME, f"{dev.name} isn't available right now. Check that it's switched on.")
            return
        resume = (self.now_path, self.position) if self.player is not None and self.now_path else None
        if self.player is not None:
            self.stop(keep_header=True, picture=False)
        if self.conn is not None:  # leave the previous TV
            worker(self._safe, self.conn.disconnect)
            self.conn = None
        self.state["device_id"] = dev.id
        self.save()
        self.connect_device(dev, then=(lambda: self._start(*resume)) if resume else None)

    # ----- playback
    def _play_selected(self):
        p = self.selected_path()
        if p:
            self.play_path(p)

    def play_pause(self):
        if self.player is not None and self.play_state in ("playing", "buffering"):
            worker(self._safe, self.player.pause)
            self.play_state = "paused"
            self._update_buttons()
        elif self.player is not None and self.play_state == "paused":
            worker(self._safe, self.player.play)
            self.play_state = "playing"
            self._update_buttons()
        else:
            p = self.selected_path() or (self.playlist[0] if self.playlist else None)
            if p:
                self.play_path(p)

    def play_path(self, path, from_start=False):
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"This file can't be found:\n{path}")
            return
        dur = self.state["durations"].get(path) or 0
        start = 0.0 if from_start else float(self.state["resume"].get(path) or 0)
        if dur and start >= dur - 15:  # watched to the end: start again
            start = 0.0
        self._start(path, start)

    def _start(self, path, start, status="Connecting..."):
        if self.screen is not None:  # a video takes the TV over from the screen
            self.end_screen(stop_tv=False)
        dev = self.current_device()
        if dev is None:
            QMessageBox.information(self, APP_NAME, "Choose a TV first: click the TV button at the top right.")
            self.show_devices()
            return
        if not dev.online and not (self.conn is not None and self.conn.device is dev):  # connected = reachable
            QMessageBox.warning(self, APP_NAME, f"{dev.name} isn't available right now. Check that it's switched on.")
            return
        if self.connecting:
            return
        if self.conn is None or self.conn.device is not dev:
            self.connect_device(dev, then=lambda: self._start(path, start))
            return
        player = self.conn
        # Every start gets a number; only the newest may load on the TV. Rapid presses of
        # Back 10 s or settings changes used to race, and an older start could win.
        self.gen += 1
        gen = self.gen
        self.pending_seek = None
        if path != self.now_path:  # another video: a new chance for "Up next" and "Skip intro"
            self.upnext_for = None
            self._upnext_cancel(None)
            self.intro_for = None
            self._intro_cancel(None)
        self.text_off_until = None  # every load switches the subtitle track on again
        self.player = player
        self.now_path = path
        self.loading = True
        self.seen_playing = False
        self.play_state = "buffering"
        self.position = start
        self.duration = self.state["durations"].get(path) or 0
        self.state["last_played"] = path
        self._refresh_next()
        fs = self.file_settings(path)
        gs = dict(self.state["global"])
        gs["hls"] = dev.id not in self.state.get("hls_failed", [])  # skippable HLS, unless this TV can't
        gs["force_hls"] = bool(getattr(self, "weak_network", False))  # weak connection: adaptive for all
        # "Up next" countdown on the TV: the next video's name and where the credits begin (if known)
        nxt = self._has_next() if gs.get("up_next", True) else None
        gs["up_next_title"] = self._short_title(nxt) if nxt else None
        gs["credits"] = self.state.get("credits", {}).get(path)
        intro = self.state.get("intros", {}).get(path)  # "Skipping intro" countdown on the TV, if known
        gs["intro"] = intro if isinstance(intro, list) else None
        enc = self.encoder
        self._update_header(status)
        self._load_thumb(path, start + 5 if start else None)

        def work():
            try:
                info = be.probe(path)
                stream = be.prepare_stream(self.server, path, info, fs, gs, start, enc)
                png = be.grab_frame(path, start + 5 if start else (be.duration_of(info) or 60) * 0.1, 480)
                if png:
                    be.CACHE_DIR.mkdir(exist_ok=True)
                    tp = be.CACHE_DIR / f"thumb_{abs(hash(path)) % 10 ** 8}.png"
                    tp.write_bytes(png)
                    stream["thumb_url"] = self.server.register(str(tp), "thumb", name="thumb.png", mime="image/png")
                with self.load_lock:
                    if gen != self.gen:
                        return  # a newer start (or Stop) replaced this one
                    player.connect()
                    if stream["plan"]["mode"] != "direct":
                        self.bridge.call.emit(lambda: self._update_header(
                            "Converting..." if stream["plan"]["mode"] == "transcode" else "Starting..."))
                    # the old stream keeps playing until the new one is ready, then goes
                    self.server.stop_transcodes(keep=stream.get("hls_job"))
                    player.load(stream, start)
                self.bridge.call.emit(lambda: self._started(path, player, stream, info, gen))
                be.prefetch_subtitles(path, info)  # so switching subtitles later is quick
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                self.bridge.call.emit(lambda: self._failed(path, msg, gen))

        worker(work)

    def _started(self, path, player, stream, info, gen):
        if gen != self.gen:  # a newer start or Stop took over; it looks after the TV
            return
        self.player = player
        self.stream = stream
        if stream.get("credits") is not None:  # found while preparing (for the countdown on the TV)
            self.state.setdefault("credits", {})[path] = stream["credits"] or -1
        if self.state["global"].get("up_next", True):
            self._credits_for(path, info)
        if self.state["global"].get("skip_intro", True):
            self._intro_for(path)
        self.loading = False
        self.duration = be.duration_of(info) or self.duration
        if self.duration:
            self.state["durations"][path] = self.duration
        self.seek.duration = self.duration
        self.last_thumb = time.time()
        self.load_time = time.time()
        self.wd_pos, self.wd_time = self.position, time.time()
        be.log(f"playing {Path(path).name} from {self.position:.0f}s: {stream['plan']['mode']}"
               f"{' (prepared copy)' if stream.get('prepared') else ''}{' (live)' if stream['live'] else ''}"
               f"{' (HLS)' if stream.get('hls') else ''}")
        self.hls_deadline = time.time() + 30
        plan = stream["plan"]
        if stream["live"] or (stream.get("hls") and (plan["mode"] == "remux" or plan["audio_copy"])):
            # a live stream can't be skipped in; HLS re-encodes (video, and DD+ audio) - make the
            # seekable copy with the original video/audio in the background and switch when ready
            # make a copy the TV can seek in (remote skip, its own progress bar) and switch to it when ready
            self.preparer.start(path, stream["plan"], stream["fs"], stream.get("burn_file"), stream.get("burn_style"),
                                on_done=lambda key, p=path: self.bridge.call.emit(lambda: self._prepared(p, key)))
        self._update_header()
        self._update_buttons()

    def _prepared(self, path, key):
        """The seekable copy is ready: switch to it at the current spot (when playing)."""
        s = self.stream
        if path != self.now_path or not s or not (s["live"] or s.get("hls")) or s["plan"].get("key") != key:
            return
        if getattr(self, "weak_network", False) and s.get("hls"):
            return  # weak connection: stay adaptive (the full-quality copy would hang)
        if self.loading or self.play_state != "playing":
            self.prepared_pending = (path, key)  # switch once it plays again
            return
        self.prepared_pending = None
        be.log(f"switching to the prepared copy of {Path(path).name} at {self.position:.0f}s")
        self.flash("Ready - skipping with the TV remote works now", 5)
        self._start(path, self.position, status="Switching to the prepared video...")

    def _tv_restarted(self, entry):
        """The TV asked for the live stream again: its remote's skip does that, and it would
        start over from where the stream began. Continue where it was instead."""
        s = self.stream
        if not s or entry.get("token") != s.get("token") or self.loading or not self.now_path:
            return
        key = s["plan"].get("key")
        pct = f" ({round(self.preparer.progress * 100)}%)" if self.preparer.busy_with(key) else ""
        be.log(f"TV restarted the live stream (remote skip) at {self.position:.0f}s")
        self.flash(f"Skipping with the TV remote works once this video is prepared{pct}", 6)
        self._start(self.now_path, self.position, status="Continuing...")

    def _failed(self, path, msg, gen):
        if gen != self.gen:
            return
        self.loading = False
        self.player = None
        self.stream = None
        self.play_state = "idle"
        self.now_path = None
        self._update_header()
        self._update_buttons()
        self.list.viewport().update()
        QMessageBox.warning(self, APP_NAME, f"Could not start playback.\n\n{msg}")

    def stop(self, keep_header=False, picture=True):
        if self.screen is not None:  # Stop while the screen is on the TV ends that
            self.end_screen(stop_tv=True, picture=picture)
            return
        self._save_resume()
        self._upnext_cancel(None)
        self.gen += 1  # cancels a start that is still on its way to the TV
        self.pending_seek = None
        if self.player is not None:
            p = self.player
            splash = self.splash_url() if picture else None

            def work():
                with self.load_lock:  # after a load that is already in progress
                    self._safe(p.stop)
                    if splash:  # back to the Video Caster picture, like after connecting
                        self._safe(p.show_picture, splash)

            worker(work)
        self.server.stop_transcodes()
        self.stream = None
        self.play_state = "idle"
        self.loading = False
        self.player = None
        if not keep_header:
            self.now_path = None
        self._update_header()
        self._update_buttons()
        self.list.viewport().update()

    def play_next(self):
        cur = self.now_path or self.selected_path()
        items = self.playlist
        if cur in items:
            i = items.index(cur) + 1
        else:
            i = 0
        if i < len(items):
            self.list.clearSelection()
            self.list.item(i).setSelected(True)
            self.play_path(items[i], from_start=False)
        elif self.next_suggestion:
            self.play_suggestion()  # end of the playlist: carry on with the next episode on disk
        else:
            self.stop()

    def seek_relative(self, d):
        if self.player is not None:
            self.seek_to(self.position + d)

    def seek_to(self, t):
        if self.player is None or not self.now_path:
            return
        t = max(0.0, min(t, self.duration - 1 if self.duration else t))
        self.position = t
        self.wd_pos, self.wd_time = t, time.time()
        if self.loading or (self.stream and self.stream["live"]):
            # a live conversion restarts at the new spot; presses within 0.6 s add up to one restart
            self.pending_seek = t
            self.flash(f"Going to {be.fmt_time(t)}...", 3)
            self.seek_timer.start()
        else:
            worker(self._safe, self.player.seek, t)
        self._load_thumb(self.now_path, t)

    def _do_pending_seek(self):
        if self.pending_seek is not None and self.now_path and self.player is not None:
            t = self.pending_seek
            self._start(self.now_path, t, status=f"Going to {be.fmt_time(t)}...")

    def change_volume(self, d):
        if self.conn is None:
            return
        player = self.conn

        def work():
            v = player.volume()
            if v is not None:
                nv = max(0.0, min(1.0, v + d))
                player.set_volume(nv)
                self.bridge.call.emit(lambda: self.flash(f"Volume {round(nv * 100)}%"))

        worker(work)

    def _tv_downloading(self):
        """Did the TV fetch video from us in the last few seconds?"""
        stats = (self.stream or {}).get("stats") or {}
        return bool(stats.get("last")) and time.time() - stats["last"] < 6

    def _download_kbps(self):
        stats = (self.stream or {}).get("stats") or {}
        now, sent = time.time(), stats.get("sent", 0)
        prev = getattr(self, "_rate_sample", None)
        self._rate_sample = (now, sent)
        if prev and now - prev[0] > 1:
            return (sent - prev[1]) * 8 / (now - prev[0]) / 1000
        return None

    def _weak_connection(self):
        """The TV is buffering while still downloading: the connection is too slow for this
        quality. Adaptive HLS lets the TV lower the quality itself; anything else switches to it."""
        self.wd_time = time.time()  # look again in a while
        kbps = self._download_kbps()
        rate = f"{kbps:.0f} kbit/s" if kbps is not None else "?"
        if self.stream and self.stream.get("hls"):
            if time.time() - getattr(self, "_weak_logged", 0) > 60:
                self._weak_logged = time.time()
                be.log(f"weak connection at {self.position:.0f}s (TV still downloading, {rate}) - "
                       "the TV lowers the quality by itself")
                self.flash("Weak connection - the TV lowers the quality", 6)
            return
        be.log(f"weak connection at {self.position:.0f}s ({rate}, needs ~{(self.stream or {}).get('kbps', 0):.0f}) - "
               "switching to adaptive streaming")
        self.weak_network = True  # for the rest of this session: adaptive HLS for everything
        self.prepared_pending = None
        self.flash("Weak connection - switching to adaptive streaming", 6)
        self._start(self.now_path, self.position, status="Weak connection - adapting...")

    def _hls_fallback(self, why):
        """HLS doesn't work on this TV: remember that and continue with the live stream."""
        dev = self.current_device()
        be.log(f"HLS failed on {dev.name if dev else '?'} ({why}) - using the live stream from now on")
        if dev is not None:
            failed = set(self.state.get("hls_failed", []))
            failed.add(dev.id)
            self.state["hls_failed"] = sorted(failed)
            self.save()
        self.flash("Switching to another way of streaming...", 5)
        self._start(self.now_path, self.position, status="Switching to another way of streaming...")

    def _finished(self):
        """The video played to the end: mark it watched and go on with the next one."""
        be.log(f"finished {Path(self.now_path).name} at {self.position:.0f}/{self.duration:.0f}s; "
               f"next: {Path(self.next_suggestion).name if self.next_suggestion else 'playlist / none'}")
        self.state["resume"][self.now_path] = self.duration or self.position
        self.save()
        self.play_state = "idle"
        self._play_next_with_card()

    def _recover(self):
        path, pos, dev = self.now_path, self.position, self.current_device()
        if not path or dev is None:
            return
        self.last_recover = time.time()
        be.log(f"TV stuck at {pos:.0f}s - restarting the receiver")
        self.gen += 1
        self.server.stop_transcodes()
        self.player = None
        self.conn = None
        self.loading = False
        self.flash("The TV got stuck - restarting it...", 8)
        self.connect_device(dev, then=lambda: self._start(path, pos))

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except Exception:
            pass

    def _save_resume(self):
        if self.now_path and self.position > 5:
            credits = self.state.get("credits", {}).get(self.now_path)
            watched = credits and credits > 0 and self.position >= credits and self.duration
            self.state["resume"][self.now_path] = self.duration if watched else self.position  # credits = watched
            self.save()

    # ----- up next at the end credits
    def _credits_for(self, path, info=None):
        """Find (once, in the background) where this video's end credits begin."""
        credits = self.state.setdefault("credits", {})
        if path in credits:
            return

        def work():
            c = be.detect_credits(path, info)
            be.log(f"credits of {Path(path).name}: {be.fmt_time(c) if c else 'not found'}")
            self.bridge.call.emit(lambda: credits.__setitem__(path, c or -1))

        worker(work)

    def _has_next(self):
        items, cur = self.playlist, self.now_path
        if cur in items and items.index(cur) + 1 < len(items):
            return items[items.index(cur) + 1]
        if self.next_suggestion and cur == self.next_anchor:
            return self.next_suggestion
        return None

    def _check_credits(self):
        """Called while playing: at the end credits, count down to the next video."""
        c = self.state.get("credits", {}).get(self.now_path)
        if not c or c < 0 or not self.state["global"].get("up_next", True) or self.position < c:
            return
        if getattr(self, "upnext_for", None) == self.now_path:
            return  # shown (or cancelled) for this video already
        nxt = self._has_next()
        if not nxt:
            return
        self.upnext_for = self.now_path
        self.upnext_next = nxt
        self.upnext_left = 10
        be.log(f"credits of {Path(self.now_path).name} at {self.position:.0f}s - up next: {Path(nxt).name}")
        self._upnext_show()
        if not hasattr(self, "upnext_timer"):
            self.upnext_timer = QTimer(self, interval=1000, timeout=self._upnext_tick)
        self.upnext_timer.start()

    @staticmethod
    def _short_title(path):
        """'Off Campus S01E06' for an episode file, else the file name without extension."""
        name = Path(path).stem
        m = be._EPISODE.search(name)
        if m:
            return f"{name[:m.start()].replace('.', ' ').replace('_', ' ').strip()} {m.group(0).upper()}"
        return name

    def _upnext_show(self):
        short = self._short_title(self.upnext_next)
        fm = QFontMetrics(self.upnext_label.font())
        text = f"Up next: {short} - starting in {self.upnext_left} s"
        self.upnext_label.setText(fm.elidedText(text, Qt.ElideMiddle, max(120, self.upnext_label.width())))
        self.upnext_bar.show()

    def _upnext_tick(self):
        if self.player is None or self.now_path != self.upnext_for:
            self._upnext_cancel(None)
            return
        if self.play_state == "paused":
            self._upnext_cancel("paused on the TV - staying on this episode")
            return
        c = self.state.get("credits", {}).get(self.now_path) or 0
        if self.position < c - 5:
            self._upnext_cancel("went back - staying on this episode")
            return
        self.upnext_left -= 1
        if self.upnext_left <= 0:
            self._upnext_go()
        else:
            self._upnext_show()

    def _upnext_go(self):
        if hasattr(self, "upnext_timer"):
            self.upnext_timer.stop()
        self.upnext_bar.hide()
        if self.now_path and self.now_path == getattr(self, "upnext_for", None):
            be.log(f"up next: playing {Path(self.upnext_next).name}")
            self.state["resume"][self.now_path] = self.duration or self.position  # watched
            self.save()
            self._play_next_with_card()

    def _upnext_cancel(self, why):
        if hasattr(self, "upnext_timer"):
            self.upnext_timer.stop()
        if not self.upnext_bar.isHidden() and why:
            be.log(f"up next cancelled: {why}")
            self.flash(f"Up next {why}" if why == "cancelled" else why.capitalize(), 4)
            self._hide_tv_countdown()
        self.upnext_bar.hide()

    def _hide_tv_countdown(self, window="upnext_window"):
        """A countdown is also on the TV (as subtitle lines): switch those off now. They come
        back (with the real subtitles) once the video is past the countdown - by the video's
        position, not a clock, since cancelling by pausing stops the video's time."""
        s, player = self.stream, self.player
        if not s or not player or not s.get(window) or not s.get("sub_url") or not hasattr(player, "hide_text"):
            return
        worker(self._safe, player.hide_text)
        self.text_off_from, self.text_off_until = s[window][0], s[window][1] + 0.3

    def _tv_text_check(self):
        """While playing: switch the subtitle track back on after a cancelled countdown, and allow
        a new countdown when the viewer goes back to before the credits."""
        s = self.stream or {}
        w = s.get("upnext_window")
        if w and self.position < w[0] - 5 and getattr(self, "upnext_for", None) == self.now_path:
            self.upnext_for = None  # the credits come again: count down again
        until = getattr(self, "text_off_until", None)
        if until is None:
            return
        back = self.position < getattr(self, "text_off_from", 0.0) - 5
        if self.position >= until or back:
            self.text_off_until = None
            # back on if it holds real subtitles, or a countdown still to come
            ahead = any(win and win[0] > self.position for win in (s.get("upnext_window"), s.get("intro_window")))
            if s.get("sub_has_text") or back or ahead:
                worker(self._safe, self.player.set_sub_style, s.get("sub_style"))

    # ----- skipping a series' opening titles
    def _intro_for(self, path):
        """Find (once, in the background) where a series episode's opening titles are - and, from
        the same comparison, those of the other episode (usually the next one)."""
        intros = self.state.setdefault("intros", {})
        if path in intros or path in self.intro_busy or not be._EPISODE.search(Path(path).stem):
            return
        self.intro_busy.add(path)

        def work():
            r = be.detect_intro(path)
            if r:
                (s, e), partner, (ps, pe) = r
                be.log(f"intro of {Path(path).name}: {be.fmt_time(s)}-{be.fmt_time(e)} "
                       f"(compared with {Path(partner).name}: {be.fmt_time(ps)}-{be.fmt_time(pe)})")
            elif r is False:
                be.log(f"intro of {Path(path).name}: none (no opening titles shared with another episode)")

            def done():
                self.intro_busy.discard(path)
                if r:
                    intros[path] = [s, e]
                    intros.setdefault(partner, [ps, pe])
                elif r is False:
                    intros[path] = -1
                # None: couldn't check (no other episode yet): look again next time

            self.bridge.call.emit(done)

        worker(work)

    def _check_intro(self):
        """Called while playing: at a series' opening titles, count down and skip them."""
        iv = self.state.get("intros", {}).get(self.now_path)
        if not isinstance(iv, list) or not self.state["global"].get("skip_intro", True):
            return
        start, end = iv
        if self.position < start - 5 and self.intro_for == self.now_path:
            self.intro_for = None  # back before the intro: it may be skipped again
        if self.intro_for == self.now_path or not start - 0.5 <= self.position <= end - be.INTRO_SECS - 2:
            return
        self.intro_for = self.now_path
        self.intro_range = (start, end)
        self.intro_left = be.INTRO_SECS
        be.log(f"intro of {Path(self.now_path).name} at {self.position:.0f}s - skipping to {be.fmt_time(end)}")
        self._intro_show()
        if not hasattr(self, "intro_timer"):
            self.intro_timer = QTimer(self, interval=1000, timeout=self._intro_tick)
        self.intro_timer.start()

    def _intro_show(self):
        self.intro_label.setText(f"Skipping intro in {self.intro_left} s")
        self.intro_bar.show()

    def _intro_tick(self):
        if self.player is None or self.now_path != self.intro_for:
            self._intro_cancel(None)
            return
        if self.play_state == "paused":
            self._intro_cancel("paused on the TV - the intro plays")
            return
        start, end = self.intro_range
        if not start - 5 <= self.position < end:
            self._intro_cancel(None)  # jumped away
            return
        self.intro_left -= 1
        if self.intro_left <= 0:
            self._intro_go()
        else:
            self._intro_show()

    def _intro_go(self):
        if hasattr(self, "intro_timer"):
            self.intro_timer.stop()
        self.intro_bar.hide()
        if self.now_path and self.now_path == self.intro_for and self.position < self.intro_range[1]:
            be.log(f"intro skipped: {Path(self.now_path).name} to {be.fmt_time(self.intro_range[1])}")
            self.seek_to(self.intro_range[1])
            self.flash("Intro skipped", 3)

    def _intro_cancel(self, why):
        if hasattr(self, "intro_timer"):
            self.intro_timer.stop()
        if not self.intro_bar.isHidden() and why:
            be.log(f"skip intro cancelled: {why}")
            self.flash(why[0].upper() + why[1:], 4)
            self._hide_tv_countdown("intro_window")
        self.intro_bar.hide()

    def _play_next_with_card(self):
        """Show an 'Up next' card on the TV (instead of a black screen) while the next video loads."""
        nxt, player = self._has_next(), self.player
        if not nxt or player is None or not hasattr(player, "show_picture"):
            self.play_next()
            return
        self.loading = True  # no status checks while the card is up
        title = self._short_title(nxt)

        def work():
            try:
                png = be.grab_frame(nxt, 60.0, 960)
                card = be.CACHE_DIR / "upnext_card.png"
                _upnext_card(title, png).save(str(card))
                url = self.server.register(str(card), "media", name="upnext.png", mime="image/png")
                player.show_picture(url, title=f"Up next: {title}")
            except Exception:
                pass
            self.bridge.call.emit(self.play_next)

        worker(work)

    def _poll(self):
        if self.player is None or self.loading:
            return
        player = self.player
        if player.kind == "appletv":  # pyatv asks the device: don't block the window
            if not getattr(self, "_atv_polling", False):
                self._atv_polling = True

                def work():
                    try:
                        res = player.state()
                    finally:
                        self._atv_polling = False
                    self.bridge.call.emit(lambda: self._apply_state(player, *res))

                worker(work)
            return
        if int(time.time()) % 5 == 0:
            player.refresh()
        self._apply_state(player, *player.state())

    def _apply_state(self, player, st, pos):
        if player is not self.player:
            return
        if (self.stream and self.stream.get("hls") and not self.seen_playing and self.pending_seek is None
                and (st == "error" or time.time() > getattr(self, "hls_deadline", time.time() + 1))):
            fetched = bool(((self.stream or {}).get("stats") or {}).get("first"))
            if st != "error" and fetched and time.time() - self.load_time < 90:
                # the TV is fetching pieces: HLS works, the conversion is just slow to start
                # (a 4K video after a jump, say) - keep waiting rather than give HLS up
                self.hls_deadline = time.time() + 10
                self._update_header("Converting - the first pieces take a while...")
                return
            self._hls_fallback("the TV reported an error" if st == "error" else
                               "no picture within 90 s" if fetched else "the TV fetched nothing within 30 s")
            return
        if st == "loading" or self.pending_seek is not None:  # TV hasn't reported on this stream yet
            self._update_header()
            return
        offset = self.stream["offset"] if self.stream else 0.0
        now = time.time()
        if st in ("playing", "paused", "buffering"):
            self.seen_playing = self.seen_playing or st == "playing"
            self.play_state = st
            live = bool(self.stream and self.stream["live"])
            if live and offset + pos < self.position - 5:
                # a live stream the TV restarted (remote skip) shows a jump back to where it began;
                # keep the real spot - the app continues there (_tv_restarted)
                pass
            else:
                self.position = offset + pos
            if st == "playing" and self.prepared_pending:
                self._prepared(*self.prepared_pending)
                if self.loading:
                    return
            if st == "playing":
                self._tv_text_check()
                self._check_intro()
                self._check_credits()
        # At the end of a converted (live) stream the TV doesn't always say "finished":
        # it may stop, go idle or report an error. Within the last seconds, any of those is the end.
        near_end = bool(self.duration) and self.seen_playing and self.position >= self.duration - 6
        if st in ("playing", "paused", "buffering"):
            if st == "paused" or abs(self.position - self.wd_pos) > 0.4:
                self.wd_pos, self.wd_time = self.position, now
            elif near_end and now - self.wd_time > 4:
                self._finished()
                return
            # Watchdog: the TV's receiver can get stuck (sound, no picture, clock frozen).
            # Restarting the receiver fixes it, so do that and carry on from the same spot.
            elif (not near_end and now - self.wd_time > 12 and now - self.load_time > 15
                  and (self.seen_playing or now - self.load_time > 30)):
                if self._tv_downloading():
                    # still fetching video: a weak connection, not a stuck TV - don't restart anything
                    self._weak_connection()
                    if self.loading:
                        return
                elif now - self.last_recover > 60:
                    self._recover()  # frozen and not fetching anything: the receiver is stuck
                    return
            if time.time() - self.last_resume_save > 5:
                self.last_resume_save = time.time()
                self._save_resume()
            if self.state["global"].get("scrubbing", True) and st == "playing" and time.time() - self.last_thumb > 45:
                self.last_thumb = time.time()
                self._load_thumb(self.now_path, self.position)
        elif (st == "finished" and self.seen_playing) or (near_end and st in ("idle", "error")):
            self._finished()
            return
        elif st == "error":
            path = self.now_path
            be.log(f"TV reported an error for {Path(path).name if path else '?'} at {self.position:.0f}s")
            dev = self.current_device()
            retried = self.__dict__.setdefault("hls_retried", set())
            if (self.stream and not self.stream.get("hls") and dev is not None and dev.id not in retried
                    and dev.id in self.state.get("hls_failed", [])):
                # the live stream (used since HLS once seemed not to work here) fails too: that mark
                # was wrong - forget it and try HLS again, once
                retried.add(dev.id)
                self.state["hls_failed"] = [d for d in self.state["hls_failed"] if d != dev.id]
                self.save()
                be.log(f"the live stream doesn't work on {dev.name} either - trying HLS again")
                self._start(path, self.position, status="Trying another way of streaming...")
                return
            self.stop(keep_header=True)
            QMessageBox.warning(self, APP_NAME,
                                f"The TV couldn't play {Path(path).name if path else 'this video'}.\n\n"
                                "Open the settings (gear button) and tick Force Conversion, or turn off "
                                "H.265 Native Playback, then play it again.")
            return
        elif st == "idle" and self.seen_playing:  # stopped on the TV, or another app took over: leave it
            be.log(f"TV went idle at {self.position:.0f}/{self.duration:.0f}s (stopped on the TV or another app)")
            self.stop(keep_header=True, picture=False)
            return
        self._update_header()
        self._update_buttons()

    # ----- header, thumbnail, scrubbing
    def flash(self, text, secs=2.5):
        self.message_until = time.time() + secs
        self.time.setText(text)

    def _update_tv_chip(self):
        """The TV chip in the header: which TV, and whether it's connected."""
        dev = self.current_device()
        connected = dev is not None and self.conn is not None and self.conn.device is dev
        if dev is None:
            state = ("none",)
        else:
            state = ("on" if connected else "connecting" if self.connecting else "ready" if dev.online else "off",
                     dev.name)
        if state == self.tv_chip_state:
            return
        self.tv_chip_state = state
        if dev is None:
            self.btn_cast.setIcon(draw_icon("cast", QColor("white"), 14))
            self.btn_cast.setText("Choose a TV")
            self.btn_cast.setToolTip("Choose the TV for your videos and your screen")
        else:
            kind = state[0]
            self.btn_cast.setIcon(dot_icon({"on": "#4cd964", "connecting": "#f5c242", "ready": "#c9c9d1",
                                            "off": "#9a9aa6"}[kind], hollow=kind == "off"))
            self.btn_cast.setText(QFontMetrics(self.btn_cast.font()).elidedText(dev.name, Qt.ElideRight, 130))
            self.btn_cast.setToolTip({"on": f"Connected to {dev.name}: volume, disconnect, speed test",
                                      "connecting": f"Connecting to {dev.name}...",
                                      "ready": f"{dev.name}: connects when you play something or share your "
                                               "screen. Click to choose another TV.",
                                      "off": f"{dev.name} isn't available right now. Click to choose a TV."}[kind])

    def _update_header(self, status=None):
        self._update_tv_chip()
        if self.screen is not None:
            s = self.screen
            self.title.setText("TV display" if s.get("tv") else "Your screen"
                               if s.get("single", len(QGuiApplication.screens()) == 1) else f"Screen {s['index'] + 1}")
            if status:
                self.time.setText(status)
            elif time.time() >= self.message_until:
                self.time.setText(f"{'Mirroring' if s.get('mirror') else 'Casting'} to {s['player'].device.name}"
                                  + ("" if s["playing"] else " - starting..."))
            self.seek.duration = 0
            self.seek.set_fraction(0)
            self._update_live(s)
            return
        self.live_bar.hide()
        path = self.now_path or self.selected_path()
        name = Path(path).name if path else APP_NAME
        fm = QFontMetrics(self.title.font())
        self.title.setText(fm.elidedText(name, Qt.ElideRight, max(80, self.header.width() - 24)))
        if time.time() < self.message_until and status is None:
            pass
        elif status:
            self.time.setText(status)
        elif self.player is not None and self.now_path:
            dur = self.duration
            label = f"{be.fmt_time(self.position)} / {be.fmt_time(dur)}" if dur else be.fmt_time(self.position)
            if self.play_state == "paused":
                label += "   Paused"
            elif self.play_state == "buffering":
                label += "   Loading..."
            self.time.setText(label)
        else:
            self.time.setText("Not Playing")
        self.seek.duration = self.duration if self.player is not None else 0
        self.seek.set_fraction(self.position / self.duration if (self.player is not None and self.duration) else 0)

    def _update_live(self, s):
        """The live bar while the screen is shared: what's on which TV, how far behind, sound."""
        tv = s["player"].device.name
        single = s.get("single", len(QGuiApplication.screens()) == 1)
        if s.get("tv"):
            title = f"{tv} is your second display"
        else:
            title = f"Your screen is on {tv}" if single else f"Screen {s['index'] + 1} is on {tv}"
        if not s["playing"]:
            delay = "Starting..."
        elif s.get("mirror"):
            delay = f"About {be.MIRROR_DELAY_MS / 1000:.1f} s behind"
        else:
            delay = "About 6 s behind"
        sound = ("PC sound on - but this PC is muted" if s.get("muted") else "PC sound on") if s["sound"] else "No sound"
        self.live_title.setText(title)
        self.live_title.setToolTip("Move the mouse past the right edge of your screen to reach it; drag windows there"
                                   if s.get("tv") else "Everything on this screen shows on the TV")
        self.live_sub.setText(f"{delay} · {sound}")
        self.live_sound.setIcon(draw_icon("speaker" if s["sound"] else "speaker-off", QColor("white"), 18))
        self.live_sound.setToolTip("Stop sending the PC's sound" if s["sound"] else "Send the PC's sound too")
        self.live_bar.show()

    def _update_buttons(self):
        """Grey out what can't be used now, like Airflow: back, stop and next only while a
        video is on the TV; next only if something comes after it."""
        if self.screen is not None:  # the screen on the TV: only Stop (and the screen menu)
            self.btn_play.setIcon(draw_icon("play", ACCENT))
            for b in (self.btn_back, self.btn_next, self.btn_play):
                b.setEnabled(False)
            self.btn_stop.setEnabled(True)
            return
        playing = self.player is not None and self.play_state in ("playing", "buffering")
        self.btn_play.setIcon(draw_icon("pause" if playing else "play", ACCENT))
        active = self.player is not None and bool(self.now_path)
        items = self.playlist
        has_next = active and ((self.now_path in items and items.index(self.now_path) + 1 < len(items))
                               or bool(self.next_suggestion))
        self.btn_back.setEnabled(active)
        self.btn_stop.setEnabled(active)
        self.btn_next.setEnabled(has_next)
        self.btn_play.setEnabled(active or bool(items))

    def _load_thumb(self, path, t):
        if not path:
            return

        def work():
            info = be.probe(path)
            when = t if t is not None else (float(self.state["resume"].get(path) or 0)
                                            or (be.duration_of(info) or 60) * 0.1)
            png = be.grab_frame(path, when, 400)
            self.bridge.call.emit(lambda: self.thumb.set_png(png) if path in (self.now_path, self.selected_path()) else None)

        worker(work)

    def _scrubbing(self, f):
        t = f * self.duration
        self.time.setText(f"{be.fmt_time(t)} / {be.fmt_time(self.duration)}")
        self.message_until = time.time() + 1.5
        if not self.state["global"].get("scrubbing", True) or not self.now_path:
            return
        self.scrub_want = t
        if self.scrub_busy:
            return
        self.scrub_busy = True
        path = self.now_path

        def work():
            while True:
                want = self.scrub_want
                png = be.grab_frame(path, want, 320)
                self.bridge.call.emit(lambda png=png: self.thumb.set_png(png))
                if self.scrub_want == want:
                    break
            self.scrub_busy = False

        worker(work)

    # ----- about / troubleshooting
    def _detect_encoder(self):
        enc = be.detect_encoder()
        self.bridge.call.emit(lambda: setattr(self, "encoder", enc))

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b><br>Plays videos from this PC on a Chromecast or Apple TV.<br><br>"
                          "Drop videos or folders on the window, choose the TV with the TV button and press play. "
                          "Videos the TV can't play are converted while they play.<br><br>"
                          "Keys: Space play/pause, Left/Right skip, Up/Down TV volume, Delete remove.")

    def show_troubleshooting(self):
        ff = shutil.which("ffmpeg") or "not found"
        lines = [
            f"{APP_NAME} on Python {platform.python_version()} ({sys.executable})",
            f"ffmpeg: {ff}",
            f"Video encoder: {self.encoder}",
            f"Media server: {self.server.base_url()} (the TV must be able to reach this address;"
            " allow Python through Windows Firewall on private networks)",
            "",
            "Devices:",
        ]
        for d in self.discovery.snapshot():
            lines.append(f"  {d.name}: {d.describe()}")
        if self.now_path and self.stream:
            plan = self.stream["plan"]
            lines += ["", f"Playing: {self.now_path}", f"How: {plan['mode']} - {plan['detail']}"]
        dlg = QDialog(self)
        dlg.setWindowTitle("Troubleshooting")
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit("\n".join(lines))
        txt.setReadOnly(True)
        txt.setMinimumSize(560, 260)
        lay.addWidget(txt)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(txt.toPlainText()))
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()


def main():
    be.refresh_windows_path()
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--screenshot", help="save a PNG of the window and exit")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="settings and playlists file")
    parser.add_argument("--no-discovery", action="store_true", help="don't search the network for TVs")
    parser.add_argument("--check-device", metavar="NAME", help="check a TV connection without starting playback, then exit")
    parser.add_argument("--report", help="JSON report path for --check-device")
    parser.add_argument("--install-display-driver", metavar="RESULT",
                        help="(the app starts this itself, with admin rights) install the bundled virtual display "
                             "driver for 'Use the TV as a second display', write the outcome to RESULT, exit")
    parser.add_argument("--uninstall-display-driver", metavar="RESULT",
                        help="(Video Caster's uninstaller runs this, with admin rights) remove the virtual display "
                             "driver if Video Caster installed it; RESULT: outcome file, or - for none")
    parser.add_argument("files", nargs="*", help="videos or folders to add")
    args = parser.parse_args()

    if args.install_display_driver:
        out = be.install_display_driver_elevated(args.install_display_driver)
        sys.exit(0 if out.get("ok") else 1)
    if args.uninstall_display_driver:
        out = be.uninstall_display_driver_elevated(args.uninstall_display_driver)
        sys.exit(0 if out.get("ok") else 1)

    if args.check_device:
        import logging
        import traceback
        report_path = Path(args.report) if args.report else be.DATA_DIR / "connection-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=str(report_path.with_suffix(".log")), level=logging.INFO,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s", encoding="utf-8")
        discovery = be.Discovery(lambda: None, load_state(args.state).get("known_devices", []))
        report = {"device": args.check_device, "connected": False, "devices": [],
                  "import_errors": be.NETWORK_IMPORT_ERRORS,
                  "chromecast_available": be.pychromecast is not None, "airplay_available": be.pyatv is not None}
        try:
            discovery.start()
            deadline = time.monotonic() + 12
            dev = None
            while time.monotonic() < deadline:
                dev = next((d for d in discovery.snapshot()
                            if d.name.casefold() == args.check_device.casefold() and d.online and d.obj), None)
                if dev:
                    break
                time.sleep(0.2)
            report["devices"] = [{"name": d.name, "kind": d.kind, "host": d.host} for d in discovery.snapshot()]
            if dev is None:
                raise RuntimeError(f"{args.check_device} was not found on this network.")
            player = be.make_player(dev, discovery)
            player.connect(fresh=False)
            report["connected"] = True
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            for d in discovery.snapshot():
                if d.kind == "chromecast" and d.obj:
                    d.obj.socket_client.stop.set()
            discovery.stop()
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        sys.exit(0 if report["connected"] else 1)

    if sys.platform == "win32":  # the taskbar shows the app's own icon, not Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoCaster.App")
        except Exception:
            pass
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI", 9))
    win = MainWindow(args.state, discover=not args.no_discovery)
    if args.files:
        win.add_paths(args.files)
    win.show()
    if args.screenshot:
        def snap():
            win.grab().save(args.screenshot)
            win.close()
            app.quit()
        QTimer.singleShot(2500, snap)
    code = app.exec()
    # Everything is saved by now. A network library thread still waiting for a TV that
    # doesn't answer must not keep an invisible app running: then leave right away.
    if any(t.is_alive() and not t.daemon for t in threading.enumerate() if t is not threading.main_thread()):
        os._exit(code)
    sys.exit(code)


if __name__ == "__main__":
    main()
