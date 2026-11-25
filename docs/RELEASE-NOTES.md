Video Caster 0.3.3 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **Updates install themselves**: once a day Video Caster asks GitHub whether there's a newer version. Only that question is sent, nothing about you or your videos. When there is one, a bar in the window offers it, with a *What's new* link:
  - *Update now* downloads the new Setup (with progress, and you can cancel) and checks it against the release's `SHA256SUMS.txt`. It then installs it over the old version (Windows asks for permission) and starts Video Caster again. Your playlists and settings stay.
  - *Later* hides the offer for three days.
  - The portable executable gets a *Download* link to the release page instead.
  - Switch the daily check off with *Updates* in the settings. *About Video Caster* (also in the settings) shows the version and has *Check for updates*.
- **The back-10-seconds button** now shows an arrow turning back (anticlockwise); it used to look like it turned forward.
- For developers: the version is set in one place, `APP_VERSION` in `app/backend.py`, and the installer build reads it from there.

The update check, the download with its checksum check, cancelling, and the bar were tested against a stand-in release on the PC, and the check against GitHub itself. The last step, Setup upgrading an installed copy and starting it again, will first run for real with the release after this one, since only copies from 0.3.3 on have the updater. Install 0.3.3 once by hand.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
