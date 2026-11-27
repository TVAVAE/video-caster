Video Caster 0.3.6 for Windows.

**If you have 0.3.5:** it offers this version by itself - a bar in the window, or *About Video Caster* → *Check for updates*. **If you have 0.3.3 or 0.3.4:** install it by hand once; their update check can fail.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's fixed

- **The TV display is only on while it's cast.** The extra screen that *Second display* casts could stay on when nothing was cast - for instance when it was set up by hand, or when Windows switched it on by itself after docking or plugging in a monitor. Windows and the mouse then ended up on a screen nobody sees. Video Caster now switches it off after casting, when it starts, and within seconds whenever Windows switches it on while it runs.
- **New setting: *Second display: off when it's not cast*** (on by default). Untick it if you use the virtual display for something else too; Video Caster then leaves it as it is.
- **A virtual display switched off in Device Manager**: *Second display* offers to switch it back on (Windows asks for permission once), instead of trying to install a second copy. Switching it back on doesn't touch its files in `C:\VirtualDisplayDriver`.

Tested on Windows 11 with the Virtual Display Driver: switched on from outside, the way Windows does it, at start and while the app runs - each time off again within seconds; with the setting unticked it stays on; *Second display* still casts it and switches it off at *Stop*.

0.3.5 brought: the update check works (it could fail with a certificate error in 0.3.3 and 0.3.4).

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
