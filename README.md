# Ambrogio — release images

**Ambrogio** is a self-hosted household assistant that runs on a Raspberry Pi in your
home. It reads your email, manages your calendar, drives smart-home devices, and talks
to you from a phone app — all from a box you own, on your own network.

This repository hosts the **flashable appliance images** and the flashing guide. The
application source lives in a separate repository and is **not** redistributed here; see
[LICENSE](LICENSE.md).

> **Heads up — these images are for personal, non-commercial use.** Ambrogio is released
> under the [PolyForm Noncommercial 1.0.0](LICENSE.md) license.

## What you need

- A **Raspberry Pi 4 or 5** (2 GB RAM minimum; 4 GB recommended).
- A **microSD card** (16 GB or larger).
- The **Raspberry Pi Imager** on your computer — <https://www.raspberrypi.com/software/>.
- The **Ambrogio app** on your phone (to finish setup once the box boots).

## Flash it (the short version)

Add this repository to Raspberry Pi Imager and pick the latest Ambrogio image:

```
rpi-imager --repo https://github.com/simonerom/Ambrogio-releases/releases/latest/download/ambrogio-repo.json
```

That command opens the Imager with Ambrogio already listed. Choose it, pick your SD card,
and write. The `latest` link always points at the newest release, so it never goes stale.

Prefer to do it by hand, or want the full walkthrough (Wi-Fi, first boot, claiming the box
from the app)? See **[FLASHING.md](FLASHING.md)**.

## After flashing

1. Put the SD card in the Pi and power it on.
2. Open the Ambrogio app — it finds the box on your network and walks you through claiming
   it and giving it a brain (a Claude subscription token or API key).

The image ships with **no remote login enabled** — access to the box is by physical
possession, the way a home appliance should be.

## Verifying a download

Every release includes a `.sha256` file next to the image. To check an image you
downloaded manually:

```
sha256sum -c ambrogio-<version>.img.xz.sha256
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) — personal, hobby, educational, charitable,
and other noncommercial use is permitted. Commercial use requires a separate agreement.
