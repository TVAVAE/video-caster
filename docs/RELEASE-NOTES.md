The first Windows installer and portable release of Video Caster.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks when installed for all users.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## Changes

- Added repeatable Windows executable and installer builds.
- Fixed missing SSL runtime support that could prevent Chromecast connections and stop AirPlay from loading in packaged builds.
- Packaged builds preserve playlists, watch progress, settings and cache under `%LOCALAPPDATA%\Video Caster\`.
- Added a connection report command for diagnosing TV discovery and connection failures.
- Updated the README with downloads, installation, troubleshooting and build instructions.

The Windows build was checked for installation/uninstallation, settings preservation, H.264/AAC encoding, FFprobe, Chromaprint, and a real Chromecast connection. AirPlay libraries were checked for successful loading; playback on a physical Apple TV was not tested.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595).
