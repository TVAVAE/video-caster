Video Caster 0.2.0 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks when installed for all users. Installing over 0.1.0 keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **Cast your screen**: a new button next to the gear shows your whole PC screen on the TV, live, with the PC's sound - no extra software needed. The PC must not be muted (a low volume is fine). The TV shows it a few seconds late, so it's meant for websites, photos and presentations rather than games.
- **The window opens on your screen** again when it was last closed on a monitor that is no longer connected (it used to start off-screen).
- **A logo of its own**: the app, its taskbar button, shortcuts and the installer now show the Video Caster logo.
- **Closing never freezes**: when a TV the app knows doesn't answer (switched off, or the PC is on another network), closing used to hang for up to half a minute until Windows reported "not responding". The window now closes at once.
- **The cache cleans itself**: leftovers of videos that were closed mid-way, which could add up to gigabytes, are removed in the background when the app starts.

Cast Screen was checked on the PC (screen and sound capture, the live stream, and the window with a stand-in TV); it has not yet been tried on a physical TV. Playback on a physical Apple TV is still untested.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595).
