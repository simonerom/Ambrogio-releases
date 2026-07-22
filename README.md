# Ambrogio — release images

**Ambrogio** is a self-hosted household assistant that runs on a Raspberry Pi in your
home. It reads your email, manages your calendar, drives smart-home devices, and talks
to you from a phone app — all from a box you own, on your own network.

This repository hosts the **flashable appliance images** and the flashing guide — there's
also a **[landing page](https://simonerom.github.io/Ambrogio-releases/)** with the same
links in a friendlier shape. The application source lives in a separate repository and is
**not** redistributed here; see [LICENSE](LICENSE.md).

> **Heads up — these images are for personal, non-commercial use.** Ambrogio is released
> under the [PolyForm Noncommercial 1.0.0](LICENSE.md) license.

## What you need

- A **Raspberry Pi 4 or 5** (2 GB RAM minimum; 4 GB recommended) and its power supply.
- A **microSD card** (16 GB or larger). On macOS/Linux, a **USB SD reader** — a card in a
  laptop's built-in slot often reports as non-removable and the flashing script won't write
  to it.
- **Python 3** on your computer (it runs the flashing script). macOS and Linux have it;
  on Windows install it from <https://www.python.org/downloads/>.
- The **Ambrogio app** on your iPhone — currently in open beta via TestFlight:
  **[install it here](https://testflight.apple.com/join/kft9Hhv3)** (Apple's free TestFlight
  app handles it). No Android build yet — you can still reach the box's web console in a
  browser after setup.

## Flash it (the short version)

**macOS & Linux — one command.** Download the little flashing script and run it: it fetches
the latest image, flashes the SD card you pick, and writes the box's claim code — all in one,
nothing else to install.

```
curl -LO https://github.com/simonerom/Ambrogio-releases/raw/main/tools/flash_box.py
sudo python3 flash_box.py --flash
```

**Windows, or prefer a GUI?** Use Raspberry Pi Imager: **Choose OS → Use custom** and pick the
`ambrogio-<version>.img.xz` from the [latest release](https://github.com/simonerom/Ambrogio-releases/releases/latest),
write it, then run `python3 flash_box.py` on the card to add the claim code.

Either way, **don't skip the claim code**: a box flashed without one boots and joins your
network, but can never be claimed — by you or anyone else. The code is how you prove, at claim
time, that the box in question is physically yours. Print the code sheet the script saves.

Full walkthrough (both routes, Wi-Fi, first boot, claiming, recovery): see **[FLASHING.md](FLASHING.md)**.

## After flashing

1. Put the SD card in the Pi and power it on.
2. Get it on your network: plug in an **Ethernet cable**, or let the app set up **Wi-Fi** for
   it (you'll scan the QR from your code sheet).
3. Open the **[Ambrogio app](https://testflight.apple.com/join/kft9Hhv3)** — it finds the box,
   asks for the **claim code** from your printed sheet, and walks you through giving the box a
   brain (a Claude subscription token or API key).

The image ships with **no remote login enabled** — access to the box is by physical
possession, the way a home appliance should be.

## Verifying a download

The flashing script verifies the image's checksum for you. If you downloaded the `.img.xz`
by hand, every release includes a `.sha256` next to it — check it with:

```
shasum -a 256 -c ambrogio-<version>.img.xz.sha256    # macOS
sha256sum -c ambrogio-<version>.img.xz.sha256         # Linux
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) — personal, hobby, educational, charitable,
and other noncommercial use is permitted. Commercial use requires a separate agreement.
