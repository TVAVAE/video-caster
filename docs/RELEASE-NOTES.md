Video Caster 0.3.7 for Windows.

**If you have 0.3.5 or 0.3.6:** it offers this version by itself - a bar in the window when you open it, or *About Video Caster* → *Check for updates*. **If you have 0.3.3 or 0.3.4:** install it by hand once; their update check can fail.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's fixed

- **Video Caster starts again after an update.** After an update from inside the app, the new version could fail to start with "Failed to load Python DLL ... python312.dll". The update itself was installed - start Video Caster from the Start menu if you saw this. The cause: the app runs from a temporary folder and passed notes about it on to Setup, so the new version looked for its files in the old copy's folder, deleted by then. Setup now starts Video Caster with a clean slate, so the update from 0.3.6 to 0.3.7 already starts it again; the app itself no longer passes those notes on either.

## What's new

- **A Windows notification for a new version**, besides the bar in the window: you see it with Video Caster in the background too. Once per version; click it to bring the window with *Update now* forward. Your 0.3.6 doesn't have this yet, so for this update you see the bar when you open Video Caster.
- **Left open for days, Video Caster still checks once a day** for a new version (before, only when it started).
- The Start menu and desktop shortcuts carry the app's ID, so Windows names its notifications "Video Caster".

Tested: an update of a one-file stand-in through a test Setup with this release's restart lines - the old ones reproduce the error, the new ones start it again, also the way an all-users installation does it.

0.3.6 brought: the TV display of *Second display* is only on while it's cast.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
