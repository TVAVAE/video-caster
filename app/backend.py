"""Video Caster engine: finds TVs, serves and converts video for them, prepares
subtitles and drives playback. No window code lives here (that is main.py)."""

from __future__ import annotations

from fractions import Fraction

import asyncio
import base64
import hashlib
import json
import math
import mimetypes
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode

NETWORK_IMPORT_ERRORS = {}

try:
    import pychromecast
    import zeroconf
    from pychromecast.discovery import CastBrowser, SimpleCastListener
except Exception:  # pragma: no cover - the app still runs without Chromecast support
    pychromecast = None
    NETWORK_IMPORT_ERRORS["chromecast"] = traceback.format_exc()

try:
    import pyatv
    from pyatv.const import DeviceState
except Exception:  # pragma: no cover
    pyatv = None
    NETWORK_IMPORT_ERRORS["airplay"] = traceback.format_exc()

APP_NAME = "Video Caster"
APP_DIR = Path(__file__).resolve().parent
# A one-file executable extracts its code into a temporary directory. Keep user
# data outside that directory so upgrades and closing the app cannot erase it.
if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Video Caster"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = APP_DIR
CACHE_DIR = DATA_DIR / "cache"

# Keeps ffmpeg/ffprobe from flashing a console window on Windows.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_JOB = None
_JOB_LOCK = threading.Lock()


def adopt(proc):
    """Tie a child process (ffmpeg) to this app: Windows ends it the moment the app process
    goes away, however it ends - a crash or a forced close included. Without this a screen
    capture or conversion could keep running unseen. Returns proc."""
    global _JOB
    if sys.platform != "win32" or proc is None:
        return proc
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        with _JOB_LOCK:
            if _JOB is None:
                class IoCounters(ctypes.Structure):
                    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

                class Basic(ctypes.Structure):
                    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                                ("SchedulingClass", wintypes.DWORD)]

                class Extended(ctypes.Structure):
                    _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                                ("PeakJobMemoryUsed", ctypes.c_size_t)]

                k32.CreateJobObjectW.restype = wintypes.HANDLE
                job = k32.CreateJobObjectW(None, None)
                info = Extended()
                info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                    return proc  # 9: JobObjectExtendedLimitInformation
                _JOB = job
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject(_JOB, int(proc._handle))
    except Exception:
        pass
    return proc

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv", ".3gp"}
SUB_EXTS = {".srt", ".vtt"}

# What a Chromecast plays as-is (kept conservative); anything else goes through ffmpeg.
DIRECT_CONTAINERS = {".mp4", ".m4v", ".webm"}
DIRECT_VIDEO = {"h264", "vp8", "vp9"}
DIRECT_PIX_FMTS = {"yuv420p", "yuvj420p"}
HEVC_PIX_FMTS = {"yuv420p", "yuvj420p", "yuv420p10le"}
DIRECT_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac"}
MP4_COPY_AUDIO = {"aac", "mp3"}
DOLBY_AUDIO = {"ac3", "eac3"}  # sent untouched with Surround = Passthrough
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

# Settings kept per video file (the left half of the settings panel and the picture options).
FILE_DEFAULTS = {
    "audio_track": 0,
    "surround": "stereo",      # stereo | surround
    "volume": "normal",        # normal | boost | normalize
    "audio_delay": 0.0,        # seconds; positive = audio later
    "subtitle": "auto",        # auto | none | ext:<path> | emb:<subtitle stream index>
    "sub_encoding": "auto",
    "sub_render": "soft",      # soft | burn
    "sub_size": 100,
    "sub_color": "White",
    "sub_delay": 0.0,
    "deinterlace": "none",     # none | yadif
    "aspect": "default",
    "quality": "original",     # original | 1080 | 720 | 480
    "force_convert": False,
}
# Settings for the whole app (the right half of the settings panel).
GLOBAL_DEFAULTS = {
    "surround": "stereo",      # stereo | surround | passthrough (Dolby DD/DD+ untouched)
    "accel_decode": True,
    "accel_encode": True,
    "scrubbing": True,
    "hevc_native": False,      # turn on when the TV plays H.265 itself
    "up_next": True,           # at the end credits: count down and play the next episode
    "skip_intro": True,        # a series' opening titles (found by comparing episodes): skipped
    "screen_sound": True,      # casting the PC screen: with the PC's sound
    "screen_mirror": True,     # ...to a Chromecast: Google's mirroring (well under a second behind)
    "sub_font": "Sans-serif",  # subtitle font and style: for all videos
    "sub_font_style": "Normal",
}

# Subtitle fonts: name -> (Chromecast generic family, Chromecast font, Windows font for burned-in)
# (the seven font styles Cast receivers carry)
SUB_FONTS = {
    "Sans-serif": ("SANS_SERIF", "Droid Sans", "Arial"),
    "Sans-serif monospace": ("MONOSPACED_SANS_SERIF", "Droid Sans Mono", "Consolas"),
    "Serif": ("SERIF", "Droid Serif", "Times New Roman"),
    "Serif monospace": ("MONOSPACED_SERIF", "Cutive Mono", "Courier New"),
    "Casual": ("CASUAL", "Short Stack", "Comic Sans MS"),
    "Cursive": ("CURSIVE", "Quintessential", "Segoe Script"),
    "Small capitals": ("SMALL_CAPITALS", "Alegreya Sans SC", "Arial"),
}
# style name -> (Chromecast fontStyle, ASS bold, ASS italic)
SUB_FONT_STYLES = {
    "Normal": ("NORMAL", 0, 0),
    "Bold": ("BOLD", -1, 0),
    "Italic": ("ITALIC", 0, -1),
    "Bold italic": ("BOLD_ITALIC", -1, -1),
}
SUB_STYLE_KEYS = ("sub_size", "sub_color", "sub_font", "sub_font_style")  # change live on the TV

# name -> (Chromecast RGBA, ASS &HAABBGGRR)
SUB_COLORS = {
    "White": ("#FFFFFFFF", "&H00FFFFFF"),
    "Yellow": ("#FFFF00FF", "&H0000FFFF"),
    "Green": ("#00FF00FF", "&H0000FF00"),
    "Cyan": ("#00FFFFFF", "&H00FFFF00"),
}

def subtitle_style(fs, gs):
    """The Chromecast textTrackStyle for these settings (size and colour per video, font for all)."""
    fs = {**FILE_DEFAULTS, **(fs or {})}
    gs = {**GLOBAL_DEFAULTS, **(gs or {})}
    family, font, _ = SUB_FONTS.get(gs["sub_font"], SUB_FONTS["Sans-serif"])
    weight = SUB_FONT_STYLES.get(gs["sub_font_style"], SUB_FONT_STYLES["Normal"])[0]
    return {
        "fontScale": max(0.3, float(fs["sub_size"]) / 100.0),
        "foregroundColor": SUB_COLORS.get(fs["sub_color"], SUB_COLORS["White"])[0],
        "backgroundColor": "#00000000",
        "edgeType": "OUTLINE",
        "edgeColor": "#000000FF",
        "fontGenericFamily": family,
        "fontFamily": font,
        "fontStyle": weight,
    }


def burn_style(fs, gs):
    """libass force_style for burned-in subtitles (Windows fonts)."""
    fs = {**FILE_DEFAULTS, **(fs or {})}
    gs = {**GLOBAL_DEFAULTS, **(gs or {})}
    font = SUB_FONTS.get(gs["sub_font"], SUB_FONTS["Sans-serif"])[2]
    _, bold, italic = SUB_FONT_STYLES.get(gs["sub_font_style"], SUB_FONT_STYLES["Normal"])
    color = SUB_COLORS.get(fs["sub_color"], SUB_COLORS["White"])[1]
    return (f"FontName={font},FontSize={round(20 * float(fs['sub_size']) / 100)},PrimaryColour={color},"
            f"Bold={bold},Italic={italic}")


SUB_ENCODINGS = [
    ("auto", "Automatic"), ("utf-8", "Unicode (UTF-8)"), ("cp1252", "Western (Windows-1252)"),
    ("cp1250", "Central European (Windows-1250)"), ("cp1251", "Cyrillic (Windows-1251)"),
    ("cp1253", "Greek (Windows-1253)"), ("cp1254", "Turkish (Windows-1254)"),
    ("cp1255", "Hebrew (Windows-1255)"), ("cp1256", "Arabic (Windows-1256)"),
    ("iso-8859-1", "Western (ISO-8859-1)"), ("iso-8859-2", "Central European (ISO-8859-2)"),
    ("gb18030", "Chinese Simplified (GB18030)"), ("big5", "Chinese Traditional (Big5)"),
    ("shift_jis", "Japanese (Shift-JIS)"), ("euc-kr", "Korean (EUC-KR)"),
]


# --------------------------------------------------------------------------- helpers

def refresh_windows_path():
    """Find ffmpeg even when it was installed (e.g. with winget) after whatever
    started this app: re-read PATH from the registry if ffmpeg isn't on it."""
    if sys.platform != "win32":
        return
    if getattr(sys, "frozen", False):
        # Also support a portable FFmpeg installation beside VideoCaster.exe.
        exe_dir = Path(sys.executable).resolve().parent
        os.environ["PATH"] = os.pathsep.join(
            [str(exe_dir), str(exe_dir / "ffmpeg" / "bin"), os.environ.get("PATH", "")])
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    try:
        import winreg
        parts = []
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join([os.environ.get("PATH", "")] + parts)
    except Exception:
        pass


def fmt_time(t):
    t = int(max(0, t or 0))
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def fmt_short(t):
    """50:25 under an hour, 01:49:03 from an hour (playlist durations)."""
    t = int(max(0, t or 0))
    return fmt_time(t) if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def have_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


_probe_cache: dict[str, dict | None] = {}
_probe_lock = threading.Lock()


def probe(path):
    """ffprobe's streams and format for `path` (cached), or None."""
    key = f"{path}|{_mtime(path)}"
    with _probe_lock:
        if key in _probe_cache:
            return _probe_cache[key]
    info = None
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=30, creationflags=NO_WINDOW)
            if r.returncode == 0:
                info = json.loads(r.stdout or "{}")
        except Exception:
            info = None
    with _probe_lock:
        _probe_cache[key] = info
    return info


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def duration_of(info):
    try:
        return float((info or {}).get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def video_stream(info):
    return next((s for s in (info or {}).get("streams", []) if s.get("codec_type") == "video"
                 and not s.get("disposition", {}).get("attached_pic")), None)


def audio_streams(info):
    return [s for s in (info or {}).get("streams", []) if s.get("codec_type") == "audio"]


def subtitle_streams(info):
    return [s for s in (info or {}).get("streams", []) if s.get("codec_type") == "subtitle"]


def _lang(stream):
    lang = (stream.get("tags") or {}).get("language", "")
    return "" if lang in ("und", "") else lang


# ISO 639-1/639-2 (B and T) codes -> English names, for the audio and subtitle lists
_LANGS = {
    "English": "en eng", "Dutch": "nl nld dut", "French": "fr fre fra", "German": "de ger deu",
    "Spanish": "es spa", "Portuguese": "pt por", "Italian": "it ita", "Danish": "da dan",
    "Swedish": "sv swe", "Norwegian": "no nor", "Norwegian Bokmal": "nb nob", "Norwegian Nynorsk": "nn nno",
    "Finnish": "fi fin", "Icelandic": "is ice isl", "Polish": "pl pol", "Czech": "cs cze ces",
    "Slovak": "sk slo slk", "Slovenian": "sl slv", "Hungarian": "hu hun", "Romanian": "ro rum ron",
    "Bulgarian": "bg bul", "Croatian": "hr hrv", "Serbian": "sr srp", "Bosnian": "bs bos",
    "Greek": "el gre ell", "Turkish": "tr tur", "Russian": "ru rus", "Ukrainian": "uk ukr",
    "Estonian": "et est", "Latvian": "lv lav", "Lithuanian": "lt lit", "Arabic": "ar ara",
    "Hebrew": "he heb", "Persian": "fa per fas", "Hindi": "hi hin", "Bengali": "bn ben", "Tamil": "ta tam",
    "Telugu": "te tel", "Kannada": "kn kan", "Malayalam": "ml mal", "Marathi": "mr mar", "Urdu": "ur urd",
    "Thai": "th tha", "Vietnamese": "vi vie", "Indonesian": "id ind", "Malay": "ms may msa",
    "Filipino": "fil tl tgl", "Chinese": "zh chi zho", "Japanese": "ja jpn", "Korean": "ko kor",
    "Catalan": "ca cat", "Basque": "eu baq eus", "Galician": "gl glg", "Welsh": "cy wel cym",
    "Irish": "ga gle", "Afrikaans": "af afr", "Albanian": "sq alb sqi", "Macedonian": "mk mac mkd",
    "Swahili": "sw swa", "Cantonese": "yue", "Flemish": "vls",
}
LANG_NAMES = {code: name for name, codes in _LANGS.items() for code in codes.split()}


def lang_name(code):
    """'dut' / 'nl' / 'pt-BR' -> 'Dutch' / 'Dutch' / 'Portuguese'; unknown codes are returned as given."""
    if not code:
        return ""
    c = code.lower().replace("_", "-")
    return LANG_NAMES.get(c) or LANG_NAMES.get(c.split("-")[0]) or code


def channel_label(ch):
    return {1: "mono", 2: "stereo", 6: "5.1", 7: "6.1", 8: "7.1"}.get(ch, f"{ch} ch" if ch else "")


def _dedupe(labels):
    seen = {}
    out = []
    for lb in labels:
        seen[lb] = seen.get(lb, 0) + 1
        out.append(lb if seen[lb] == 1 else f"{lb} #{seen[lb]}")
    return out


def audio_format(s):
    """'Dolby Digital Plus Atmos', 'Dolby Digital', 'DTS', 'AAC', ... for an audio stream."""
    c, prof = s.get("codec_name"), s.get("profile") or ""
    if c == "eac3":
        return "Dolby Digital Plus Atmos" if "Atmos" in prof else "Dolby Digital Plus"
    if c == "truehd":
        return "Dolby TrueHD Atmos" if "Atmos" in prof else "Dolby TrueHD"
    return {"ac3": "Dolby Digital", "dts": "DTS-HD" if "HD" in prof else "DTS", "aac": "AAC", "mp3": "MP3",
            "opus": "Opus", "flac": "FLAC", "vorbis": "Vorbis"}.get(c, (c or "?").upper())


_SHORT_FORMAT = {"Dolby Digital Plus Atmos": "DD+ Atmos", "Dolby Digital Plus": "DD+", "Dolby Digital": "DD",
                 "Dolby TrueHD Atmos": "TrueHD Atmos", "Dolby TrueHD": "TrueHD", "DTS-HD": "DTS-HD", "DTS": "DTS"}


def audio_track_labels(info):
    """'English (DD+ Atmos, 5.1)', 'English (Commentary, stereo)', or 'Track 2 (5.1)' without a language."""
    labels = []
    for n, s in enumerate(audio_streams(info), 1):
        lang = lang_name(_lang(s))
        title = (s.get("tags") or {}).get("title", "")
        bits = [b for b in (title if title and title.lower() not in lang.lower() else "",
                            _SHORT_FORMAT.get(audio_format(s), ""),
                            channel_label(s.get("channels") or 0)) if b]
        labels.append(f"{lang or f'Track {n}'}" + (f" ({', '.join(bits)})" if bits else ""))
    return _dedupe(labels) or ["Track 1"]


def _sub_name_parts(tokens):
    """Language name and the other words (SDH, forced, ...) from a subtitle file name's suffix."""
    lang, other = "", []
    for t in tokens:
        name = LANG_NAMES.get(t.lower())
        if name and not lang:
            lang = name
        elif t:
            other.append(t)
    return lang, other


def external_subtitles(path):
    """[(file, label, language)] for subtitle files that belong to `path`: same name start,
    next to it or in a Subs/Subtitles folder."""
    p = Path(path)
    stem = p.stem.lower()
    found = []
    for folder, prefix in ((p.parent, ""), (p.parent / "Subs", "Subs: "), (p.parent / "Subtitles", "Subtitles: ")):
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for f in entries:
            if f.suffix.lower() not in SUB_EXTS or not f.is_file():
                continue
            fstem = f.stem
            if folder == p.parent and not fstem.lower().startswith(stem):
                continue
            rest = fstem[len(stem):].strip(" ._-") if fstem.lower().startswith(stem) else fstem
            lang, other = _sub_name_parts(re.split(r"[ ._-]+", rest)) if rest else ("", [])
            name = lang or (" ".join(other) if other and len(" ".join(other)) < 25 else "Subtitle file")
            extra = [o for o in other if lang]
            label = f"{prefix}{name}" + (f" ({', '.join(extra)})" if extra else "") + f" [{f.suffix[1:].lower()}]"
            found.append((str(f), label, lang))
    return found


def _emb_label(s):
    tags = s.get("tags") or {}
    lang = lang_name(_lang(s))
    title = tags.get("title", "")
    disp = s.get("disposition") or {}
    bits = [b for b in (title if title and title.lower() != lang.lower() else "",
                        "Forced" if disp.get("forced") and "forced" not in title.lower() else "",
                        "picture" if s.get("codec_name") not in TEXT_SUB_CODECS else "") if b]
    return (lang or "Unknown language") + (f" ({', '.join(bits)})" if bits else "")


def subtitle_choices(path, info):
    """[(key, label)] for the Subtitles box: None, subtitle files, then the video's own
    subtitles by language name (alphabetical)."""
    choices = [("none", "None")]
    choices += [(f"ext:{p}", label) for p, label, _ in external_subtitles(path)]
    emb = [(f"emb:{i}", _emb_label(s)) for i, s in enumerate(subtitle_streams(info))]
    labels = _dedupe([lb for _, lb in emb])
    choices += sorted(((k, lb) for (k, _), lb in zip(emb, labels)), key=lambda kl: kl[1].lower())
    return choices


def subtitle_language(path, info, key):
    """(language, variant) of a subtitle choice, for remembering it across videos."""
    if key == "none":
        return ("none", "")
    if key.startswith("ext:"):
        for p, _, lang in external_subtitles(path):
            if f"ext:{p}" == key:
                return (lang, "") if lang else None
        return None
    if key.startswith("emb:"):
        subs = subtitle_streams(info)
        try:
            s = subs[int(key[4:])]
        except (ValueError, IndexError):
            return None
        lang = lang_name(_lang(s))
        return (lang, (s.get("tags") or {}).get("title", "")) if lang else None
    return None


def resolve_subtitle(path, info, fs, gs=None):
    """The subtitle the settings ask for: {'kind': none|ext|emb, 'path'|'index', 'text': bool, 'key'}.
    'auto' uses the language last picked (gs['sub_pref']), else a subtitle file next to the video."""
    key = fs.get("subtitle", "auto")
    if key == "auto":
        key = _auto_subtitle(path, info, (gs or {}).get("sub_pref"))
    if key.startswith("ext:") and os.path.isfile(key[4:]):
        return {"kind": "ext", "path": key[4:], "text": True, "key": key}
    if key.startswith("emb:"):
        subs = subtitle_streams(info)
        try:
            i = int(key[4:])
        except ValueError:
            i = -1
        if 0 <= i < len(subs):
            return {"kind": "emb", "index": i, "text": subs[i].get("codec_name") in TEXT_SUB_CODECS, "key": key}
    return {"kind": "none", "text": True, "key": "none"}


def _auto_subtitle(path, info, pref):
    ext = external_subtitles(path)
    if pref and pref[0] == "none":
        return "none"
    if pref and pref[0]:
        lang, variant = pref[0], (pref[1] or "").lower()
        for p, _, elang in ext:
            if elang == lang:
                return f"ext:{p}"
        best = None
        for i, s in enumerate(subtitle_streams(info)):
            if lang_name(_lang(s)) != lang:
                continue
            title = ((s.get("tags") or {}).get("title") or "").lower()
            disp = s.get("disposition") or {}
            score = (title == variant, s.get("codec_name") in TEXT_SUB_CODECS, not disp.get("forced"),
                     "sdh" not in title or "sdh" in variant)
            if best is None or score > best[0]:
                best = (score, i)
        if best:
            return f"emb:{best[1]}"
    return f"ext:{ext[0][0]}" if ext else "none"


# --------------------------------------------------------------------------- subtitles

_SRT_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{3})")


def parse_cues(text):
    """SRT or WebVTT text -> [(start, end, [lines])]."""
    cues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        ti = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if ti is None:
            continue
        times = _SRT_TIME.findall(lines[ti])
        if len(times) < 2:
            continue
        start, end = (int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in times[:2])
        cues.append((start, end, lines[ti + 1:]))
    return cues


def _ts(t, sep):
    h, rem = divmod(int(round(max(0.0, t) * 1000)), 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def cues_to_vtt(cues, shift=0.0):
    """WebVTT with every cue moved by `shift` seconds; cues that end before 0 are dropped.
    A cue may carry a 4th item: WebVTT cue settings (position on screen)."""
    out = ["WEBVTT", ""]
    for cue in sorted(cues, key=lambda c: c[0]):
        start, end, lines = cue[:3]
        if end + shift <= 0:
            continue
        settings = f" {cue[3]}" if len(cue) > 3 and cue[3] else ""
        out.append(f"{_ts(start + shift, '.')} --> {_ts(end + shift, '.')}{settings}")
        out.extend(lines)
        out.append("")
    return "\n".join(out)


UPNEXT_SECS = 10


def upnext_cues(credits, title, secs=UPNEXT_SECS):
    """The 'Up next' countdown as subtitle lines in the top-right corner, from the credits on."""
    return [(credits + i, credits + i + 1, [f"Up next: {title}", f"starts in {secs - i} s"],
             "line:6% position:96% align:end size:50%") for i in range(secs)]


def cues_to_srt(cues, shift=0.0):
    out = []
    n = 0
    for start, end, lines in cues:
        if end + shift <= 0:
            continue
        n += 1
        out += [str(n), f"{_ts(start + shift, ',')} --> {_ts(end + shift, ',')}", *lines, ""]
    return "\n".join(out)


def srt_to_vtt(text, offset=0.0):
    """SRT -> WebVTT, moved back by `offset` seconds (a stream that starts part-way in)."""
    return cues_to_vtt(parse_cues(text), -offset)


def read_text_file(path, encoding="auto"):
    data = Path(path).read_bytes()
    if encoding == "auto":
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="replace")
    return data.decode(encoding, errors="replace")


def _emb_cache(path, index):
    key = hashlib.sha1(f"{path}|{_mtime(path)}|{index}".encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"emb_{key}.srt"


_sub_locks: dict[str, threading.Lock] = {}
_sub_locks_guard = threading.Lock()


def prefetch_subtitles(path, info=None):
    """Pull every text subtitle out of the video in one pass (ffmpeg reads the file once),
    so switching subtitles later is instant. Safe to call from several threads."""
    info = info or probe(path)
    subs = subtitle_streams(info)
    todo = [i for i, s in enumerate(subs) if s.get("codec_name") in TEXT_SUB_CODECS and not _emb_cache(path, i).exists()]
    if not todo or not shutil.which("ffmpeg"):
        return
    with _sub_locks_guard:
        lock = _sub_locks.setdefault(path, threading.Lock())
    with lock:
        todo = [i for i in todo if not _emb_cache(path, i).exists()]
        if not todo:
            return
        CACHE_DIR.mkdir(exist_ok=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", path]
        tmps = []
        for i in todo:
            tmp = _emb_cache(path, i).with_suffix(".tmp.srt")
            tmps.append((i, tmp))
            cmd += ["-map", f"0:s:{i}", "-c:s", "srt", str(tmp)]
        subprocess.run(cmd, capture_output=True, timeout=1800, creationflags=NO_WINDOW)
        for i, tmp in tmps:
            if tmp.exists():
                tmp.replace(_emb_cache(path, i))


def subtitle_cues(path, sub, encoding="auto"):
    """Cues of the chosen subtitle (external file, or a text stream pulled out of the video)."""
    if sub["kind"] == "ext":
        return parse_cues(read_text_file(sub["path"], encoding))
    if sub["kind"] == "emb" and sub["text"]:
        out = _emb_cache(path, sub["index"])
        if not out.exists():
            prefetch_subtitles(path)
        if not out.exists():
            raise RuntimeError("Couldn't read the subtitles from the video.")
        return parse_cues(out.read_text(encoding="utf-8", errors="replace"))
    return []


def detect_credits(path, info=None, min_duration=300):
    """Seconds where the end credits begin, or None. Looks at the last minutes (keyframes only,
    under a second): credits are light text on a dark picture, so it finds the earliest point
    from which the picture stays dark to the end."""
    info = info or probe(path)
    dur = duration_of(info)
    v = video_stream(info)
    if not v or dur < min_duration or not shutil.which("ffmpeg"):
        return None
    window = min(600.0, max(360.0, dur * 0.12))
    start = max(0.0, dur - window)
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-skip_frame", "nokey", "-ss", f"{start:.1f}", "-i", path,
                            "-an", "-sn", "-dn", "-vf", "scale=160:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                            "-fps_mode", "passthrough", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                           creationflags=NO_WINDOW)
    except Exception:
        return None
    scale = 4.0 if "10" in (v.get("pix_fmt") or "") else (16.0 if "12" in (v.get("pix_fmt") or "") else 1.0)
    samples, t = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = start + float(m.group(1))
            continue
        m = re.search(r"YAVG=([\d.]+)", line)
        if m and t is not None:
            samples.append((t, float(m.group(1)) / scale))
            t = None
    samples.sort()
    dark = [y < 30 for _, y in samples]  # 8-bit average brightness: black is 16
    for i, (ti, _) in enumerate(samples):
        tail = dark[i:]
        if dark[i] and dur - ti >= 30 and sum(tail) >= 0.9 * len(tail) and len(tail) >= 4:
            return round(ti, 1)
    return None


_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S(\d{1,2})[ ._-]?E(\d{1,3})(?!\d)")


def _words(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def next_episode(path, step=1):
    """The next episode of a series in the same folder (S01E09 -> S01E10, or the next
    season's first), preferring the same release as `path`; None if there isn't one.
    step=-1: the previous episode instead."""
    p = Path(path)
    m = _EPISODE.search(p.stem)
    if not m:
        return None
    show, cur = _words(p.stem[:m.start()]), (int(m.group(1)), int(m.group(2)))
    tags = set(_words(p.stem[m.end():]).split())
    best = None
    try:
        files = list(p.parent.iterdir())
    except OSError:
        return None
    for f in files:
        if f.suffix.lower() not in VIDEO_EXTS or f == p:
            continue
        fm = _EPISODE.search(f.stem)
        if not fm or _words(f.stem[:fm.start()]) != show:
            continue
        se = (int(fm.group(1)), int(fm.group(2)))
        if (se <= cur) if step > 0 else (se >= cur):
            continue
        near = se if step > 0 else (-se[0], -se[1])  # the closest one first
        key = (near, -len(tags & set(_words(f.stem[fm.end():]).split())), f.name.lower())
        if best is None or key < best[0]:
            best = (key, f)
    return str(best[1]) if best else None


# --------------------------------------------------------------------------- intros

INTRO_SCAN = 600.0  # seconds at the start of an episode in which its intro is looked for
FP_STEP = 4096 / 3 / 11025  # seconds per audio-fingerprint point (Chromaprint: ~0.124 s)


def audio_fingerprint(path, seconds=INTRO_SCAN):
    """Chromaprint audio fingerprint of the first `seconds` of a video (one 32-bit number per
    ~0.124 s), cached on disk; an empty array if it can't be made. Needs numpy."""
    import numpy as np
    key = hashlib.sha1(f"{path}|{_mtime(path)}|{seconds:g}".encode("utf-8")).hexdigest()[:16]
    f = CACHE_DIR / f"fp_{key}.bin"
    data = b""
    if f.exists():
        data = f.read_bytes()
    elif shutil.which("ffmpeg") and Path(path).exists():
        for _ in range(2):  # once more if it fails (a file briefly in use)
            try:
                r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-t", f"{seconds:g}",
                                    "-i", path, "-map", "0:a:0", "-ac", "2", "-f", "chromaprint", "-fp_format", "raw",
                                    "-"], capture_output=True, timeout=600, creationflags=NO_WINDOW)
                data = r.stdout if r.returncode == 0 else b""
            except Exception:
                data = b""
            if data:
                break
        if data:
            CACHE_DIR.mkdir(exist_ok=True)
            f.write_bytes(data)
    return np.frombuffer(data[:len(data) // 4 * 4], dtype="<u4")


def match_intro(fa, fb, min_len=15.0, max_len=150.0, max_bits=6, gap=2.0):
    """The longest stretch of audio two fingerprints share - an episode's opening titles:
    ((a_start, a_end), (b_start, b_end)) in seconds, or None. Every offset between the two is
    tried; points count as the same sound when at most `max_bits` of their 32 bits differ."""
    import numpy as np
    na, nb = len(fa), len(fb)
    need = int(min_len / FP_STEP)
    if na < need or nb < need:
        return None
    scores = []
    for shift in range(-(na - need), nb - need + 1):  # b index = a index + shift
        a0 = max(0, -shift)
        n = min(na - a0, nb - a0 - shift)
        hits = int(np.count_nonzero(np.bitwise_count(fa[a0:a0 + n] ^ fb[a0 + shift:a0 + shift + n]) <= max_bits))
        if hits >= need // 2:
            scores.append((hits, shift))
    best = None
    for _, shift in sorted(scores, reverse=True)[:12]:
        a0 = max(0, -shift)
        n = min(na - a0, nb - a0 - shift)
        a, b = fa[a0:a0 + n], fb[a0 + shift:a0 + shift + n]
        idx = np.flatnonzero(np.bitwise_count(a ^ b) <= max_bits)
        if not len(idx):
            continue
        cut = np.flatnonzero(np.diff(idx) > int(gap / FP_STEP))  # short gaps are bridged
        for s, e in zip(np.r_[idx[0], idx[cut + 1]], np.r_[idx[cut], idx[-1]]):
            length = (e - s + 1) * FP_STEP
            if not min_len <= length <= max_len:
                continue
            if len(np.unique(a[s:e + 1])) < 0.5 * (e - s + 1):
                continue  # near-constant fingerprint: silence, not titles
            if best is None or length > best[0]:
                best = (length, ((a0 + s) * FP_STEP, (a0 + e + 1) * FP_STEP),
                        ((a0 + shift + s) * FP_STEP, (a0 + shift + e + 1) * FP_STEP))
    if best is None:
        return None
    # each fingerprint point covers ~2 s of sound, so the last matching one lies ~1.8 s before
    # the shared stretch really ends; move the end up, staying just short of the episode itself
    r = lambda t: (round(float(t[0]), 1), round(float(t[1]) + FP_TAIL, 1))
    return r(best[1]), r(best[2])


FP_TAIL = 1.5


def detect_intro(path, partner=None):
    """Where the opening titles of an episode are, found by comparing its first minutes with
    another episode of the series (the next one, or else the previous one). Returns
    ((start, end), partner, (partner_start, partner_end)) - one comparison answers for both
    episodes -, False if the two share no intro, or None if it couldn't be checked (no other
    episode, audio unreadable, numpy missing)."""
    partner = partner or next_episode(path) or next_episode(path, -1)
    if not partner:
        return None
    try:
        fa, fb = audio_fingerprint(path), audio_fingerprint(partner)
        if not len(fa) or not len(fb):
            return None
        m = match_intro(fa, fb)
    except Exception:
        return None
    return (m[0], partner, m[1]) if m else False


# --------------------------------------------------------------------------- online subtitles

OS_API = os.environ.get("VIDEOCASTER_OS_API") or "https://api.opensubtitles.com/api/v1"
OS_AGENT = "VideoCaster v1.0"  # OpenSubtitles wants "AppName vX.Y" as User-Agent


def _os_languages():
    """Languages for the search window: name -> OpenSubtitles code (two letters, a few with region)."""
    out = {}
    for name, codes in _LANGS.items():
        two = next((c for c in codes.split() if len(c) == 2), None)
        if two and name not in ("Portuguese", "Chinese"):
            out[name] = two
    out.update({"Portuguese (Portugal)": "pt-pt", "Portuguese (Brazil)": "pt-br",
                "Chinese (simplified)": "zh-cn", "Chinese (traditional)": "zh-tw"})
    return dict(sorted(out.items()))


OS_LANGS = _os_languages()


def os_language_for(pref):
    """The search window's language for a remembered subtitle choice ('Portuguese', 'Brazilian')."""
    if not pref or not pref[0] or pref[0] == "none":
        return "English"
    lang, variant = pref[0], (pref[1] or "").lower() if len(pref) > 1 else ""
    if lang == "Portuguese":
        return "Portuguese (Brazil)" if "braz" in variant else "Portuguese (Portugal)"
    if lang == "Chinese":
        return "Chinese (traditional)" if "trad" in variant else "Chinese (simplified)"
    return lang if lang in OS_LANGS else "English"


def movie_hash(path):
    """OpenSubtitles' fingerprint of a video file: its size plus the 64-bit sums of the first
    and last 64 KB, as 16 hex digits; None for files under 128 KB."""
    try:
        size = os.path.getsize(path)
        if size < 131072:
            return None
        h = size
        with open(path, "rb") as f:
            for pos in (0, size - 65536):
                f.seek(pos)
                h = (h + sum(struct.unpack("<8192Q", f.read(65536)))) & 0xFFFFFFFFFFFFFFFF
        return f"{h:016x}"
    except (OSError, struct.error):
        return None


def video_query(path):
    """What a file is, from its name: {'query': 'off campus', 'season_number': 1, 'episode_number': 3}
    for an episode, {'query': 'masterplan', 'year': 2026} for a film."""
    stem = Path(path).stem
    m = _EPISODE.search(stem)
    if m:
        return {"query": _words(stem[:m.start()]), "season_number": int(m.group(1)), "episode_number": int(m.group(2))}
    y = re.search(r"(?<![0-9])(19\d\d|20\d\d)(?![0-9])", stem)
    if y and y.start() > 0:
        return {"query": _words(stem[:y.start()]), "year": int(y.group(1))}
    title = re.split(r"(?i)[ ._\-\[(](?:2160p|1080p|720p|480p|web|bluray|brrip|hdtv|dvdrip|x26[45]|h26[45]|hevc)", stem)[0]
    return {"query": _words(title)}


class SubtitleError(Exception):
    """Something about finding subtitles online to tell the viewer, in plain words."""


OpenSubtitlesError = SubtitleError


def _os_error(e):
    try:
        body = json.loads(e.read().decode("utf-8", "replace") or "{}")
    except Exception:
        body = {}
    msg = ""
    if isinstance(body, dict):
        msg = body.get("message") or "; ".join(str(x) for x in (body.get("errors") or []))
    if e.code == 401:
        return "OpenSubtitles didn't accept the API key or the login" + (f": {msg}" if msg else ".")
    if e.code == 403:
        return "OpenSubtitles refused this" + (f": {msg}" if msg else " - check the API key.")
    if e.code == 406:
        return msg or "No subtitle downloads left for today."
    if e.code == 429:
        return "Too many requests to OpenSubtitles - try again in a few seconds."
    if e.code >= 500:
        return f"OpenSubtitles has a problem right now (error {e.code}) - try again later."
    return msg or f"OpenSubtitles answered with error {e.code}."


class OpenSubtitles:
    """OpenSubtitles.com (REST API v1): search by the file's fingerprint and name, and download.
    Needs an API key (free, made in the viewer's own account); logging in as well gives more
    downloads per day."""

    def __init__(self, api_key, username="", password="", api=None):
        self.api_key = (api_key or "").strip()
        self.username, self.password = (username or "").strip(), password or ""
        self.base = (api or OS_API).rstrip("/")
        self.token = None
        self.remaining = None  # downloads left today, as of the last download

    def _call(self, method, path, params=None, body=None):
        url = f"{self.base}/{path}"
        if params:  # lowercase and in alphabetical order, as the API wants (it redirects otherwise)
            url += "?" + urlencode(sorted((k, str(v).lower()) for k, v in params.items() if v not in (None, "")))
        headers = {"Api-Key": self.api_key, "User-Agent": OS_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method),
                                        timeout=20) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise OpenSubtitlesError(_os_error(e)) from None
        except (urllib.error.URLError, OSError) as e:
            raise OpenSubtitlesError(f"OpenSubtitles can't be reached ({getattr(e, 'reason', e)}).") from None
        except ValueError:
            raise OpenSubtitlesError("OpenSubtitles sent an answer that couldn't be read.") from None

    def login(self):
        """Log in (only with a user name and password); True when logged in."""
        if self.token or not (self.username and self.password):
            return bool(self.token)
        r = self._call("POST", "login", body={"username": self.username, "password": self.password})
        self.token = r.get("token")
        host = (r.get("base_url") or "").strip().rstrip("/")
        host = host.split("://")[-1].split("/")[0]
        if host.endswith(".opensubtitles.com") and not os.environ.get("VIDEOCASTER_OS_API"):
            self.base = f"https://{host}/api/v1"  # e.g. the VIP server for VIP members
        return bool(self.token)

    def search(self, path, language):
        """Subtitles for this video in one language (an OS_LANGS code), best first: exact
        matches for this very file, then human-made ones by downloads."""
        q = video_query(path)
        params = dict(q, languages=language)
        h = movie_hash(path)
        if h:
            params["moviehash"] = h
        r = self._call("GET", "subtitles", params)
        out = []
        for item in r.get("data") or []:
            a = (item or {}).get("attributes") or {}
            files = a.get("files") or []
            if not files or files[0].get("file_id") is None:
                continue
            fd = a.get("feature_details") or {}
            out.append({"file_id": files[0]["file_id"], "file_name": files[0].get("file_name") or "",
                        "language": a.get("language") or language,
                        "release": a.get("release") or files[0].get("file_name") or "",
                        "downloads": int(a.get("download_count") or 0), "exact": bool(a.get("moviehash_match")),
                        "hearing_impaired": bool(a.get("hearing_impaired")),
                        "machine": bool(a.get("machine_translated") or a.get("ai_translated")),
                        "trusted": bool(a.get("from_trusted")), "fps": a.get("fps"),
                        "season": fd.get("season_number"), "episode": fd.get("episode_number")})
        if "episode_number" in q:  # a search by name can bring other episodes too
            out = [s for s in out if s["exact"] or (s["season"] in (None, q["season_number"])
                                                    and s["episode"] in (None, q["episode_number"]))]
        out.sort(key=lambda s: (not s["exact"], s["machine"], -s["downloads"]))
        return out

    def download(self, sub, video_path):
        """Fetch one search result and save it next to the video (or else in the app's folder);
        returns the saved file."""
        if self.username and self.password and not self.token:
            self.login()
        r = self._call("POST", "download", body={"file_id": sub["file_id"]})
        link = r.get("link")
        if not link or not str(link).startswith("https://") and not os.environ.get("VIDEOCASTER_OS_API"):
            raise OpenSubtitlesError(r.get("message") or "OpenSubtitles gave no download link.")
        if r.get("remaining") is not None:
            self.remaining = r.get("remaining")
        try:
            with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": OS_AGENT}), timeout=30) as f:
                data = f.read(5_000_000)
        except (urllib.error.URLError, OSError) as e:
            raise OpenSubtitlesError(f"The subtitle file couldn't be downloaded ({getattr(e, 'reason', e)}).") from None
        if data[:2] == b"\x1f\x8b":
            import gzip
            data = gzip.decompress(data)
        if not data.strip():
            raise OpenSubtitlesError("The downloaded subtitle file is empty.")
        return save_online_subtitle(video_path, sub.get("language") or "", data)


def save_online_subtitle(video, language, data):
    """Save downloaded subtitles as '<video name>.<language>.online.srt' next to the video, so
    the app finds them by itself next time (the same file again is not saved twice)."""
    p = Path(video)
    code = re.sub(r"[^a-z0-9-]", "", (language or "xx").lower()) or "xx"
    for folder in (p.parent, CACHE_DIR / "subs"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            n = 1
            while True:
                target = folder / f"{p.stem}.{code}.online{'' if n == 1 else f'-{n}'}.srt"
                if not target.exists():
                    break
                if target.read_bytes() == data:
                    return str(target)
                n += 1
            target.write_bytes(data)
            return str(target)
        except OSError:
            continue
    raise OpenSubtitlesError("The subtitle file couldn't be saved.")


def _dpapi(data, encrypt):
    """Windows' own encryption for the signed-in user (DPAPI)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):  # 0x1: never show a prompt
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(dst.pbData, ctypes.c_void_p))


def protect(text):
    """A secret (API key, password) for state.json: encrypted for this Windows user."""
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
        except OSError:
            pass
    return "b64:" + base64.b64encode(raw).decode("ascii")  # other systems: only hidden from view


def unprotect(stored):
    if not stored:
        return ""
    try:
        kind, _, b = stored.partition(":")
        raw = base64.b64decode(b)
        return (_dpapi(raw, False) if kind == "dpapi" else raw).decode("utf-8")
    except Exception:
        return ""


def opensubtitles_from(account):
    """An OpenSubtitles client from the saved account (state['opensubtitles']), or None without an API key."""
    account = account or {}
    key = unprotect(account.get("api_key", ""))
    if not key:
        return None
    return OpenSubtitles(key, account.get("username", ""), unprotect(account.get("password", "")))


# Stremio's own OpenSubtitles add-on: free, no account or key. It finds subtitles by IMDb id
# (looked up by title in Stremio's catalogue, Cinemeta) and by the file's fingerprint.
STREMIO_SUBS = os.environ.get("VIDEOCASTER_STREMIO_SUBS") or "https://opensubtitles-v3.strem.io"
CINEMETA = os.environ.get("VIDEOCASTER_CINEMETA") or "https://v3-cinemeta.strem.io"
# the add-on's language codes (ISO 639-2) that need more than lang_name: -> search window language
_STREMIO_LANGS = {"pob": "Portuguese (Brazil)", "por": "Portuguese (Portugal)", "chi": "Chinese (simplified)",
                  "zhe": "Chinese (simplified)", "zht": "Chinese (traditional)", "spl": "Spanish", "spn": "Spanish"}


def stremio_language(code):
    """Search-window language name for one of the add-on's language codes, or None."""
    code = (code or "").lower()
    name = _STREMIO_LANGS.get(code) or lang_name(code)
    return name if name in OS_LANGS else None


def _get_json(url, what):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": OS_AGENT,
                                                                         "Accept": "application/json"}), timeout=20) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise SubtitleError(f"{what} answered with error {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise SubtitleError(f"{what} can't be reached ({getattr(e, 'reason', e)}).") from None
    except ValueError:
        raise SubtitleError(f"{what} sent an answer that couldn't be read.") from None


def _release_group(name):
    """'PSA' from '...x265 HEVC-PSA', 'ELiTE' from '...x265-ELiTE[EZTVx.to]'."""
    m = re.search(r"-([A-Za-z0-9]+)(?:\[[^\]]*\])?$", Path(name).stem if "." in name[-5:] else name)
    return m.group(1).lower() if m else ""


class StremioSubtitles:
    """Subtitles through Stremio's own OpenSubtitles add-on - nothing to sign up for."""

    _ids: dict = {}  # (kind, title, year) -> IMDb id, for this run of the app

    def imdb_id(self, path):
        """('series', 'tt33546863:1:3') or ('movie', 'tt38672588') for a video, from its file name."""
        q = video_query(path)
        kind = "series" if "episode_number" in q else "movie"
        title, year = q["query"], q.get("year")
        m = re.match(r"(.+?)\s+((?:19|20)\d\d)$", title)
        if kind == "series" and m:  # 'Off.Campus.2026.S01E03': the year belongs to the series
            title, year = m.group(1), int(m.group(2))
        if not title:
            raise SubtitleError("Couldn't tell from the file name which film or series this is.")
        key = (kind, title, year)
        if key not in self._ids:
            metas = _get_json(f"{CINEMETA}/catalog/{kind}/top/search={quote(title)}.json", "Stremio's catalogue")
            metas = [m for m in (metas.get("metas") or []) if str(m.get("id", "")).startswith("tt")]
            if not metas:
                raise SubtitleError(f"'{title}' wasn't found in Stremio's catalogue.")
            best = metas[0]
            for m in metas:  # same year first, else the same name, else the catalogue's first
                if year and str(m.get("releaseInfo") or "").startswith(str(year)):
                    best = m
                    break
            else:
                best = next((m for m in metas if _words(m.get("name") or "") == title), best)
            self._ids[key] = best["id"]
        vid = self._ids[key]
        return kind, (f"{vid}:{q['season_number']}:{q['episode_number']}" if kind == "series" else vid)

    def search(self, path):
        """All subtitles the add-on has for this video (every language), as search results."""
        kind, vid = self.imdb_id(path)
        extra = ""
        h = movie_hash(path)
        if h:
            extra = "/" + urlencode({"videoHash": h, "videoSize": os.path.getsize(path), "filename": Path(path).name},
                                    quote_via=quote)
        data = _get_json(f"{STREMIO_SUBS}/subtitles/{kind}/{vid}{extra}.json", "Stremio's subtitle service")
        group = _release_group(Path(path).name)
        out = []
        for s in data.get("subtitles") or []:
            name = stremio_language(s.get("lang"))
            if not name or not s.get("url"):
                continue
            release = s.get("movieReleaseName") or s.get("subtitleFileName") or ""
            fname = s.get("subtitleFileName") or release
            out.append({"source": "stremio", "url": s["url"], "id": s.get("id"), "language": OS_LANGS[name],
                        "language_name": name, "release": release, "downloads": None,
                        "exact": s.get("m") == "h",
                        "same_release": bool(group) and re.sub(r"\[[^\]]*\]", "", s.get("releaseGroup") or "").lower() == group,
                        "hearing_impaired": bool(re.search(r"(?i)(?<![a-z])(sdh|hi|cc)(?![a-z])", fname)),
                        "machine": False, "trusted": False,
                        "variant": "Latin American" if (s.get("lang") or "").lower() in ("spl", "spn") else ""})
        return out

    def download(self, sub, video_path):
        url = sub["url"]
        if not url.startswith("https://") and not os.environ.get("VIDEOCASTER_STREMIO_SUBS"):
            raise SubtitleError("The subtitle service gave an unexpected download link.")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": OS_AGENT}), timeout=30) as f:
                data = f.read(5_000_000)
        except (urllib.error.URLError, OSError) as e:
            raise SubtitleError(f"The subtitle file couldn't be downloaded ({getattr(e, 'reason', e)}).") from None
        if data[:2] == b"\x1f\x8b":
            import gzip
            data = gzip.decompress(data)
        if not data.strip():
            raise SubtitleError("The downloaded subtitle file is empty.")
        return save_online_subtitle(video_path, sub["language"], data)


def find_subtitles(path, language, os_client=None):
    """Subtitles for a video in one language (a name from OS_LANGS): from Stremio's free add-on,
    and also from the OpenSubtitles API when the viewer saved their own key. Returns
    (results best first, other languages that do have some, problems to mention)."""
    results, others, problems = [], set(), []
    try:
        for s in StremioSubtitles().search(path):
            if s["language_name"] == language:
                results.append(s)
            else:
                others.add(s["language_name"])
    except SubtitleError as e:
        problems.append(str(e))
    if os_client is not None:
        try:
            seen = {(s["release"].lower(), s["language"]) for s in results}
            group = _release_group(Path(path).name)
            for s in os_client.search(path, OS_LANGS[language]):
                s.update(source="opensubtitles", language=OS_LANGS[language], language_name=language, variant="",
                         same_release=bool(group) and group in s["release"].lower())
                key = (s["release"].lower(), s["language"])
                if key in seen:  # the same file from both: keep the free one, with the download count
                    for r in results:
                        if (r["release"].lower(), r["language"]) == key and r["downloads"] is None:
                            r["downloads"] = s["downloads"]
                            r["exact"] = r["exact"] or s["exact"]
                    continue
                seen.add(key)
                results.append(s)
        except SubtitleError as e:
            problems.append(f"OpenSubtitles (your key): {e}")
    results.sort(key=lambda s: (not s["exact"], not s["same_release"], s["machine"], -(s["downloads"] or 0)))
    return results, sorted(others), problems


def fetch_subtitle(sub, video_path, os_client=None):
    """Download a search result (from either source) next to the video: (file, downloads left today or None)."""
    if sub.get("source") == "opensubtitles":
        if os_client is None:
            raise SubtitleError("This one needs your OpenSubtitles key (Account...).")
        return os_client.download(sub, video_path), os_client.remaining
    return StremioSubtitles().download(sub, video_path), None


INTRO_SECS = 5  # countdown before an intro is skipped


def intro_cues(start, secs=INTRO_SECS):
    """'Skipping intro' countdown as subtitle lines in the top-right corner, from the intro on."""
    return [(start + i, start + i + 1, ["Skipping intro", f"in {secs - i} s"],
             "line:6% position:96% align:end size:50%") for i in range(secs)]


# --------------------------------------------------------------------------- planning

def describe_video(v):
    codec = {"hevc": "H.265", "h264": "H.264", "mpeg4": "MPEG-4", "mpeg2video": "MPEG-2", "av1": "AV1",
             "vc1": "VC-1", "wmv3": "WMV"}.get(v.get("codec_name"), (v.get("codec_name") or "?").upper())
    if "10" in (v.get("pix_fmt") or ""):
        codec += " 10-bit"
    return codec


def plan_stream(path, info, fs, gs, encoder="libx264"):
    """Decide how the TV gets this file:
    direct    - sent as it is (with byte ranges, so the TV can seek)
    remux     - the original video stream is copied into a new MP4; audio adapted if needed
    transcode - the video is converted too (ffmpeg, live while playing)
    Also returns the texts for the settings panel footer."""
    fs = {**FILE_DEFAULTS, **(fs or {})}
    gs = {**GLOBAL_DEFAULTS, **(gs or {})}
    video = video_stream(info)
    audios = audio_streams(info)
    a_idx = max(0, min(int(fs["audio_track"]), len(audios) - 1)) if audios else 0
    audio = audios[a_idx] if audios else None
    ext = Path(path).suffix.lower()
    sub = resolve_subtitle(path, info, fs, gs)

    reasons = []
    hevc_native = gs["hevc_native"] and video is not None and video.get("codec_name") == "hevc" \
        and video.get("pix_fmt") in HEVC_PIX_FMTS
    if video is not None and not hevc_native and not (
            video.get("codec_name") in DIRECT_VIDEO and video.get("pix_fmt") in DIRECT_PIX_FMTS):
        reasons.append(f"{describe_video(video)} video isn't supported by the TV")
    burn = sub["kind"] != "none" and (fs["sub_render"] == "burn" or not sub["text"])
    if burn:
        reasons.append("the subtitles are burned into the picture")
    if fs["deinterlace"] != "none":
        reasons.append("the video is deinterlaced")
    if fs["force_convert"]:
        reasons.append("conversion is forced in the settings")
    video_convert = bool(reasons) and video is not None

    channels = int((audio or {}).get("channels") or 2)
    surround = gs.get("surround", "stereo")   # app-wide: it's about the TV / soundbar, not the file
    passthrough = surround == "passthrough"
    downmix = surround == "stereo" and channels > 2
    afilters = []
    if fs["volume"] == "boost":
        afilters.append("volume=6dB")
    elif fs["volume"] == "normalize":
        afilters.append("dynaudnorm=f=150:g=7")
    delay = float(fs["audio_delay"] or 0)
    if delay > 0:
        afilters.append(f"adelay={int(delay * 1000)}:all=1")
    elif delay < 0:
        afilters.append(f"atrim=start={-delay:.3f},asetpts=PTS-STARTPTS")
    a_codec = (audio or {}).get("codec_name")
    dolby = a_codec in DOLBY_AUDIO
    audio_as_is = audio is None or (a_codec in DIRECT_AUDIO and not downmix and not afilters)
    audio_copy = audio is None or (a_codec in MP4_COPY_AUDIO and not downmix and not afilters)
    audio_out = "aac"  # what the audio becomes when it can't be copied
    if passthrough and audio is not None:
        if dolby and not afilters:
            # Dolby Digital / Digital Plus (Atmos included) go to the TV untouched
            audio_as_is = audio_copy = True
        elif channels > 2:
            # other surround (DTS, TrueHD, AAC 5.1, ...) becomes Dolby Digital 5.1,
            # which TVs and soundbars pass on; Atmos can't survive a conversion
            audio_as_is = audio_copy = False
            audio_out = "ac3"
    if passthrough and dolby:
        audio_out = "ac3"  # e.g. when filters or a seek in a converted video force re-encoding

    if not video_convert and audio_as_is and ext in DIRECT_CONTAINERS and a_idx == 0 and fs["aspect"] == "default":
        mode = "direct"
    elif not video_convert:
        mode = "remux"
    else:
        mode = "transcode"

    plan = {
        "mode": mode,
        "audio_index": a_idx,
        "audio_copy": audio_copy,
        "audio_out": audio_out,
        "audio_channels": 2 if (downmix or channels <= 2) else min(channels, 6),
        "afilters": afilters,
        "deinterlace": fs["deinterlace"],
        "aspect": fs["aspect"],
        "target_h": {"1080": 1080, "720": 720, "480": 480}.get(str(fs["quality"]), 1080),
        "video_codec": (video or {}).get("codec_name"),
        "hw_decode": bool(gs["accel_decode"]),
        "encoder": encoder if gs["accel_encode"] else "libx264",
        "sub": sub,
        "burn": burn,
        "sub_font": (gs.get("sub_font"), gs.get("sub_font_style")) if burn else None,  # burned in: part of the picture
        "duration": duration_of(info),
    }
    if mode == "direct":
        plan["headline"] = "Video conversion is not required"
        plan["detail"] = "The file is streamed as it is - best quality and lowest CPU load."
    elif mode == "remux":
        what = []
        if ext not in DIRECT_CONTAINERS:
            what.append(f"the {ext[1:].upper()} container")
        if not audio_as_is or a_idx:
            what.append("the audio" + (" (mixed down to stereo)" if downmix else ""))
        plan["headline"] = "Video conversion is not required"
        plan["detail"] = ("The original video stream is kept - best quality and low CPU load."
                          + (f" Only {' and '.join(what)} is adapted for the TV." if what else ""))
    else:
        how = "Intel Quick Sync" if plan["encoder"] == "h264_qsv" else "the processor"
        plan["headline"] = "Video will be converted"
        plan["detail"] = f"Because {' and '.join(reasons)}. Converting with {how} while it plays."
    if passthrough and audio is not None:
        name = audio_format(audio)
        if audio_copy:
            plan["detail"] += f" {name} audio goes to the TV untouched (passthrough)."
            if mode == "transcode":
                plan["detail"] += " After a jump in the video it's sent as Dolby Digital 5.1 instead."
        elif audio_out == "ac3":
            plan["detail"] += f" {name} audio is sent as Dolby Digital 5.1."
    return plan


# --------------------------------------------------------------------------- ffmpeg

def detect_encoder():
    """h264_qsv when Intel Quick Sync works on this PC, else libx264."""
    if not shutil.which("ffmpeg"):
        return "libx264"
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi",
                            "-i", "testsrc=size=640x360:rate=25:duration=0.5", "-vf", "format=nv12",
                            "-c:v", "h264_qsv", "-f", "null", "-"],
                           capture_output=True, timeout=20, creationflags=NO_WINDOW)
        return "h264_qsv" if r.returncode == 0 else "libx264"
    except Exception:
        return "libx264"


def _bitrate(h):
    return {480: 2500, 720: 5000, 1080: 8000}.get(h, 8000)


HLS_SEG = 4.0  # seconds per HLS piece
# Every HLS run puts its pieces this much later than the source. A run from 0 s would otherwise
# start with negative times (B-frame reordering, audio encoder priming) and ffmpeg would push
# that whole run forward by a frame or so - one frame off from runs started later (after a jump
# or a quality switch), so pieces of different runs overlapped. With the same small lead
# everywhere, nothing is negative and every run lines up to the frame.
HLS_LEAD = 0.1


def frame_rate(v):
    """A video stream's constant frame rate as a Fraction, or None if it varies or is unknown."""
    try:
        r = Fraction(v.get("r_frame_rate") or "0/1")
        a = v.get("avg_frame_rate")
        a = Fraction(a) if a and a != "0/0" else r
    except (ValueError, ZeroDivisionError, TypeError):
        return None
    if not 10 <= r <= 121 or (a and abs(a - r) / r > Fraction(1, 100)):
        return None
    return r


def _hls_seek(start, fps):
    """For an HLS run beginning at `start`: where to seek, the real time of the first frame
    it keeps (the first frame at or after `start`), and how far that lies past `start`.
    ffmpeg would put that frame at `start` itself (it rounds times to whole frames from the
    seek point), a fraction of a frame off from a run that began earlier; seeking a quarter
    frame before it keeps it on its real time."""
    try:
        f = Fraction(fps) if fps else None
    except (ValueError, ZeroDivisionError, TypeError):
        f = None
    if not f:
        return start, start, 0.0
    first = Fraction(math.ceil(Fraction(start) * f)) / f
    return float(first - 1 / (4 * f)), float(first), float(first - Fraction(start))


def ffmpeg_command(entry, to_file=None, hls=None):
    """ffmpeg arguments that write the TV's MP4 stream to stdout - or, with to_file, the whole
    video as an ordinary MP4 the TV can seek in - or, with hls={'rel', 'k'}, HLS pieces from
    piece k on. Runs in CACHE_DIR, so burned-in subtitle files can be named without drive letters."""
    plan = entry["plan"]
    start = float(entry.get("start") or 0)
    transcode = plan["mode"] == "transcode"
    seek, first, shift = start, start, 0.0
    if hls and transcode and start > 0:
        seek, first, shift = _hls_seek(start, plan.get("fps"))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if transcode and plan.get("hw_decode"):
        cmd += ["-hwaccel", "auto"]
    if seek > 0:
        cmd += ["-ss", f"{seek:.6f}"]
    cmd += ["-i", entry["path"]]
    if transcode:
        enc = plan["encoder"]
        chain = []
        if plan["deinterlace"] == "yadif":
            chain.append("yadif")
        h = plan["target_h"]
        tail = [f"scale=-2:'min({h},ih)'", "format=nv12" if enc == "h264_qsv" else "format=yuv420p"]
        burn_file = entry.get("burn_file")
        sub = plan["sub"]
        if plan["burn"] and burn_file:
            # the subtitles filter needs the source's own clock: put the -ss offset back
            style = entry.get("burn_style", "")
            sf = f"subtitles={burn_file}" + (f":force_style='{style}'" if style else "")
            if start > 0:
                chain += [f"setpts=PTS+{start:.3f}/TB", sf, "setpts=PTS-STARTPTS"]
            else:
                chain.append(sf)
            fc = "[0:V:0]" + ",".join(chain + tail) + "[v]"
        elif plan["burn"] and sub["kind"] == "emb" and not sub["text"]:
            pre = ",".join(chain) + "," if chain else ""
            fc = f"[0:V:0]{pre}null[b];[b][0:s:{sub['index']}]overlay[o];[o]" + ",".join(tail) + "[v]"
        else:
            fc = "[0:V:0]" + ",".join(chain + tail) + "[v]"
        cmd += ["-filter_complex", fc, "-map", "[v]"]
        br = int(plan.get("kbps") or _bitrate(h))
        # HLS: keyframes only where a piece starts (see below), so a long GOP; else one every ~2 s
        gop = "600" if hls else "50"
        if enc == "h264_qsv":
            cmd += ["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", f"{br}k", "-maxrate", f"{br * 3 // 2}k",
                    "-bufsize", f"{br * 2}k", "-profile:v", "high", "-g", gop]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", f"{br * 3 // 2}k",
                    "-bufsize", f"{br * 2}k", "-profile:v", "high", "-g", gop]
        if hls:
            # A keyframe on the first frame at or after every 4-second mark of the video, and
            # nowhere else (no extra ones at scene changes), so each piece plays on its own and
            # every run - from the start, after a jump, at another quality - cuts the very same
            # frames. t counts from this run's first frame, which is `shift` past its start.
            cmd += ["-force_key_frames", f"expr:gte(t+{shift + 2e-6:.9f},n_forced*{HLS_SEG:g})"]
            if enc == "h264_qsv":
                cmd += ["-forced_idr", "1", "-adaptive_i", "0"]
            else:
                cmd += ["-sc_threshold", "0"]
    else:
        cmd += ["-map", "0:V:0?", "-c:v", "copy"]
        if plan.get("video_codec") == "hevc":
            cmd += ["-tag:v", "hvc1"]
    if plan["aspect"] != "default":
        cmd += ["-aspect", plan["aspect"]]
    cmd += ["-map", f"0:a:{plan['audio_index']}?"]
    # copied audio starts at the keyframe before -ss; that only lines up with copied video
    if plan["audio_copy"] and (not transcode or start <= 0):
        cmd += ["-c:a", "copy"]
    else:
        if plan["afilters"]:
            cmd += ["-af", ",".join(plan["afilters"])]
        ch = plan["audio_channels"]
        if plan.get("audio_out") == "ac3":  # Dolby Digital, for passthrough to a TV / soundbar
            cmd += ["-c:a", "ac3", "-b:a", "640k" if ch > 2 else "224k", "-ac", str(ch)]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k" if ch <= 2 else "384k", "-ac", str(ch)]
    # No chapters: ffmpeg turns them into an extra text track whose data only comes at the
    # very end, and the TV's player then waits for it and freezes after the first fragment.
    # delay_moov: the header waits for the first audio data - Dolby Digital (Plus) needs that
    cmd += ["-sn", "-dn", "-map_chapters", "-1"]
    if hls:  # pieces carry the video's real times, so a piece fits wherever the TV puts it
        rel = hls["rel"]
        if hls.get("t"):  # only this long (piece 0 made on the side)
            cmd += ["-t", f"{hls['t']:.3f}"]
        # frag_discont: each piece carries its real time itself (tfdt), not only the init file -
        # the TV reads init.mp4 once, so pieces made after a jump must place themselves
        # -hls_time 1: ffmpeg counts piece length from this run's own first frame, which would
        # cut some pieces a frame differently than another run; with keyframes only at the piece
        # marks and a short target, it simply cuts at every keyframe - the same frames in every run
        cmd += ["-output_ts_offset", f"{first + HLS_LEAD:.6f}", "-f", "hls", "-hls_time", "1",
                "-hls_segment_options", "movflags=+frag_discont",
                "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4", "-start_number", str(hls["k"]),
                "-hls_segment_filename", f"{rel}/seg_%d.m4s", "-hls_flags", "temp_file+independent_segments",
                "-hls_list_size", "0", f"{rel}/ffmpeg.m3u8"]
    elif to_file:  # faststart: the index goes to the front, so the TV can jump anywhere at once
        cmd += ["-movflags", "+faststart", "-f", "mp4", str(to_file)]
    else:
        cmd += ["-movflags", "frag_keyframe+empty_moov+delay_moov+default_base_moof", "-f", "mp4", "pipe:1"]
    return cmd


# --------------------------------------------------------------------------- HLS on request

class HlsJob:
    """A converted video as HLS: a playlist of the whole video in 4-second pieces, each made
    when the TV asks for it. A jump (the app's or the TV remote's) asks for a piece far away,
    and conversion restarts right there - so the TV can skip anywhere at once."""

    def __init__(self, path, plan, extra, duration, start=0.0, video=None):
        self.path = path
        self.plan = {**plan, "mode": "transcode", "audio_copy": False}  # exact pieces need a fresh encode
        self.extra = extra
        self.video = video  # the HlsVideo this quality level belongs to
        self.duration = max(float(duration or 0), HLS_SEG)
        self.n = int(-(-self.duration // HLS_SEG))
        self.start_k = min(self.n - 1, int(max(0.0, start) // HLS_SEG))
        self.rel = f"hls_{uuid.uuid4().hex[:10]}"
        self.dir = CACHE_DIR / self.rel
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.proc = None
        self.first = None
        self.closed = False
        self.last_req = self.start_k
        self.last_req_at = time.time()
        self.paused = False
        self.side = None
        threading.Thread(target=self._pace, daemon=True).start()

    def _start_side(self):
        # TVs fetch piece 0 first (to learn the start time) even when starting later on:
        # make it on the side, so the conversion at the real start point isn't restarted for it
        if self.side is not None:
            return
        (self.dir / "p0").mkdir(exist_ok=True)
        entry = dict(self.extra, plan=self.plan, path=self.path, start=0.0)
        try:
            self.side = adopt(subprocess.Popen(ffmpeg_command(entry, hls={"rel": f"{self.rel}/p0", "k": 0,
                                                                          "t": HLS_SEG + 0.2}),
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, cwd=str(CACHE_DIR), creationflags=NO_WINDOW))
        except OSError:
            self.side = None

    def _pace(self):
        """Convert as fast as possible (quick start after a jump), but pause ffmpeg once it is
        about 100 s ahead of what the TV asks for, and let it go on when the TV catches up.
        A quality level the TV stopped using is ended after a minute."""
        while not self.closed:
            time.sleep(0.5)
            with self.lock:
                if not self._running():
                    continue
                if time.time() - self.last_req_at > 60:
                    self._kill()
                    continue
                ahead = self._produced() - self.last_req
                if ahead > 25 and not self.paused:
                    self.paused = _suspend(self.proc, True)
                elif ahead < 15 and self.paused:
                    _suspend(self.proc, False)
                    self.paused = False

    def _asked(self, k):
        self.last_req, self.last_req_at = k, time.time()
        if self.video is not None:
            self.video.last_k = k

    def playlist(self):
        lines = ["#EXTM3U", "#EXT-X-VERSION:7", f"#EXT-X-TARGETDURATION:{int(HLS_SEG)}", "#EXT-X-MEDIA-SEQUENCE:0",
                 "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS", '#EXT-X-MAP:URI="init.mp4"']
        for k in range(self.n):
            d = min(HLS_SEG, self.duration - k * HLS_SEG)
            lines += [f"#EXTINF:{max(d, 0.1):.3f},", f"seg_{k}.m4s"]
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    def seg(self, k):
        return self.dir / f"seg_{k}.m4s"

    def _running(self):
        return self.proc is not None and self.proc.poll() is None

    def _produced(self):
        k = self.first if self.first is not None else 0
        while self.seg(k).exists():
            k += 1
        return k - 1

    def _restart(self, k):
        self._kill()
        self.paused = False
        self.last_req = k
        entry = dict(self.extra, plan=self.plan, path=self.path, start=k * HLS_SEG)
        try:
            self.proc = adopt(subprocess.Popen(ffmpeg_command(entry, hls={"rel": self.rel, "k": k}),
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, cwd=str(CACHE_DIR), creationflags=NO_WINDOW))
            self.first = k
        except OSError:
            self.proc = None

    def _kill(self):
        if self._running():
            try:
                if self.paused:
                    _suspend(self.proc, False)
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass

    def piece(self, k, timeout=45):
        """The file of piece k, made now if needed; None if it can't be."""
        if self.closed or not 0 <= k < self.n:
            return None
        end = time.time() + timeout
        if k == 0 and not self.seg(0).exists() and not (self._running() and self.first == 0):
            with self.lock:
                self._start_side()
        if k == 0 and self.side is not None:  # piece 0 made on the side
            side = self.dir / "p0" / "seg_0.m4s"
            while time.time() < end and not self.closed and not self.seg(0).exists():
                if side.exists():
                    try:
                        shutil.copyfile(side, self.seg(0))
                    except OSError:
                        pass
                    break
                if self.side.poll() is not None:
                    break  # the side job ended without it: make it the normal way
                time.sleep(0.1)
            if self.seg(0).exists():
                return self.seg(0)
        self._asked(k)
        restarts = 0
        while time.time() < end and not self.closed:
            f = self.seg(k)
            if f.exists():
                self._tidy(k)
                return f
            with self.lock:
                coming = self._running() and self.first is not None and self.first <= k <= self._produced() + 5
                if not coming and restarts < 2 and (restarts == 0 or not self._running()):
                    self._restart(k)  # far from what's being made (a jump), or nothing running
                    restarts += 1
            time.sleep(0.1)
        return None

    def init(self, timeout=45):
        end = time.time() + timeout
        with self.lock:
            if not self._running() and not (self.dir / "init.mp4").exists():
                # start where the video is now (a quality switch mid-way), not at its start
                k = self.video.last_k if self.video is not None and self.video.last_k is not None else self.start_k
                self._restart(min(self.n - 1, max(0, k)))
                self.last_req_at = time.time()
        while time.time() < end and not self.closed:
            f = self.dir / "init.mp4"
            if f.exists() and (self.seg(self.first or 0).exists() or self._produced() >= (self.first or 0)):
                return f
            time.sleep(0.1)
        f = self.dir / "init.mp4"
        return f if f.exists() else None

    def _tidy(self, k):
        for old in range(max(1, k - 60), max(1, k - 30)):  # keep the last ~2 minutes for rewinding (and piece 0)
            try:
                self.seg(old).unlink()
            except OSError:
                pass

    def close(self):
        self.closed = True
        with self.lock:
            self._kill()
            if self.side is not None and self.side.poll() is None:
                try:
                    self.side.kill()
                except Exception:
                    pass
        time.sleep(0.2)
        shutil.rmtree(self.dir, ignore_errors=True)


HLS_LADDER = [(1080, 8000), (720, 5000), (480, 2500)]  # height, video kbit/s


class HlsVideo:
    """A video as adaptive HLS: the same 4-second pieces at up to three quality levels.
    The TV measures its own connection and switches level by itself, seamlessly - so a
    weak connection lowers the picture quality instead of making playback hang."""

    def __init__(self, path, plan, extra, info, start=0.0):
        self.path = path
        self.last_k = None
        self.stats = {}  # bytes sent to the TV and when (see MediaHandler._serve_file)
        self.closed = False
        v = video_stream(info) or {}
        src_w, src_h = int(v.get("width") or 1920), int(v.get("height") or 1080)
        top = min(src_h, int(plan.get("target_h") or 1080), 1080)
        heights = [top] + [h for h, _ in HLS_LADDER if h < top - 100]
        duration = plan.get("duration") or duration_of(info)
        fps = frame_rate(v)  # lets every run cut its pieces at exactly the same frames
        self.levels = []
        for h in heights:
            kbps = 8000 if h > 800 else 5000 if h > 540 else 2500  # 1080p/960p, 720p, 480p
            job = HlsJob(path, {**plan, "target_h": h, "kbps": kbps, "fps": str(fps) if fps else None},
                         extra, duration, start, video=self)
            w = int(round(src_w * h / src_h / 2) * 2)
            audio_kbps = 640 if plan.get("audio_out") == "ac3" and plan["audio_channels"] > 2 else (
                384 if plan["audio_channels"] > 2 else 192)
            self.levels.append({"job": job, "height": h, "width": w, "bandwidth": int((kbps * 1.5 + audio_kbps) * 1000)})
        self.audio_codec = "ac-3" if plan.get("audio_out") == "ac3" else "mp4a.40.2"
        self.cur_level = None
        self.switches = []  # (time, piece, level) each time the TV changes quality level

    def served(self, i, k):
        """Note which quality level the TV fetches piece k from; log each change, so picture
        trouble on the TV can be matched with the moment it switched."""
        if i == self.cur_level or not 0 <= i < len(self.levels):
            return
        prev, self.cur_level = self.cur_level, i
        self.switches.append((time.time(), k, i))
        lv = self.levels[i]
        log(f"quality: TV {'starts on' if prev is None else 'switches to'} {lv['width']}x{lv['height']} "
            f"(level {i}) at {k * HLS_SEG:.0f}s of {Path(self.path).name}")

    def master(self):
        lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS"]
        for i, lv in enumerate(self.levels):
            lines += [f'#EXT-X-STREAM-INF:BANDWIDTH={lv["bandwidth"]},RESOLUTION={lv["width"]}x{lv["height"]},'
                      f'CODECS="avc1.640028,{self.audio_codec}"', f"v{i}/index.m3u8"]
        return "\n".join(lines) + "\n"

    def level(self, i):
        return self.levels[i]["job"] if 0 <= i < len(self.levels) else None

    def close(self):
        self.closed = True
        for lv in self.levels:
            lv["job"].close()


def _suspend(proc, on):
    """Pause (on=True) or continue a process; Windows only. True if it was paused."""
    if sys.platform != "win32" or proc is None or proc.poll() is not None:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x0800, False, proc.pid)  # PROCESS_SUSPEND_RESUME
        if not h:
            return False
        (ctypes.windll.ntdll.NtSuspendProcess if on else ctypes.windll.ntdll.NtResumeProcess)(h)
        ctypes.windll.kernel32.CloseHandle(h)
        return on
    except Exception:
        return False


# --------------------------------------------------------------------------- log

LOG_FILE = DATA_DIR / "videocaster.log"
_log_lock = threading.Lock()


def log(msg):
    """One line in videocaster.log, for finding out what happened."""
    try:
        with _log_lock:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
                LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- prepared (seekable) copies

PREP_DIR = CACHE_DIR / "prepared"

_CACHE_KEEP_DIRS = {"prepared", "subs"}        # seekable copies (capped elsewhere), downloaded subtitles
_CACHE_KEEP_FILES = {"speedtest.mp4", "splash.png"}
_CACHE_AGES = {"emb_": 60 * 86400, "fp_": 180 * 86400}  # extracted subtitles, audio fingerprints: kept a while


def clean_cache(dry_run=False, now=None):
    """Remove what earlier runs left behind in the cache - mainly converted HLS pieces of
    videos the app was closed in the middle of (they can add up to gigabytes) - plus the
    per-stream subtitle copies and thumbnails. Folders used in the last 5 minutes and files
    from the last day stay (another copy of the app may be playing). Returns (items, bytes)."""
    now = now or time.time()
    items = freed = 0
    try:
        entries = list(CACHE_DIR.iterdir())
    except OSError:
        return 0, 0
    for p in entries:
        try:
            if p.is_dir():
                if p.name in _CACHE_KEEP_DIRS:
                    continue
                files = [f for f in p.rglob("*") if f.is_file()]
                last = max([p.stat().st_mtime] + [f.stat().st_mtime for f in files])
                if now - last < 300:
                    continue
                size = sum(f.stat().st_size for f in files)
                if not dry_run:
                    shutil.rmtree(p, ignore_errors=True)
            else:
                if p.name in _CACHE_KEEP_FILES:
                    continue
                age = next((a for pre, a in _CACHE_AGES.items() if p.name.startswith(pre)), 86400)
                st = p.stat()
                if now - st.st_mtime < age:
                    continue
                size = st.st_size
                if not dry_run:
                    p.unlink()
            items += 1
            freed += size
        except OSError:
            continue
    return items, freed
PREP_KEEP = 4  # prepared videos kept on disk (the oldest go first)
BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


def prep_key(path, plan, fs):
    """Identifies a prepared copy: same file, same audio/picture/burned-subtitle choices."""
    parts = [str(path), _mtime(path), plan["mode"], plan["audio_index"], plan["audio_copy"], plan.get("audio_out"),
             plan["audio_channels"], tuple(plan["afilters"]), plan["deinterlace"], plan["aspect"]]
    if plan["mode"] == "transcode":
        parts += [plan["target_h"], plan["burn"]]
        if plan["burn"]:
            parts += [plan["sub"]["key"], fs.get("sub_size"), fs.get("sub_color"), fs.get("sub_delay"),
                      fs.get("sub_encoding"), plan.get("sub_font")]
    return hashlib.sha1(repr(parts).encode("utf-8")).hexdigest()[:16]


def prepared_path(key):
    return PREP_DIR / f"prep_{key}.mp4"


class Preparer:
    """Makes, in the background, an ordinary MP4 of the video that is playing as a live
    stream (repackaged, or converted when needed). The TV can't jump inside a live stream -
    its remote skip restarts it - but in that file it can, so playback switches to it as
    soon as it's ready. One video at a time, at lower priority than the live stream."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.key = None
        self.progress = 0.0

    def busy_with(self, key):
        return self.key == key and self.proc is not None and self.proc.poll() is None

    def start(self, path, plan, fs, burn_file=None, burn_style=None, on_done=None):
        key = prep_key(path, plan, fs)
        final = prepared_path(key)
        if final.exists():
            if on_done:
                on_done(key)
            return key
        with self.lock:
            if self.busy_with(key):
                return key
            self._cancel()
            PREP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = final.with_suffix(".part.mp4")
            entry = {"plan": plan, "path": path, "start": 0.0, "burn_file": burn_file, "burn_style": burn_style}
            cmd = ffmpeg_command(entry, to_file=tmp)
            cmd[1:1] = ["-y", "-progress", "pipe:1", "-nostats"]
            try:
                proc = adopt(subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, cwd=str(CACHE_DIR),
                                              creationflags=NO_WINDOW | BELOW_NORMAL))
            except OSError:
                return key
            self.proc, self.key, self.progress = proc, key, 0.0
        log(f"prepare start {Path(path).name} ({plan['mode']})")
        duration = float(plan.get("duration") or 0)

        def watch():
            for line in proc.stdout:
                if line.startswith(b"out_time_us=") and duration:
                    try:
                        self.progress = min(0.999, int(line.split(b"=")[1]) / 1e6 / duration)
                    except ValueError:
                        pass
            proc.wait()
            ok = proc.returncode == 0 and tmp.exists()
            with self.lock:
                if self.proc is proc:
                    self.proc = None
            if ok:
                tmp.replace(final)
                self.progress = 1.0
                _trim_prepared()
                log(f"prepare done {Path(path).name}")
                if on_done:
                    on_done(key)
            else:
                tmp.unlink(missing_ok=True)
                log(f"prepare stopped {Path(path).name} (exit {proc.returncode})")

        threading.Thread(target=watch, daemon=True).start()
        return key

    def _cancel(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def cancel(self):
        with self.lock:
            self._cancel()


def _trim_prepared():
    try:
        files = sorted(PREP_DIR.glob("prep_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[PREP_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def grab_frame(path, t, width=320):
    """PNG bytes of the frame at `t` seconds, or None."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}",
                            "-i", path, "-an", "-sn", "-frames:v", "1", "-vf", f"scale={width}:-2",
                            "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                           capture_output=True, timeout=20, creationflags=NO_WINDOW)
        return r.stdout if r.returncode == 0 and r.stdout else None
    except Exception:
        return None


# --------------------------------------------------------------------------- media server

# testing only: limit how fast files go to the TV, to see how a weak connection is handled
THROTTLE_KBPS = float(os.environ.get("VIDEOCASTER_THROTTLE_KBPS") or 0)


# --------------------------------------------------------------------------- casting the PC screen

def _com():
    """ctypes helpers for the Windows audio (COM) interfaces: (ctypes, GUID, guid, call)."""
    import ctypes
    import uuid as _uuid
    from ctypes import POINTER, c_ubyte, c_void_p, HRESULT, WINFUNCTYPE

    class GUID(ctypes.Structure):
        _fields_ = [("raw", c_ubyte * 16)]

    def guid(s):
        g = GUID()
        ctypes.memmove(ctypes.byref(g), _uuid.UUID(s).bytes_le, 16)
        return g

    def call(obj, index, *args, types=()):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        return WINFUNCTYPE(HRESULT, c_void_p, *types)(vtbl[index])(obj, *args)

    return ctypes, GUID, guid, call


def _speakers(objs):
    """The default speakers (IMMDevice) and their volume control (IAudioEndpointVolume); the
    COM objects are added to `objs` for releasing. Call with COM initialised in this thread."""
    ctypes, GUID, guid, call = _com()
    from ctypes import POINTER, byref, c_ulong, c_void_p
    enum, dev, vol = c_void_p(), c_void_p(), c_void_p()
    ctypes.OleDLL("ole32").CoCreateInstance(byref(guid("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 0x17,
                                            byref(guid("A95664D2-9614-4F35-A746-DE8DB63617E6")), byref(enum))
    objs.append(enum)
    call(enum, 4, 0, 0, byref(dev), types=(c_ulong, c_ulong, POINTER(c_void_p)))  # eRender, eConsole
    objs.append(dev)
    call(dev, 3, byref(guid("5CDF2C82-841E-4546-9722-0CF74078229A")), 0x17, None, byref(vol),
         types=(POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)))
    objs.append(vol)
    return dev, vol


def _volume_state(vol):
    """(muted, volume 0..1, level in dB, volume done by the hardware) from an IAudioEndpointVolume."""
    ctypes, _, _, call = _com()
    from ctypes import POINTER, byref, c_float, c_int, c_ulong
    mute, scalar, db, hw = c_int(), c_float(), c_float(), c_ulong()
    call(vol, 15, byref(mute), types=(POINTER(c_int),))  # GetMute
    call(vol, 9, byref(scalar), types=(POINTER(c_float),))  # GetMasterVolumeLevelScalar
    call(vol, 8, byref(db), types=(POINTER(c_float),))  # GetMasterVolumeLevel
    call(vol, 19, byref(hw), types=(POINTER(c_ulong),))  # QueryHardwareSupport
    return bool(mute.value), float(scalar.value), float(db.value), bool(hw.value & 0x1)  # HARDWARE_SUPPORT_VOLUME


def _release(objs):
    _, _, _, call = _com()
    for o in reversed(objs):
        try:
            call(o, 2)
        except OSError:
            pass


def speaker_state():
    """(muted, volume 0..1, level dB, hardware volume) of this PC's default speakers, or None.
    Read only. Runs in its own thread (COM there, not in the window's thread)."""
    if sys.platform != "win32":
        return None
    out = []

    def run():
        objs = []
        try:
            _com()[0].OleDLL("ole32").CoInitializeEx(None, 0)
            _, vol = _speakers(objs)
            out.append(_volume_state(vol))
        except OSError:
            pass
        finally:
            _release(objs)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    return out[0] if out else None


class LoopbackAudio:
    """The sound this PC is playing (everything you'd hear from its speakers), recorded with
    Windows' own WASAPI loopback - no extra software or 'Stereo Mix' device needed.
    - Windows sends nothing while the PC is silent: silence is filled in, so the stream goes on.
    - On most PCs Windows applies the volume slider before recording programs get the sound:
      the PC's volume level is read and the sound boosted back to full strength for the TV,
      so the PC can be turned down low. Muted gives silence (there's nothing to record then)."""

    MAX_BOOST_DB = 45.0

    def __init__(self):
        self.fmt = None  # (ffmpeg sample format, rate, channels) once opened
        self.stats = {"packets": 0, "silent": 0, "filled": 0, "muted": False, "boost_db": 0.0}
        self._out = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    def start(self, timeout=3.0):
        """Open the default speakers for recording; (sample format, rate, channels) or None."""
        if sys.platform != "win32":
            return None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.fmt

    def attach(self, out):
        """Send the recorded sound to `out` (ffmpeg's stdin) from now on."""
        self._out = out

    def stop(self):
        self._stop.set()

    def _run(self):
        import numpy as np
        ctypes, GUID, guid, call = _com()
        from ctypes import POINTER, byref, c_uint32, c_ulong, c_void_p, c_ubyte
        objs = []
        client = None
        pwfx = c_void_p()
        try:
            ctypes.OleDLL("ole32").CoInitializeEx(None, 0)
            dev, vol = _speakers(objs)
            client = c_void_p()
            call(dev, 3, byref(guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")), 0x17, None, byref(client),
                 types=(POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)))
            objs.append(client)
            call(client, 8, byref(pwfx), types=(POINTER(c_void_p),))  # GetMixFormat
            tag, ch, rate, _, block, bits, extra = struct.unpack_from("<HHIIHHH", ctypes.string_at(pwfx, 18))
            if tag == 0xFFFE and extra >= 22:  # WAVEFORMATEXTENSIBLE: the real format is in the SubFormat GUID
                tag = struct.unpack_from("<H", ctypes.string_at(pwfx, 18 + extra), 24)[0]
            fmt = {(3, 32): "f32le", (1, 16): "s16le", (1, 24): "s24le", (1, 32): "s32le"}.get((tag, bits))
            if not fmt:
                return
            # shared mode, loopback, 200 ms buffer
            call(client, 3, 0, 0x00020000, 2_000_000, 0, pwfx, None,
                 types=(c_ulong, c_ulong, ctypes.c_longlong, ctypes.c_longlong, c_void_p, c_void_p))
            cap = c_void_p()
            call(client, 14, byref(guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")), byref(cap),
                 types=(POINTER(GUID), POINTER(c_void_p)))
            objs.append(cap)
            call(client, 10)  # Start
            self.fmt = (fmt, rate, ch)
            self._ready.set()
            n, data, frames, flags = c_uint32(), POINTER(c_ubyte)(), c_uint32(), c_ulong()
            next_size = lambda: call(cap, 5, byref(n), types=(POINTER(c_uint32),))
            written, t0, gain, checked = 0, None, 1.0, 0.0
            while not self._stop.is_set():
                if time.time() - checked > 0.5:  # follow the volume slider
                    checked = time.time()
                    muted, _, db, hw = _volume_state(vol)
                    boost = 0.0 if (hw or fmt != "f32le") else min(self.MAX_BOOST_DB, max(0.0, -db))
                    gain = 10 ** (boost / 20)
                    self.stats.update(muted=muted, boost_db=round(boost, 1))
                out = self._out
                next_size()
                while n.value:
                    call(cap, 3, byref(data), byref(frames), byref(flags), None, None,
                         types=(POINTER(POINTER(c_ubyte)), POINTER(c_uint32), POINTER(c_ulong), c_void_p, c_void_p))
                    count = frames.value
                    silent = bool(flags.value & 0x2)  # AUDCLNT_BUFFERFLAGS_SILENT
                    chunk = b"\0" * (count * block) if silent else ctypes.string_at(data, count * block)
                    call(cap, 4, count, types=(c_uint32,))  # ReleaseBuffer
                    self.stats["packets"] += 1
                    self.stats["silent"] += silent
                    if out is not None:
                        if gain != 1.0 and not silent:
                            chunk = (np.frombuffer(chunk, "<f4") * np.float32(gain)).astype("<f4").tobytes()
                        out.write(chunk)
                        written += count
                    next_size()
                if out is not None:
                    t0 = t0 or time.perf_counter()
                    due = int((time.perf_counter() - t0) * rate)
                    if due - written > rate // 10:  # >100 ms behind the clock: nothing playing - fill in silence
                        out.write(b"\0" * ((due - written) * block))
                        self.stats["filled"] += due - written
                        written = due
                    out.flush()
                time.sleep(0.01)
        except (OSError, ValueError, BrokenPipeError):
            pass  # ffmpeg ended (or no speakers): stop recording
        finally:
            self._ready.set()
            out, self._out = self._out, None
            if out is not None:  # close the pipe here, quietly (ffmpeg may be gone already)
                try:
                    out.close()
                except (OSError, ValueError):
                    pass
            if client:
                try:
                    call(client, 11)  # Stop
                except OSError:
                    pass
            _release(objs)
            if pwfx:
                ctypes.windll.ole32.CoTaskMemFree(pwfx)


SCREEN_SEG = 1  # seconds per piece of the live screen stream


def screen_command(encoder, audio=None, monitor=0, fps=30, height=1080):
    """ffmpeg arguments that capture a screen (Windows' Desktop Duplication, mouse pointer
    included) plus the PC's sound from stdin (audio=(format, rate, channels); silence
    without it), and write it as live HLS into the current folder: index.m3u8, a short
    rolling playlist of 1-second fMP4 pieces. Live HLS is what every Cast receiver (Google TV
    included, which refuses an endless MP4) and Apple TV play for live streams."""
    qsv = encoder == "h264_qsv"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if audio:
        fmt, rate, ch = audio
        cmd += ["-thread_queue_size", "1024", "-f", fmt, "-ar", str(rate), "-ac", str(ch), "-i", "pipe:0"]
    else:
        cmd += ["-re", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-filter_complex", f"ddagrab=output_idx={int(monitor)}:framerate={fps}:draw_mouse=1,hwdownload,"
                               f"format=bgra,scale=-2:'min({height},ih)',format={'nv12' if qsv else 'yuv420p'}[v]",
            "-map", "[v]", "-map", "0:a"]
    # about 4 Mbit/s: plenty for a desktop, and it still flows over weaker Wi-Fi
    if qsv:
        cmd += ["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", "4000k", "-maxrate", "6000k", "-bufsize", "6000k",
                "-bf", "0", "-async_depth", "1"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "24", "-maxrate", "6000k",
                "-bufsize", "6000k"]
    # a keyframe every second (the capture runs at a steady frame rate); -force_key_frames
    # can't be used: with the capture's timestamps it stops the pieces from being written.
    # 12 pieces in the playlist: the TV plays about 6 s behind, well inside that window.
    cmd += ["-g", str(fps * SCREEN_SEG), "-profile:v", "high", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
            "-f", "hls", "-hls_time", str(SCREEN_SEG), "-hls_list_size", "12", "-hls_delete_threshold", "12",
            "-hls_flags", "delete_segments+independent_segments+temp_file",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", "seg_%d.m4s", "index.m3u8"]
    return cmd


class ScreenCast:
    """The PC screen as a live HLS stream, captured from the moment casting starts: ffmpeg
    writes 1-second pieces into a folder of its own and the media server hands them out.
    Ends by itself when the TV stops asking for a minute (stopped on the TV)."""

    NAMES = re.compile(r"^(index\.m3u8|init\.mp4|seg_\d+\.m4s)$")

    def __init__(self, encoder="libx264", monitor=0, sound=True):
        self.dir = CACHE_DIR / f"screen_{uuid.uuid4().hex[:8]}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sound = LoopbackAudio() if sound else None
        fmt = self.sound.start() if self.sound else None
        if self.sound is not None and fmt is None:
            self.sound.stop()
            self.sound = None  # no speakers to record: send silence
        self.with_sound = fmt is not None
        self.closed = False
        self.last_request = time.time()
        self.started = time.time()
        self._fetched = []  # (time, how old the piece was) for each piece the TV fetched
        self._reported = time.time()
        self.proc = adopt(subprocess.Popen(screen_command(encoder, fmt, monitor), stdin=subprocess.PIPE if fmt else
                                           subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           cwd=str(self.dir), creationflags=NO_WINDOW))
        if self.sound is not None:
            self.sound.attach(self.proc.stdin)
        threading.Thread(target=self._watch, daemon=True).start()

    def running(self):
        return not self.closed and self.proc.poll() is None

    def file(self, name, timeout=15.0):
        """One file of the stream, waiting for it if the TV asks before ffmpeg wrote it
        (the playlist exists about two seconds after the start); None if it doesn't come."""
        if not self.NAMES.match(name or ""):
            return None
        self.last_request = time.time()
        path = self.dir / name
        end = time.time() + timeout
        while not path.exists() and time.time() < end and self.running():
            time.sleep(0.1)
        if not path.exists():
            return None
        if name.startswith("seg_"):
            self._note_fetch(path)
        return path

    def _note_fetch(self, path):
        """Every 30 s, log how the TV keeps up: pieces fetched (one a second when it plays
        smoothly) and how far behind the capture it is - for when it plays jerkily."""
        now = time.time()
        try:
            self._fetched.append((now, now - path.stat().st_mtime))
        except OSError:
            return
        if now - self._reported >= 30:
            recent = [age for t, age in self._fetched if t > self._reported]
            span = now - self._reported
            self._reported = now
            self._fetched = self._fetched[-100:]
            if recent:
                log(f"screen: the TV fetched {len(recent)} pieces in {span:.0f} s (smooth = about {span:.0f}); "
                    f"they were {sum(recent) / len(recent):.1f} s old on average")

    def _watch(self):
        while not self.closed:
            time.sleep(1)
            if time.time() - self.last_request > 60 or self.proc.poll() is not None:
                self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.sound is not None:
            self.sound.stop()
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)


# --------------------------------------------------------------------------- screen mirroring

MIRROR_APP = "0F5096E8"  # Google's mirroring receiver: what Chrome's "Cast screen" talks to
MIRROR_NS = "urn:x-cast:com.google.cast.webrtc"
MIRROR_DELAY_MS = 200  # how far behind the TV plays: pieces arrive in ~10 ms, a resend in ~50 ms
MIRROR_KBPS = 5000
MIRROR_FPS = 30
_MIRROR_PT = {"audio": 127, "video": 96}  # Chrome's classic numbers; Android TV receivers expect these
_MIRROR_PAYLOAD = 1472 - 23  # UDP payload on Ethernet/Wi-Fi minus the largest RTP + Cast header
_MIRROR_VIDEO_LAG = 0.04  # a picture takes about this much longer than the sound to come out encoded


class MirrorError(Exception):
    """The TV can't mirror the screen (no mirroring receiver there, or it refused the offer)."""


def _ntp64(t):
    sec = int(t)
    return ((sec + 2208988800) & 0xFFFFFFFF) << 32 | (int((t - sec) * (1 << 32)) & 0xFFFFFFFF)


def mirror_size(src=None, height=1080):
    """The picture size sent to the TV for a screen of src=(width, height) pixels: at most
    `height` lines (1080 also suits the HD Chromecasts' decoders), even numbers, same shape."""
    sw, sh = src or (1920, 1080)
    h = min(height, sh) // 2 * 2
    return max(2, int(round(sw * h / sh / 2)) * 2), h


def mirror_video_command(encoder, monitor=0, size=(1920, 1080), kbps=MIRROR_KBPS, fps=MIRROR_FPS):
    """ffmpeg arguments: the screen (Desktop Duplication, mouse pointer included) as raw H.264 on
    stdout, one access-unit delimiter before every picture, the stream headers repeated before
    every key picture (every 2 s, so a TV that lost something recovers), no B-frames."""
    qsv = encoder == "h264_qsv"
    w, h = size
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-filter_complex",
           f"ddagrab=output_idx={int(monitor)}:framerate={fps}:draw_mouse=1,hwdownload,format=bgra,"
           f"scale={w}:{h},format={'nv12' if qsv else 'yuv420p'}[v]", "-map", "[v]"]
    if qsv:
        cmd += ["-c:v", "h264_qsv", "-preset", "veryfast", "-async_depth", "1"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency"]
    cmd += ["-profile:v", "main", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps // 2}k",
            "-bf", "0", "-g", str(fps * 2), "-bsf:v", "dump_extra=freq=keyframe,h264_metadata=aud=insert",
            "-f", "h264", "pipe:1"]
    return cmd


def mirror_audio_command(fmt):
    """ffmpeg arguments: the PC's sound (raw samples on stdin, fmt=(format, rate, channels)) as
    Opus in 10 ms packets, in Ogg pages flushed at once on stdout."""
    sfmt, rate, ch = fmt
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", sfmt, "-ar", str(rate), "-ac", str(ch),
            "-i", "pipe:0", "-ac", "2", "-ar", "48000", "-c:a", "libopus", "-b:a", "128k", "-application", "lowdelay",
            "-frame_duration", "10", "-f", "ogg", "-page_duration", "10000", "-flush_packets", "1", "pipe:1"]


def _nal_types(au):
    out, i = [], au.find(b"\x00\x00\x01")
    while i >= 0:
        if i + 3 < len(au):
            out.append(au[i + 3] & 0x1F)
        i = au.find(b"\x00\x00\x01", i + 3)
    return out


def h264_pictures(stream, on_picture, stop, fps=MIRROR_FPS):
    """Cut raw H.264 (as mirror_video_command writes it) into pictures at the access-unit
    delimiters, and call on_picture(data, time, is_key) with steady, rising timestamps."""
    buf, idx, anchor, prev = b"", 0, None, 0.0
    while not stop.is_set():
        chunk = stream.read1(1 << 16)
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(b"\x00\x00\x01\x09", 5)  # the next picture's delimiter (past this one's)
            if i < 0:
                break
            if buf[i - 1] == 0:
                i -= 1
            au, buf = buf[:i], buf[i:]
            now = time.time() - _MIRROR_VIDEO_LAG
            if anchor is None or abs(now - (anchor + idx / fps)) > 0.1:
                anchor = now - idx / fps  # the encoder fell behind, or came in a burst
            prev = max(anchor + idx / fps, prev + 0.002)
            on_picture(au, prev, 5 in _nal_types(au))
            idx += 1


def ogg_packets(stream, on_packet, stop, packet_secs=0.01):
    """The Opus packets in an Ogg stream (skipping its two header packets): on_packet(data, time)."""
    pending, n, t0, prev = b"", 0, None, 0.0
    while not stop.is_set():
        head = stream.read(27)
        if len(head) < 27 or head[:4] != b"OggS":
            break
        lacing = stream.read(head[26])
        data = stream.read(sum(lacing))
        pos = 0
        for size in lacing:
            pending += data[pos:pos + size]
            pos += size
            if size == 255:
                continue  # the packet goes on in the next segment
            n += 1
            if n > 2:
                k = n - 3
                now = time.time()
                if t0 is None or abs(now - (t0 + k * packet_secs)) > 0.2:
                    t0 = now - k * packet_secs
                prev = max(t0 + k * packet_secs, prev + 0.001)
                on_packet(pending, prev)
            pending = b""


class _MirrorStream:
    """One stream of a mirroring session (picture or sound): numbered frames, each encrypted
    (AES-128-CTR) and cut into RTP packets with the Cast header; what the TV misses is sent again."""

    def __init__(self, kind, sock, addr, ssrc, rate):
        self.kind, self.sock, self.addr, self.ssrc, self.rate = kind, sock, addr, ssrc, rate
        self.pt = _MIRROR_PT[kind]
        self.key, self.mask = os.urandom(16), os.urandom(16)
        self.tv_ssrc = None
        self.seq = random.randrange(1 << 16)
        self.rtp0 = random.randrange(1 << 32)
        self.t0 = None
        self.next_id = 0
        self.frames = {}
        self.checkpoint = -1  # the TV has every frame up to this one
        self.packets = self.octets = 0
        self.wait_key = False
        self.lock = threading.Lock()
        self.stats = {"frames": 0, "bytes": 0, "resent": 0, "skipped": 0, "picture_loss": 0}
        self.arrive = []  # seconds from sending a frame to the TV having all of it (recent)

    def offer(self, index, delay_ms, **extra):
        from cryptography.hazmat.primitives.ciphers import Cipher  # noqa: F401 (fail early if missing)
        return dict({"index": index, "type": f"{self.kind}_source", "rtpProfile": "cast", "rtpPayloadType": self.pt,
                     "ssrc": self.ssrc, "targetDelay": delay_ms, "aesKey": self.key.hex(),
                     "aesIvMask": self.mask.hex(), "timeBase": f"1/{self.rate}", "receiverRtcpEventLog": True,
                     "codecParameter": ""}, **extra)

    def _rtp(self, t):
        return (self.rtp0 + int(round((t - self.t0) * self.rate))) & 0xFFFFFFFF

    def _encrypt(self, fid, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        nonce = bytearray(16)
        nonce[8:12] = struct.pack(">I", fid & 0xFFFFFFFF)
        iv = bytes(a ^ b for a, b in zip(nonce, self.mask))
        enc = Cipher(algorithms.AES(self.key), modes.CTR(iv)).encryptor()
        return enc.update(data) + enc.finalize()

    def send(self, data, t, key):
        """Send one frame captured at time t (time.time() clock). False if it was skipped
        because the TV is far behind (pictures then wait for the next key picture)."""
        with self.lock:
            if self.next_id - 1 - self.checkpoint > 100 or (self.wait_key and not key):
                self.wait_key = self.kind == "video"
                self.stats["skipped"] += 1
                return False
            self.wait_key = False
            if self.t0 is None:
                self.t0 = t
            fid = self.next_id
            self.next_id += 1
            enc = self._encrypt(fid, data)
            fr = {"ts": self._rtp(t), "key": key, "ref": fid if key else fid - 1, "data": enc,
                  "n": max(1, -(-len(enc) // _MIRROR_PAYLOAD)), "sent": time.time(), "resent": {}}
            self.frames[fid] = fr
            self.frames.pop(fid - 240, None)
            self.stats["frames"] += 1
            self.stats["bytes"] += len(data)
            for p in range(fr["n"]):
                self._packet(fid, fr, p)
            return True

    def _packet(self, fid, fr, p):  # with the lock held
        chunk = fr["data"][p * _MIRROR_PAYLOAD:(p + 1) * _MIRROR_PAYLOAD]
        self.seq = (self.seq + 1) & 0xFFFF
        pkt = (struct.pack(">BBHII", 0x80, (0x80 if p == fr["n"] - 1 else 0) | self.pt, self.seq, fr["ts"], self.ssrc)
               + struct.pack(">BBHHB", (0x80 if fr["key"] else 0) | 0x40, fid & 0xFF, p, fr["n"] - 1, fr["ref"] & 0xFF)
               + chunk)
        try:
            self.sock.sendto(pkt, self.addr)
        except OSError:
            return
        self.packets += 1
        self.octets += len(chunk)

    def sender_report(self):
        with self.lock:
            if self.t0 is None:
                return None
            t = time.time()
            return struct.pack(">BBHIQIII", 0x80, 200, 6, self.ssrc, _ntp64(t), self._rtp(t),
                               self.packets & 0xFFFFFFFF, self.octets & 0xFFFFFFFF)

    def feedback(self, ck8, losses):
        """The TV's report: complete up to frame (8 bits of) ck8, and the packets it misses."""
        now = time.time()
        with self.lock:
            latest = self.next_id - 1
            ck = latest - ((latest - ck8) & 0xFF)
            if ck > self.checkpoint:
                for fid in range(self.checkpoint + 1, ck + 1):
                    fr = self.frames.get(fid)
                    if fr is not None and "acked" not in fr:
                        fr["acked"] = now
                        self.arrive.append(now - fr["sent"])
                del self.arrive[:-300]
                self.checkpoint = ck
            for f8, pid, bits in losses:
                fid = self.checkpoint + 1 + ((f8 - (self.checkpoint + 1)) & 0xFF)
                fr = self.frames.get(fid)
                if fr is None:
                    continue
                todo = range(fr["n"]) if pid == 0xFFFF else [pid] + [pid + 1 + i for i in range(8) if bits >> i & 1]
                for p in todo:
                    if p < fr["n"] and now - fr["resent"].get(p, 0) > 0.03:
                        fr["resent"][p] = now
                        self._packet(fid, fr, p)
                        self.stats["resent"] += 1


class ScreenMirror:
    """This PC's screen (and sound) on a Chromecast through Google's own mirroring protocol -
    Cast Streaming, what Chrome's "Cast screen" uses - a fraction of a second behind:
    - the TV runs Google's mirroring receiver; an OFFER/ANSWER sets up the streams (H.264
      picture, Opus sound) and gives a UDP port;
    - every picture and every 10 ms of sound goes there as encrypted RTP packets; the TV plays
      each at its capture time + delay_ms (the RTCP sender reports tie them to this PC's clock);
    - the TV reports which frames it has complete and which packets it misses (sent again at
      once), and logs which frames it decoded and played.
    Raises MirrorError when the TV can't mirror; the HLS ScreenCast is the fallback then."""

    STOPPED_TV = "Screen casting stopped on the TV"

    def __init__(self, cast, host, encoder="libx264", monitor=0, sound=True, src_size=None,
                 delay_ms=MIRROR_DELAY_MS, kbps=MIRROR_KBPS, timeout=10.0):
        from pychromecast.controllers import BaseController
        self.cast, self.closed, self.why = cast, False, None
        self.started = time.time()
        self.procs, self.audio = [], None
        self._stop = threading.Event()
        self.with_sound = False
        answer, got = {}, threading.Event()

        class WebRtc(BaseController):
            def receive_message(self, _msg, data):
                if data.get("type") == "ANSWER":
                    answer.update(data)
                    got.set()
                return True

        self._ctl = WebRtc(MIRROR_NS, supporting_app_id=MIRROR_APP, app_must_match=True)
        cast.register_handler(self._ctl)
        try:
            cast.start_app(MIRROR_APP, timeout=20)
        except Exception as e:
            self._unregister()
            raise MirrorError(f"the TV has no mirroring receiver ({e.__class__.__name__})") from e
        if not cast.status or cast.status.app_id != MIRROR_APP or MIRROR_NS not in (cast.status.namespaces or []):
            self._unregister()
            raise MirrorError("the TV didn't start its mirroring receiver")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
        self.sock.bind(("0.0.0.0", 0))
        addr = (host, 0)  # the port comes with the ANSWER
        self.size = mirror_size(src_size)
        a = _MirrorStream("audio", self.sock, addr, random.randrange(1, 1 << 31), 48000)
        v = _MirrorStream("video", self.sock, addr, random.randrange(1, 1 << 31), 90000)
        offered = ([a] if sound else []) + [v]
        streams = []
        for i, s in enumerate(offered):
            if s is a:
                streams.append(s.offer(i, delay_ms, codecName="opus", bitRate=128000, sampleRate=48000, channels=2))
            else:
                streams.append(s.offer(i, delay_ms, codecName="h264", channels=1, maxFrameRate=f"{MIRROR_FPS}/1",
                                       maxBitRate=kbps * 1000, resolutions=[{"width": self.size[0], "height": self.size[1]}],
                                       profile="", protection="", level="", errorRecoveryMode=""))
        self._ctl.send_message({"type": "OFFER", "seqNum": random.randrange(1, 1 << 20),
                                "offer": {"castMode": "mirroring", "supportedStreams": streams}}, no_add_request_id=True)
        if not got.wait(timeout):
            self._fail("the TV didn't answer the offer")
        ans = answer.get("answer") or {}
        if answer.get("result") not in (None, "ok") or not ans.get("udpPort"):
            err = answer.get("error") or {}
            self._fail(f"the TV refused the offer ({err.get('description') or err.get('code') or 'no reason given'})")
        addr = (host, int(ans["udpPort"]))
        self.streams = {}  # our SSRC -> stream
        self._kinds = {}   # the TV's SSRC -> stream
        for i, tv_ssrc in zip(ans.get("sendIndexes") or [], ans.get("ssrcs") or []):
            if 0 <= i < len(offered):
                s = offered[i]
                s.addr, s.tv_ssrc = addr, tv_ssrc
                self.streams[s.ssrc] = s
                self._kinds[tv_ssrc] = s
        if v.ssrc not in self.streams:
            self._fail("the TV doesn't take this picture format")
        dims = (((ans.get("constraints") or {}).get("video") or {}).get("maxDimensions") or {})
        if dims.get("width") and dims.get("height") and (dims["width"] < self.size[0] or dims["height"] < self.size[1]):
            self.size = mirror_size(self.size, min(dims["height"], int(dims["width"] * self.size[1] / self.size[0])))
        self.video, self.audio_stream = v, (a if a.ssrc in self.streams else None)
        self.tv_log = {"played": 0, "late": 0, "decoded": 0}
        self.last_feedback = None
        self._reported = time.time()
        try:
            vp = adopt(subprocess.Popen(mirror_video_command(encoder, monitor, self.size, kbps), stdout=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW))
            self.procs.append(vp)
            threading.Thread(target=h264_pictures, args=(vp.stdout, v.send, self._stop), daemon=True).start()
            if self.audio_stream is not None:
                self.audio = LoopbackAudio()
                fmt = self.audio.start()
                if fmt:
                    ap = adopt(subprocess.Popen(mirror_audio_command(fmt), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, creationflags=NO_WINDOW))
                    self.procs.append(ap)
                    self.audio.attach(ap.stdin)
                    self.with_sound = True
                    threading.Thread(target=ogg_packets, daemon=True,
                                     args=(ap.stdout, lambda d, t: a.send(d, t, True), self._stop)).start()
                else:
                    self.audio.stop()
                    self.audio = None
        except Exception as e:
            self._fail(f"couldn't start capturing the screen ({e})")
        threading.Thread(target=self._rtcp, daemon=True).start()

    def _unregister(self):
        try:
            self.cast.socket_client.unregister_handler(self._ctl)
        except Exception:
            pass

    def _fail(self, why):
        self.close(quit_tv=True)
        raise MirrorError(why)

    # ---- running
    def _rtcp(self):
        last_sr = 0.0
        self.sock.settimeout(0.05)
        while not self.closed:
            now = time.time()
            if now - last_sr >= 0.5:  # sender reports: RTP time <-> this PC's clock, twice a second
                last_sr = now
                for s in list(self.streams.values()):
                    sr = s.sender_report()
                    if sr:
                        try:
                            self.sock.sendto(sr, s.addr)
                        except OSError:
                            pass
                self._check()
            try:
                buf = self.sock.recv(65536)
            except (socket.timeout, TimeoutError, OSError):
                continue
            if len(buf) >= 2 and 200 <= buf[1] <= 207:
                self.last_feedback = time.time()
                self._parse(buf)

    def _parse(self, buf):
        off = 0
        while off + 4 <= len(buf):
            b0, pt, ln = struct.unpack_from(">BBH", buf, off)
            body = buf[off + 4:off + (ln + 1) * 4]
            off += (ln + 1) * 4
            fmt = b0 & 0x1F
            if pt == 206 and len(body) >= 8:
                s = self.streams.get(struct.unpack_from(">I", body, 4)[0])
                if s is None:
                    continue
                if fmt == 15 and len(body) >= 16 and struct.unpack_from(">I", body, 8)[0] == 0x43415354:  # 'CAST'
                    ck8, n, _delay = struct.unpack_from(">BBH", body, 12)
                    s.feedback(ck8, [struct.unpack_from(">BHB", body, 16 + 4 * i) for i in range(n)
                                     if 16 + 4 * i + 4 <= len(body)])
                elif fmt == 1:  # picture loss: the next key picture (at most 2 s away) repairs it
                    s.stats["picture_loss"] += 1
            elif pt == 204 and len(body) >= 8 and struct.unpack_from(">I", body, 4)[0] == 0x43415354:
                s = self._kinds.get(struct.unpack_from(">I", body)[0])
                if s is self.video:
                    self._tv_frame_log(body[8:])

    def _tv_frame_log(self, d):
        # the TV's own log; event types on the wire: 11 acked, 12 played (value: ms early, - is late),
        # 13 decoded, 14 packet received
        off = 0
        while off + 8 <= len(d):
            count = (struct.unpack_from(">I", d, off + 4)[0] >> 24) + 1
            off += 8
            for _ in range(count):
                if off + 4 > len(d):
                    return
                val, tw = struct.unpack_from(">HH", d, off)
                off += 4
                if tw >> 12 == 12:
                    self.tv_log["played"] += 1
                    self.tv_log["late"] += val >= 0x8000
                elif tw >> 12 == 13:
                    self.tv_log["decoded"] += 1

    def _check(self):
        """Still on? Stops when the TV closed the receiver, stopped answering, or a capture ended."""
        if self.closed:
            return
        why = None
        st = self.cast.status
        if st is not None and st.app_id != MIRROR_APP:
            why = self.STOPPED_TV
        elif self.last_feedback is None and time.time() - self.started > 20:
            why = "The TV didn't show the screen"
        elif self.last_feedback is not None and time.time() - self.last_feedback > 10:
            why = "The TV stopped answering"
        elif any(p.poll() is not None for p in self.procs):
            why = "The screen capture stopped"
        if why:
            self.why = why
            self.close()
            return
        if time.time() - self._reported >= 30:
            self._reported = time.time()
            v, arr = self.video, sorted(self.video.arrive)
            log(f"screen: mirroring - {self.tv_log['played']} pictures played on the TV ({self.tv_log['late']} late), "
                f"{v.stats['resent']} packets sent again, {v.stats['skipped']} pictures skipped, "
                f"frames complete there after {arr[len(arr) // 2] * 1000 if arr else 0:.0f} ms (median)")

    def state(self):
        """'starting', 'playing' (the TV shows it) or 'stopped' (see .why)."""
        if self.closed:
            return "stopped"
        if self.tv_log["played"] or (self.video.checkpoint >= 30 and not self.tv_log["decoded"]):
            return "playing"
        return "starting"

    def running(self):
        return not self.closed

    def close(self, quit_tv=False):
        """Stop sending; quit_tv also closes the receiver on the TV (back to its home screen)."""
        first = not self.closed
        self.closed = True
        self._stop.set()
        if first:
            if self.audio is not None:
                self.audio.stop()
            for p in self.procs:
                try:
                    p.kill()
                except Exception:
                    pass
            try:
                self.sock.close()
            except Exception:
                pass
            self._unregister()
        if quit_tv:
            try:
                st = self.cast.status
                if st is not None and st.app_id == MIRROR_APP:
                    self.cast.quit_app(timeout=10)
            except Exception:
                pass


class MediaHandler(BaseHTTPRequestHandler):
    """Serves only what the app registered for the TV: video files (with byte ranges,
    so the TV can seek), subtitles, thumbnails and live ffmpeg conversions. Every
    other path gets a 404, so no other files on this PC are exposed."""

    server_version = "VideoCaster/2.0"
    protocol_version = "HTTP/1.1"
    media = None  # MediaServer, set on the bound subclass

    def log_message(self, fmt, *args):
        return

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._handle(head=True)

    def do_GET(self):
        self._handle(head=False)

    def _handle(self, head):
        entry = self.media.lookup(self.path) if self.media else None
        if not entry:
            self.send_error(404)
            return
        if entry["kind"] == "transcode":
            self._serve_transcode(entry, head)
        elif entry["kind"] == "screen":
            self._serve_screen(entry, head)
        elif entry["kind"] == "hls":
            self._serve_hls(entry, head)
        else:
            self._serve_file(entry["path"], entry.get("mime"), head, entry)

    def _serve_hls(self, entry, head):
        video = entry["job"]
        parts = self.path.split("?", 1)[0].strip("/").split("/")  # m, token, [v<i>,] name
        name = parts[-1]
        job = None
        if len(parts) >= 4 and parts[2].startswith("v") and parts[2][1:].isdigit():
            job = video.level(int(parts[2][1:]))
        if job is None and name == "index.m3u8":  # the master playlist: the quality levels
            body = video.master().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        if job is None:
            self.send_error(404)
            return
        if name.endswith(".m3u8"):
            body = job.playlist().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        f = None
        if name == "init.mp4":
            f = job.init()
        elif name.startswith("seg_") and name.endswith(".m4s"):
            try:
                k = int(name[4:-4])
                f = job.piece(k)
                if f is not None:
                    video.served(int(parts[2][1:]), k)
            except ValueError:
                f = None
        if f is None:
            self.send_error(404 if not name.startswith(("seg_", "init")) else 503)
            return
        self._serve_file(str(f), "video/mp4", head, video.stats)

    def _serve_file(self, path, mime, head, entry=None):
        try:
            size = os.path.getsize(path)
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return
        with f:
            start, end, status = 0, size - 1, 200
            m = re.match(r"\s*bytes=(\d*)-(\d*)\s*$", self.headers.get("Range") or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", mime or mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._cors()
            self.end_headers()
            if head:
                return
            f.seek(start)
            remaining = length
            try:
                while remaining > 0:
                    chunk = f.read(min((1 << 16) if THROTTLE_KBPS else (1 << 20), remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
                    if THROTTLE_KBPS:  # testing only: pretend the connection is weak
                        time.sleep(len(chunk) * 8 / (THROTTLE_KBPS * 1000))
                    if entry is not None:  # for the speed test
                        now = time.time()
                        entry.setdefault("first", now)
                        entry["last"] = now
                        entry["sent"] = entry.get("sent", 0) + len(chunk)
            except OSError:
                self.close_connection = True

    def _serve_transcode(self, entry, head):
        # A live conversion has no length up front: send ffmpeg's output as it comes
        # until ffmpeg ends or the TV hangs up, and close the connection to mark the end.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        if head:
            return
        # A second request for the same live stream means the TV restarted it - that's what
        # its remote's skip does with a live stream. Tell the app, which continues where it was.
        entry["requests"] = entry.get("requests", 0) + 1
        if entry["requests"] > 1 and self.media.on_rerequest:
            try:
                self.media.on_rerequest(entry)
            except Exception:
                pass
        proc = self.media.start_transcode(entry)
        if proc is None:
            return
        try:
            while True:
                chunk = proc.stdout.read1(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                now = time.time()
                entry.setdefault("first", now)
                entry["last"] = now
                entry["sent"] = entry.get("sent", 0) + len(chunk)
        except OSError:
            pass
        finally:
            self.media.end_transcode(proc)

    def _serve_screen(self, entry, head):
        # the live screen stream: its playlist (always fresh) and its 1-second pieces
        name = self.path.split("?", 1)[0].strip("/").split("/")[-1]
        f = entry["cast"].file(name)
        if f is None:
            self.send_error(404)
            return
        if name.endswith(".m3u8"):
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        self._serve_file(str(f), "video/mp4", head, entry)


class QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # TVs drop idle and finished connections all the time; that's not worth a traceback
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class MediaServer:
    def __init__(self, host="0.0.0.0"):
        self.host = host
        self.tokens: dict[str, dict] = {}
        self.transcodes: set[subprocess.Popen] = set()
        self.lock = threading.Lock()
        self.httpd = None
        self.port = 0
        self.ip = None
        self.on_rerequest = None  # called (from a server thread) when the TV restarts a live stream
        self.hls_jobs: list[HlsJob] = []
        self.screens: list[ScreenCast] = []

    def start(self):
        handler = type("BoundMediaHandler", (MediaHandler,), {"media": self})
        self.httpd = QuietHTTPServer((self.host, 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.stop_transcodes()
        if self.httpd:
            self.httpd.shutdown()

    def base_url(self):
        ip = "127.0.0.1" if self.host == "127.0.0.1" else get_local_ip()
        return f"http://{ip}:{self.port}"

    def register(self, path, kind="media", name=None, **extra):
        tok = uuid.uuid4().hex
        self.tokens[tok] = dict(extra, kind=kind, path=path, token=tok)
        return f"{self.base_url()}/m/{tok}/{quote(name or Path(path).name)}"

    def lookup(self, url_path):
        # /m/<token>/<name>; anything else is refused
        parts = url_path.split("?", 1)[0].strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "m":
            entry = self.tokens.get(parts[1])
            if entry and (entry["kind"] == "screen" or os.path.isfile(entry["path"])):
                return entry
        return None

    def add_screen(self, cast):
        """Serve a ScreenCast to the TV: the playlist URL (its pieces sit next to it)."""
        with self.lock:
            self.screens.append(cast)
        return self.register("screen", "screen", name="index.m3u8", cast=cast)

    def start_transcode(self, entry):
        CACHE_DIR.mkdir(exist_ok=True)
        try:
            proc = adopt(subprocess.Popen(ffmpeg_command(entry), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, cwd=str(CACHE_DIR), creationflags=NO_WINDOW))
        except OSError:
            return None
        with self.lock:
            self.transcodes.add(proc)
        return proc

    def end_transcode(self, proc):
        with self.lock:
            self.transcodes.discard(proc)
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.stdout.close()
            proc.wait(timeout=5)
        except Exception:
            pass

    def stop_transcodes(self, keep=None):
        """End every conversion (live streams and HLS videos), except the HLS video `keep`."""
        with self.lock:
            procs = list(self.transcodes)
            jobs = [j for j in self.hls_jobs if j is not keep]
            self.hls_jobs = [j for j in self.hls_jobs if j is keep]
            screens, self.screens = self.screens, []
        for s in screens:
            s.close()
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        for j in jobs:
            j.close()


def prepare_stream(server, path, info, fs, gs, start=0.0, encoder="libx264"):
    """Register everything the TV needs for `path` and return a dict with the URLs.
    start: where a converted stream begins (a direct file starts there on the TV instead)."""
    fs = {**FILE_DEFAULTS, **(fs or {})}
    plan = plan_stream(path, info, fs, gs, encoder)
    CACHE_DIR.mkdir(exist_ok=True)
    prepared = None
    if plan["mode"] != "direct":
        plan["key"] = prep_key(path, plan, fs)
        if prepared_path(plan["key"]).exists() and not gs.get("force_hls"):  # an ordinary MP4 the TV can seek in
            prepared = prepared_path(plan["key"])
            try:
                os.utime(prepared)  # recently used: kept longest
            except OSError:
                pass
    # adaptive HLS for anything converted - and for everything once the connection proved weak
    use_hls = gs.get("hls", True) and not prepared and (plan["mode"] != "direct" or gs.get("force_hls"))
    offset = 0.0 if (plan["mode"] == "direct" or prepared or use_hls) else float(start)
    out = {"plan": plan, "offset": offset, "title": Path(path).name, "sub_url": None, "burn_file": None,
           "burn_style": None, "fs": fs, "prepared": bool(prepared), "hls": use_hls}

    sub = plan["sub"]
    cues = []
    if sub["kind"] != "none" and (sub["text"]):
        cues = subtitle_cues(path, sub, fs["sub_encoding"])
    if sub["kind"] == "emb":
        subs = subtitle_streams(info)
        out["sub_lang"] = _lang(subs[sub["index"]]) if sub["index"] < len(subs) else ""
    color_cc, color_ass = SUB_COLORS.get(fs["sub_color"], SUB_COLORS["White"])
    out["sub_style"] = subtitle_style(fs, gs)
    tag = uuid.uuid4().hex[:8]
    # "Up next" countdown on the TV: lines in the subtitle track from where the credits begin
    title = gs.get("up_next_title")
    credits = gs.get("credits")
    if title and gs.get("up_next", True) and credits is None:
        credits = detect_credits(path, info)  # about a second; the app remembers it
    out["credits"] = credits
    soft = cues if (cues and not plan["burn"]) else []
    shift = float(fs["sub_delay"])
    track = [(s + shift, e + shift, lines) for s, e, lines in soft]
    if title and gs.get("up_next", True) and credits and credits > 0:
        track += upnext_cues(credits, title)
        out["upnext_window"] = (credits, credits + UPNEXT_SECS)
    intro = gs.get("intro")  # (start, end) if already known: the "Skipping intro" countdown on the TV
    if gs.get("skip_intro", True) and intro and intro[1] - intro[0] > INTRO_SECS + 3 and intro[0] >= start - 1:
        track += intro_cues(intro[0])
        out["intro_window"] = (intro[0], intro[0] + INTRO_SECS)
    out["sub_has_text"] = bool(soft)  # real subtitles in the track (not only the countdown)
    if track:
        vtt = CACHE_DIR / f"sub_{tag}.vtt"
        vtt.write_text(cues_to_vtt(track, -offset), encoding="utf-8")
        out["sub_url"] = server.register(str(vtt), "sub", name="subtitles.vtt", mime="text/vtt")
    entry_extra = {}
    if cues and plan["burn"]:
        srt = CACHE_DIR / f"burn_{tag}.srt"
        srt.write_text(cues_to_srt(cues, float(fs["sub_delay"])), encoding="utf-8")
        entry_extra["burn_file"] = srt.name
        entry_extra["burn_style"] = burn_style(fs, gs)
        out["burn_file"], out["burn_style"] = entry_extra["burn_file"], entry_extra["burn_style"]

    if prepared:
        out["url"] = server.register(str(prepared), "media", name=Path(path).stem + ".mp4", mime="video/mp4")
        out["mime"] = "video/mp4"
        out["live"] = False
    elif plan["mode"] == "direct" and not use_hls:
        plan["mime"] = mimetypes.guess_type(path)[0] or "video/mp4"
        out["url"] = server.register(path, "media", mime=plan["mime"])
        out["mime"] = plan["mime"]
        out["live"] = False
    elif use_hls:  # 4-second pieces made on request, at several qualities: skippable and adaptive
        job = HlsVideo(path, plan, entry_extra, info, start)
        with server.lock:
            server.hls_jobs.append(job)
        out["hls_job"] = job
        out["stats"] = job.stats
        out["kbps"] = job.levels[0]["bandwidth"] / 1000
        out["url"] = server.register(path, "hls", name="index.m3u8", job=job)
        out["mime"] = "application/x-mpegurl"
        out["live"] = False
    else:
        out["url"] = server.register(path, "transcode", name=Path(path).stem + ".mp4",
                                     plan=plan, start=offset, **entry_extra)
        out["mime"] = "video/mp4"
        out["live"] = True
    out["token"] = out["url"].split("/m/", 1)[1].split("/", 1)[0]
    if "stats" not in out:  # bytes sent to the TV for this stream, and when
        out["stats"] = server.tokens[out["token"]]
        src = prepared or (path if plan["mode"] == "direct" else None)
        dur = plan.get("duration") or 0
        out["kbps"] = (os.path.getsize(src) * 8 / dur / 1000) if src and dur else (_bitrate(plan["target_h"]) + 200)
    return out


# --------------------------------------------------------------------------- devices

class AioThread:
    """One asyncio loop on its own thread, for pyatv (its connections live on one loop)."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


class Device:
    def __init__(self, dev_id, kind, name, model="", cast_type="cast", online=False, obj=None):
        self.id, self.kind, self.name, self.model = dev_id, kind, name, model
        self.cast_type, self.online, self.obj = cast_type, online, obj
        self.host = None  # last known address, to find it when it doesn't announce itself

    @property
    def video(self):
        return self.cast_type not in ("audio", "group")

    def describe(self):
        kind = "Chromecast" if self.kind == "chromecast" else "AirPlay"
        if not self.video:
            kind += " speaker"
        return f"{kind}{' - ' + self.model if self.model else ''}{'' if self.online else ' (not found right now)'}"


class Discovery:
    """Keeps a live list of Chromecasts (continuous mDNS browsing) and AirPlay devices
    (scanned on start and on request). on_change() is called from worker threads."""

    def __init__(self, on_change, known=None):
        self.on_change = on_change
        self.devices: dict[str, Device] = {}
        for d in known or []:
            self.devices[d["id"]] = Device(d["id"], d["kind"], d["name"], d.get("model", ""), d.get("cast_type", "cast"))
            self.devices[d["id"]].host = d.get("host")
        self.lock = threading.Lock()
        self.zconf = None
        self.browser = None
        self.aio = AioThread() if pyatv else None
        self._last_atv_scan = 0.0

    def start(self):
        if pychromecast:
            try:
                self.zconf = zeroconf.Zeroconf()
                listener = SimpleCastListener(self._cc_add, self._cc_remove, self._cc_update)
                # keep browsing while the app runs: a Chromecast looks up its address
                # through this every time it (re)connects
                # known_hosts: also ask the TVs seen before directly - some Chromecasts stop
                # announcing themselves on the network now and then (seen with 'Slaapkamer')
                hosts = sorted({d.host for d in self.devices.values() if d.kind == "chromecast" and d.host})
                self.browser = CastBrowser(listener, self.zconf, known_hosts=hosts or None)
                self.browser.start_discovery()
            except Exception:
                log("Chromecast discovery failed: " + traceback.format_exc())
                self.browser = None
        self.scan_airplay()

    def stop(self):
        try:
            if self.browser:
                self.browser.stop_discovery()
            if self.zconf:
                self.zconf.close()
        except Exception:
            pass

    def _cc_add(self, uid, service):
        self._cc_update(uid, service)

    def _cc_update(self, uid, service):
        info = self.browser.devices.get(uid) if self.browser else None
        if info is None:
            return
        key = f"cc:{uid}"
        with self.lock:
            dev = self.devices.get(key) or Device(key, "chromecast", info.friendly_name)
            dev.name = info.friendly_name or dev.name
            dev.model = info.model_name or ""
            dev.cast_type = info.cast_type or "cast"
            dev.host = info.host or dev.host
            dev.online = True
            dev.removed_at = None
            if dev.obj is None:
                try:
                    dev.obj = pychromecast.get_chromecast_from_cast_info(info, self.zconf)
                except Exception:
                    log("Chromecast initialization failed: " + traceback.format_exc())
                    dev.obj = None
            self.devices[key] = dev
        self.on_change()

    def _cc_remove(self, uid, service, cast_info):
        # Some Chromecasts (Google TV) briefly withdraw and re-announce themselves when their
        # receiver restarts - e.g. when connecting. Only call one offline if it stays gone.
        key = f"cc:{uid}"
        with self.lock:
            dev = self.devices.get(key)
            if dev:
                dev.removed_at = time.time()

        def later(stamp):
            time.sleep(15)
            with self.lock:
                d = self.devices.get(key)
                if d is None or getattr(d, "removed_at", None) != stamp:
                    return  # it came back
                d.online = False
            self.on_change()

        if dev:
            threading.Thread(target=later, args=(dev.removed_at,), daemon=True).start()

    def scan_airplay(self, force=False):
        if not self.aio or (not force and time.time() - self._last_atv_scan < 30):
            return
        self._last_atv_scan = time.time()

        def work():
            try:
                confs = self.aio.run(pyatv.scan(self.aio.loop, timeout=5), timeout=15)
            except Exception:
                return
            seen = set()
            with self.lock:
                for conf in confs:
                    key = f"atv:{conf.identifier}"
                    seen.add(key)
                    model = ""
                    try:
                        model = conf.device_info.model_str
                    except Exception:
                        pass
                    dev = self.devices.get(key) or Device(key, "appletv", conf.name)
                    dev.name, dev.model, dev.online, dev.obj = conf.name, model or "", True, conf
                    self.devices[key] = dev
                for key, dev in self.devices.items():
                    if dev.kind == "appletv" and key not in seen:
                        dev.online = False
            self.on_change()

        threading.Thread(target=work, daemon=True).start()

    def snapshot(self):
        with self.lock:
            return sorted(self.devices.values(), key=lambda d: (d.name.lower(), d.kind))

    def known(self):
        with self.lock:
            return [{"id": d.id, "kind": d.kind, "name": d.name, "model": d.model, "cast_type": d.cast_type,
                     "host": d.host} for d in self.devices.values()]


# --------------------------------------------------------------------------- players

MEDIA_RECEIVER = "CC1AD845"  # Google's Default Media Receiver


class ChromecastPlayer:
    kind = "chromecast"

    def __init__(self, device):
        self.device = device
        self.cast = device.obj
        self.mc = self.cast.media_controller

    @property
    def receiver(self):
        return self.cast.socket_client.receiver_controller

    def connect(self, timeout=15, fresh=False):
        """Connect to the TV. fresh: close whatever receiver runs on it and start a new one.
        A receiver that has been used a lot can get stuck playing sound without picture;
        a new one always shows video (found on a Philips Android TV)."""
        try:
            self.cast.wait(timeout=timeout)  # raises RequestTimeout when it can't connect
        except Exception:
            pass
        if self.cast.status is None:
            raise RuntimeError(f"Couldn't connect to {self.device.name}. Check that it is switched on and on the "
                               "same network as this PC.")
        if fresh:
            if self.cast.status.app_id not in (None, "E8C28D3C"):  # E8C28D3C = the TV's idle backdrop
                try:
                    self.cast.quit_app(timeout=10)
                except Exception:
                    pass
                end = time.time() + 6
                while time.time() < end and self.cast.status and self.cast.status.app_id == MEDIA_RECEIVER:
                    time.sleep(0.3)
                time.sleep(1.0)
            self.cast.start_app(MEDIA_RECEIVER, timeout=20)

    def receiver_name(self):
        try:
            return self.cast.status.display_name or "Receiver"
        except Exception:
            return "Receiver"

    def muted(self):
        try:
            return bool(self.cast.status.volume_muted)
        except Exception:
            return False

    def set_muted(self, on):
        self.receiver.set_volume_muted(bool(on))

    def disconnect(self):
        """Close the receiver: the TV goes back to what it showed before."""
        try:
            self.cast.quit_app(timeout=10)
        except Exception:
            pass

    def _leave_mirroring(self):
        # After the screen was mirrored the TV still runs Google's mirroring receiver, which
        # also answers on the media channel: start the media receiver before loading anything
        st = getattr(self.cast, "status", None)
        if st is not None and st.app_id == MIRROR_APP:
            self.cast.start_app(MEDIA_RECEIVER, timeout=20)

    def load(self, s, start):
        self._leave_mirroring()
        direct = not s["live"]
        subs = {}
        if s.get("sub_url"):
            # pychromecast puts the track in the LOAD message *and* switches it on there
            # (activeTrackIds); switching it on afterwards is ignored while a converted
            # stream is still starting up
            subs = dict(subtitles=s["sub_url"], subtitles_mime="text/vtt", subtitle_id=1,
                        subtitles_lang=s.get("sub_lang") or "en")
        self.sub_style = s.get("sub_style")
        # Which TV media session is ours is learnt from the first status naming this URL;
        # until then, and for any other session (the stream this one replaced), the
        # status says nothing about this video.
        self._clear_picture()
        self.url = s["url"]
        self.session_id = None
        self.load_at = time.time()
        self.our_urls = getattr(self, "our_urls", set()) | {s["url"]}
        hls = {"media_info": {"hlsSegmentFormat": "fmp4", "hlsVideoSegmentFormat": "fmp4"}} if s.get("hls") else {}
        # The PC screen is a live HLS stream, but announced as LIVE the receiver keeps jumping
        # to the live edge: one picture per piece and buffering in between (measured on
        # 'Slaapkamer'). Announced as BUFFERED it plays the same playlist smoothly.
        live_type = s["live"] and not s.get("screen")
        self.mc.play_media(s["url"], s["mime"], title=s["title"], thumb=s.get("thumb_url"),
                           current_time=start if direct and start > 0 else None,
                           stream_type="LIVE" if live_type else "BUFFERED", **subs, **hls)
        self.mc.block_until_active(timeout=30)
        if subs:
            threading.Thread(target=self._ensure_subtitles, daemon=True).start()

    def _ensure_subtitles(self, timeout=90):
        """Once the TV is really playing, make sure the subtitle track is on and styled;
        repeat until the TV reports it active."""
        end = time.time() + timeout
        while time.time() < end:
            st = self.mc.status
            if st is not None and st.media_session_id and st.player_state in ("PLAYING", "PAUSED"):
                if 1 in (st.current_subtitle_tracks or []):
                    self.set_sub_style(self.sub_style)  # size and colour
                    self.subs_active = True
                    return
                self.set_sub_style(self.sub_style)
                time.sleep(2)
                self.refresh()
                continue
            time.sleep(0.5)
        self.subs_active = False

    subs_active = None

    def set_sub_style(self, style):
        try:
            msg = {"type": "EDIT_TRACKS_INFO", "activeTrackIds": [1]}
            if style:
                msg["textTrackStyle"] = style
            self.mc._send_command(msg, None)
        except Exception:
            pass

    def hide_text(self):
        """Switch the subtitle track off (e.g. an 'Up next' countdown that was cancelled)."""
        try:
            self.mc._send_command({"type": "EDIT_TRACKS_INFO", "activeTrackIds": []}, None)
        except Exception:
            pass

    def play(self):
        self.mc.play()

    def pause(self):
        self.mc.pause()

    def stop(self):
        self.mc.stop()

    def seek(self, t):
        self.mc.seek(max(0.0, t))

    def volume(self):
        try:
            return float(self.cast.status.volume_level)
        except Exception:
            return None

    def set_volume(self, v):
        self.receiver.set_volume(max(0.0, min(1.0, v)))

    def refresh(self):
        try:
            self.mc.update_status()
        except Exception:
            pass

    def show_picture(self, url, title=APP_NAME):
        """Show a still picture on the TV (the 'connected' screen)."""
        self._leave_mirroring()
        self.our_urls = getattr(self, "our_urls", set()) | {url}
        self.mc.play_media(url, "image/png", title=title)
        self.mc.block_until_active(timeout=15)
        self.showing_picture = True

    def _clear_picture(self):
        # After a still picture, a Chromecast with Google TV doesn't take an HLS video unless
        # the picture is stopped first (measured on 'Slaapkamer')
        if getattr(self, "showing_picture", False):
            self.showing_picture = False
            try:
                self.mc.stop()
            except Exception:
                return
            for _ in range(30):
                time.sleep(0.1)
                st = self.mc.status
                if st is None or st.player_state in ("IDLE", "UNKNOWN", None):
                    break

    def state(self):
        """(state, position) with state in playing/paused/buffering/idle/finished/error,
        or 'loading' while the TV hasn't reported on this video yet."""
        st = self.mc.status
        if st is None or not st.player_state:
            return "idle", 0.0
        url = getattr(self, "url", None)
        if url is not None:
            if st.content_id == url and st.media_session_id:
                # a status naming this video: its session is ours (the first one after a load
                # can still carry the previous session's number, so keep following it)
                self.session_id = st.media_session_id
            elif self.session_id is None:
                if time.time() - self.load_at < 40:
                    return "loading", 0.0
            elif st.media_session_id and st.media_session_id != self.session_id:
                if st.content_id and st.content_id not in self.our_urls:
                    return "idle", 0.0  # another app took over the TV
                return "loading", 0.0  # the status of a stream we replaced
        ps = st.player_state
        if ps == "PLAYING":
            return "playing", st.adjusted_current_time or 0.0
        if ps == "PAUSED":
            return "paused", st.current_time or 0.0
        if ps == "BUFFERING":
            return "buffering", st.current_time or 0.0
        if ps == "IDLE":
            reason = st.idle_reason or ""
            return ("finished" if reason == "FINISHED" else "error" if reason == "ERROR" else "idle"), st.current_time or 0.0
        return "idle", 0.0

    def close(self):
        pass


class AppleTvPlayer:
    kind = "appletv"

    def __init__(self, device, aio):
        self.device = device
        self.aio = aio
        self.atv = None
        self.play_future = None
        self._volume = None

    def connect(self, timeout=20, fresh=False):
        if self.atv is None:
            try:
                self.atv = self.aio.run(pyatv.connect(self.device.obj, self.aio.loop), timeout)
            except Exception as e:
                raise RuntimeError(f"Couldn't connect to {self.device.name}: {e}") from e

    def show_picture(self, url, title=APP_NAME):
        pass  # AirPlay video only; nothing to show until a video plays

    def receiver_name(self):
        return "AirPlay"

    def muted(self):
        return False

    def set_muted(self, on):
        self.set_volume(0.0 if on else (self._volume or 0.3))

    def disconnect(self):
        self.stop()
        self.close()

    def load(self, s, start):
        if self.play_future:
            self.play_future.cancel()
        self.play_future = self.aio.submit(self.atv.stream.play_url(s["url"]))
        if start > 0 and not s["live"]:
            def later():
                time.sleep(4)
                try:
                    self.seek(start)
                except Exception:
                    pass
            threading.Thread(target=later, daemon=True).start()

    def set_sub_style(self, style):
        pass

    def hide_text(self):
        pass

    def play(self):
        self.aio.run(self.atv.remote_control.play(), 10)

    def pause(self):
        self.aio.run(self.atv.remote_control.pause(), 10)

    def stop(self):
        if self.play_future:
            self.play_future.cancel()
        try:
            self.aio.run(self.atv.remote_control.stop(), 10)
        except Exception:
            pass

    def seek(self, t):
        self.aio.run(self.atv.remote_control.set_position(int(max(0, t))), 10)

    def volume(self):
        try:
            return float(self.atv.audio.volume) / 100.0
        except Exception:
            return None

    def set_volume(self, v):
        if v > 0:
            self._volume = v
        self.aio.run(self.atv.audio.set_volume(max(0.0, min(100.0, v * 100))), 10)

    def refresh(self):
        pass

    def state(self):
        try:
            p = self.aio.run(self.atv.metadata.playing(), 5)
        except Exception:
            return "idle", 0.0
        pos = float(p.position or 0)
        ds = p.device_state
        if ds == DeviceState.Playing:
            return "playing", pos
        if ds == DeviceState.Paused:
            return "paused", pos
        if ds in (DeviceState.Loading, DeviceState.Seeking):
            return "buffering", pos
        if self.play_future is not None and self.play_future.done() and not self.play_future.cancelled():
            return ("error" if self.play_future.exception() else "finished"), pos
        return "idle", pos

    def close(self):
        try:
            if self.atv:
                self.atv.close()
        except Exception:
            pass
        self.atv = None


def make_speedtest_clip():
    """A 12 s, 40 Mbit/s noise video (no sound) the TV downloads during the speed test."""
    CACHE_DIR.mkdir(exist_ok=True)
    clip = CACHE_DIR / "speedtest.mp4"
    if not clip.exists():
        tmp = CACHE_DIR / "speedtest.tmp.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
                        "-i", "testsrc2=size=1280x720:rate=30,noise=alls=60:allf=t", "-t", "12", "-c:v", "libx264",
                        "-preset", "ultrafast", "-b:v", "40M", "-minrate", "40M", "-maxrate", "40M", "-bufsize", "40M",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, timeout=180, creationflags=NO_WINDOW, check=True)
        tmp.replace(clip)
    return clip


def speed_test(server, player, seconds=10):
    """How fast the TV can download from this PC, in Mbit/s: it plays a high-bitrate test
    video (muted) and we time the bytes it pulls."""
    clip = make_speedtest_clip()
    url = server.register(str(clip), "media", name="speedtest.mp4", mime="video/mp4")
    entry = server.tokens[url.split("/m/", 1)[1].split("/", 1)[0]]
    size = os.path.getsize(clip)
    was_muted = player.muted()
    try:
        player.set_muted(True)
    except Exception:
        pass
    try:
        player.load({"url": url, "mime": "video/mp4", "title": "Speed test", "live": False}, 0.0)
        end = time.time() + seconds
        while time.time() < end and entry.get("sent", 0) < size:
            time.sleep(0.2)
        player.stop()
    finally:
        try:
            player.set_muted(was_muted)
        except Exception:
            pass
    sent, first, last = entry.get("sent", 0), entry.get("first"), entry.get("last")
    if not sent or not first or not last or last - first < 0.2:
        raise RuntimeError("The TV didn't download the test video.")
    return sent * 8 / (last - first) / 1e6


def make_player(device, discovery):
    if device.kind == "chromecast":
        if device.obj is None:
            raise RuntimeError(f"{device.name} isn't available right now.")
        return ChromecastPlayer(device)
    if not pyatv or device.obj is None:
        raise RuntimeError(f"{device.name} isn't available right now.")
    return AppleTvPlayer(device, discovery.aio)
