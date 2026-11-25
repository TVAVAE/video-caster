Video Caster 0.2.1 for Windows.

## Downloads

- **VideoCaster-Setup.exe**: recommended. Includes Python, FFmpeg, FFprobe and Chromaprint. Installs shortcuts and an uninstaller, with optional firewall rules for private local networks when installed for all users. Installing over 0.2.0 or 0.1.0 keeps your playlists, watch progress and settings.
- **VideoCaster.exe**: portable app with Python included. Install FFmpeg and FFprobe separately, or place them beside the executable or in `ffmpeg\bin` next to it.
- **SHA256SUMS.txt**: checksums for both Windows downloads.

Windows 10 or 11, 64-bit. Keep the PC and TV on the same network. The binaries are unsigned, so Windows may ask for confirmation.

## What's new

- **Cast your screen with almost no delay**: on a Chromecast, Google TV or TV with Chromecast built-in, the screen now goes over Google's own screen-mirroring protocol, the one Chrome's *Cast screen* uses. The TV is a fraction of a second behind instead of several seconds, so the mouse pointer and videos from the browser follow along. *Low delay (mirroring)* in the screen button's menu switches it off. A TV that doesn't accept mirroring gets the screen as a video stream instead, automatically.
- **The screen as a video stream plays smoothly**: when the screen is sent as a video stream (on an Apple TV, or with *Low delay* off), a Chromecast with Google TV now plays it smoothly instead of showing one picture every second or so. It stays about 6 seconds behind.
- **4K films start reliably**: after a jump into a 4K film, the first converted picture can take longer than 30 seconds. The app used to give up at that point and switch that TV to a fallback format for good, which a Chromecast with Google TV can't play. After that, every converted video failed on that TV. The app now waits up to 90 seconds while the TV is still downloading. It undoes that wrong switch once after updating, and returns to the normal format if the fallback fails.
- **No stray conversions after a crash**: FFmpeg conversions and screen captures now always end with the app, even when it's closed by force.

Screen mirroring was measured on a Chromecast with Google TV (HD): at the 200 ms delay the app uses, every picture and sound frame was played on time. The version built into the app was checked on the PC against a stand-in receiver. It hasn't been tried yet on a TV with Chromecast built-in. Playback on a physical Apple TV is still untested.

The installer contains the Gyan FFmpeg 9.1 full build. Its GPLv3 license, build configuration, and upstream source reference are included under `ffmpeg` in the installation directory. See the [FFmpeg build provider](https://www.gyan.dev/ffmpeg/builds/) and [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/74e4393595).
