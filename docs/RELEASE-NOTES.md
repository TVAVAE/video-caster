Video Caster 0.3.5 for Windows.

**If you have 0.3.3 or 0.3.4: install this version by hand once.** Their update check can fail (see below), so they may not offer it themselves. From 0.3.5 on, updates come by themselves.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's fixed

- **The update check works**: *Check for updates* could fail with "certificate verify failed: unable to get issuer certificate", so no update was offered. The cause: the app checked secure connections only against Windows' certificate store. That store can lack the root certificate some of GitHub's connections end at, because Windows fetches such certificates only for its own programs. Video Caster now also uses the standard certifi list of trusted certificates (Mozilla's), for the update check and download as well as the online subtitle search, which could hit the same error.
- For diagnosing: `VideoCaster.exe --check-update report.json` runs the update check from a command line and writes the outcome to a file.

0.3.4 brought: the PC stays awake while something is on the TV, and the keyboard's media keys control the TV.

The fixed check was run from the built program itself, several times in a row, against GitHub.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
