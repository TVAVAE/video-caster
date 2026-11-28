Video Caster 0.3.10 for Windows.

**If you have 0.3.5 to 0.3.9:** it offers this version by itself - 0.3.7 and later with a Windows notification, all of them with a bar in the window. 0.3.8 and 0.3.9 ask every time they open; 0.3.5 to 0.3.7 at most once a day, so it can take until the next day there. *About Video Caster* → *Check for updates* checks right away. **If you have 0.3.3 or 0.3.4:** install it by hand once; their update check can fail.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **One window.** Starting Video Caster while it's already open now brings the open window forward, and videos you started it with are added to its playlist, instead of opening a second copy. Two copies each saved their own playlists, watch progress and settings over the other's - and with them the result of the update check, so a new version found by one could go unnoticed in the other.
- Two starts at the same moment still give one window. A start while Video Caster is closing (also right after an update) waits until it has saved and closed, then opens. A copy that doesn't answer for 20 seconds doesn't stop a new one.
- Each Windows user on the PC has their own window.

Tested with real starts of the app (from the source and the built one-file executable): a second start with a video, two starts at the same moment, a start while the window is closing, and another settings file.

0.3.9 brought: the check for a new version runs only when Video Caster opens. 0.3.8: a check at every opening. 0.3.7: Video Caster starts again by itself after an update, and a Windows notification for a new version.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
