Video Caster 0.3.4 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings. Version 0.3.3 offers this update by itself.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **The PC stays awake while something is on the TV**: Windows used to go to sleep during a film or a shared screen, because nobody touched the PC, and the TV then stopped. Now:
  - a video on the TV keeps the PC awake (the screen may still switch off);
  - a shared screen keeps the PC and its screen on;
  - paused for half an hour, Windows may sleep again;
  - with nothing on the TV, Windows' own sleep settings apply as before.
- **Media keys control the TV**: while something is on the TV, the keyboard's play/pause, next, previous (back 10 seconds) and stop keys control it, also when Video Caster isn't the active window. Stop also ends sharing the screen. The rest of the time the keys are left to other players; the volume keys always stay with Windows.

Both were checked in the window with a stand-in TV, including a real press of the keyboard's play/pause key and reading back what the app asks Windows for, and on a PC with three monitors.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
