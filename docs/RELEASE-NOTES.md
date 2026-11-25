Video Caster 0.3.0 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks when installed for all users. Installing over an earlier version keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **Use the TV as a second display**: a new option in the screen button's menu adds an extra screen to the right of yours and shows it on the TV. Drag a window onto it to put it on the TV, and keep working on your own screen. The extra screen is there only while it's cast: when you stop, its windows come back to your screen. Windows needs a virtual display for this. Video Caster includes the free, open-source [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver) (MIT license) and installs it the first time you use the option, after asking you; Windows then asks for admin permission, just once.
- **The right screen is cast** on PCs with more than one display, also when Windows lists the displays in a different order than Video Caster does.
- **Fix**: stopping a mirrored screen without the app's picture coming back now also closes the mirroring on the TV.

Screen mirroring has now been used on a Chromecast with Google TV and on a Philips Android TV with Chromecast built-in: every picture played on time, also in a 12-minute session. The second display was checked on the PC: switching it on and off, casting it, and installing the driver through the app. It was also cast to the Philips TV, using the same virtual display set up by hand. Playback on a physical Apple TV is still untested.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595). The Virtual Display Driver's license is installed as `licenses\VirtualDisplayDriver-LICENSE.txt`.
