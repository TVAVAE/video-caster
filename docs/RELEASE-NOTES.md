Video Caster 0.3.2 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks and an optional virtual display when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **The virtual display in Setup**: a new option, *Install the virtual display for 'Second display'*, installs the [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver) (MIT license) together with Video Caster. It's unticked by default and available when installing for all users. Without it, Video Caster still offers to install the driver the first time you choose *Second display*.
- **A clean uninstall**: uninstalling Video Caster now also removes the virtual display (its device, its driver and `C:\VirtualDisplayDriver`), but only if Video Caster installed it. A Virtual Display Driver you set up yourself, or that another program installed, stays.
- **Third-party components in the README**: FFmpeg and the Virtual Display Driver, with their projects, licenses and the exact releases the build uses.

Removing the driver and installing it from scratch through the app were both tested on a Windows 11 PC. Setup's new option runs that same install step; Setup itself was built but not yet run with the option ticked.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license (MIT) is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
