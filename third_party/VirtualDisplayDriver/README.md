# Virtual Display Driver

*Use the TV as a second display* needs a display that Windows can extend the desktop onto.
Video Caster uses the **Virtual Display Driver** by the
[VirtualDrivers project](https://github.com/VirtualDrivers/Virtual-Display-Driver) for this:
an open-source Indirect Display driver under the [MIT license](LICENSE). It is signed by the
SignPath Foundation.

The driver isn't stored in this repository. The build (`build-windows.ps1`) takes it from
that project's release, pinned to one exact file:

| | |
| --- | --- |
| Release | [25.7.23](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23) (driver version 24.12.24) |
| File | `VirtualDisplayDriver-x86.Driver.Only.zip` (132,118 bytes; 64-bit Intel/AMD despite the name) |
| SHA-256 | `E24210692B442B39AF763536330CE78B423F19342B7A7792C26DE3944E418B3A` |

The build checks that hash and the files' signatures. It then puts the driver files
(`MttVDD.inf`, `MttVDD.dll`, `mttvdd.cat`, `vdd_settings.xml`) and this license into the
executable. Pass `-DisplayDriverZip <path>` to use a copy you downloaded yourself; otherwise
the build downloads the file above.

It is installed in one of two ways, both running `VideoCaster.exe --install-display-driver`
with admin rights:

- **In Setup**: the optional task *Install the virtual display* (unticked by default; only
  when installing for all users, since a driver needs admin rights).
- **On first use**: the first time someone chooses *Second display*, Video Caster asks first,
  then Windows asks for admin permission, and the app runs itself once with admin rights.

Either way the app does what `devcon install MttVDD.inf Root\MttVDD` would do. It copies the
files to `C:\VirtualDisplayDriver` (where the driver reads its settings), creates the device
`Root\MttVDD`, and installs the driver on it. When it created the device itself, it leaves
`installed-by-video-caster.txt` there.

**Uninstalling** Video Caster (installed for all users) runs
`VideoCaster.exe --uninstall-display-driver -`. That removes the device, the driver package
from Windows' driver store, and `C:\VirtualDisplayDriver` - but only when that file shows Video
Caster installed it. A Virtual Display Driver set up by hand, or by another program, stays.

To remove it by hand: Device Manager → *Display adapters* → *Virtual Display Driver* →
*Uninstall device* (tick *Attempt to remove the driver for this device*). Then delete
`C:\VirtualDisplayDriver`.

To move to a newer release, change the URL and hash in `build-windows.ps1` and in this file.
