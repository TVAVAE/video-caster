Video Caster 0.3.8 for Windows.

**If you have 0.3.5, 0.3.6 or 0.3.7:** it offers this version by itself - 0.3.7 with a Windows notification, all of them with a bar in the window. Those versions check at most once a day, so it can take until the next day; *About Video Caster* → *Check for updates* checks right away. **If you have 0.3.3 or 0.3.4:** install it by hand once; their update check can fail.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **Video Caster checks for a new version every time it opens**, in the background a few seconds after the window appears, without slowing anything down. Before, it asked GitHub at most once a day, so a version released in the meantime could wait until the next day. Left open, it still checks once a day. When there's a new version you see the bar in the window, and once per version a Windows notification.
- The settings' help text for *Updates* and the README say so.

Shown on Windows 11 with the app from the source and a stand-in GitHub on the PC: two openings less than a minute apart each asked for the newest release about 3 seconds after the window appeared; the first showed the bar and a notification, the second the bar.

0.3.7 brought: Video Caster starts again by itself after an update, and a Windows notification for a new version.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
