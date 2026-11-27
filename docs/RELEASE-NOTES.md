Video Caster 0.3.9 for Windows.

**If you have 0.3.5 to 0.3.8:** it offers this version by itself - 0.3.7 and 0.3.8 with a Windows notification, all of them with a bar in the window. 0.3.8 asks every time it opens; 0.3.5 to 0.3.7 at most once a day, so it can take until the next day there. *About Video Caster* → *Check for updates* checks right away. **If you have 0.3.3 or 0.3.4:** install it by hand once; their update check can fail.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **The check for a new version runs only when Video Caster opens**, in the background a few seconds after the window appears. 0.3.8 also asked once a day while the window stayed open; that timer is gone, so a window left open doesn't ask again until you open Video Caster again.
- **Later** hides the update bar until the next opening (it was three days). The Windows notification still comes once per version.
- The settings' help text for *Updates* and the README say so.

0.3.8 brought: a check for a new version every time the app opens. 0.3.7: Video Caster starts again by itself after an update, and a Windows notification for a new version.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
