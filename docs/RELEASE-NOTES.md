Video Caster 0.3.1 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

A cleaner window that says what it does:

- **Show your screen on the TV**: the screen button now opens one panel instead of a list of menu items. It offers two choices, *Mirror my screen* (the TV shows what you see) or *Second display* (drag windows onto the TV). Below them are the screen to mirror (only when you have more than one), *PC sound on the TV* and *Low delay*, each with a line on what to expect, then *Start sharing*. While sharing, the same panel offers *Stop sharing* and switching to the other choice.
- **A live bar** while your screen is on the TV, so it's never on there by accident. It says what's shown where (for example "Your screen is on Living Room TV"), how far behind it is, and whether the sound is on, or that the PC is muted. It has a sound button and *Stop sharing*. The "PC is muted" pop-up is gone; the panel and the bar say it instead.
- **The TV in the header**: the TV button became the TV's name with a status dot (green when connected, yellow while connecting, grey when not connected yet), or *Choose a TV* when none is chosen. Click it for the TV's volume, *Disconnect* and *Speed Test*, or to pick another TV.
- **An empty playlist shows what you can do**: *Play videos*, *Mirror my screen* or *Second display*. Click one to start; dropping videos still works anywhere in the playlist.

The new panel, bar, header and playlist screen were checked on the PC with a stand-in TV. Screen mirroring itself is unchanged since 0.3.0, where it was used on a Chromecast with Google TV and a Philips Android TV. Playback on a physical Apple TV is still untested.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
