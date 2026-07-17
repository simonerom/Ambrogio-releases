# Flashing Ambrogio onto a Raspberry Pi

This guide takes you from a blank SD card to a running Ambrogio box you've claimed from
the app. It should take about 15–20 minutes, most of which is the SD card writing.

## Before you start

You'll need:

- A **Raspberry Pi 4 or 5** (2 GB RAM minimum, 4 GB recommended) and its power supply.
- A **microSD card**, 16 GB or larger, and a way to connect it to your computer.
- **Raspberry Pi Imager** installed — <https://www.raspberrypi.com/software/>.
- The **Ambrogio app** on your phone, on the same Wi-Fi you'll use for the box.

## Step 1 — Add the Ambrogio image to Raspberry Pi Imager

Ambrogio publishes a repository file that Raspberry Pi Imager can read directly, so you
don't have to download the image by hand.

**Option A — one command (macOS / Linux):**

```
rpi-imager --repo https://github.com/simonerom/Ambrogio-releases/releases/latest/download/ambrogio-repo.json
```

This launches the Imager with Ambrogio already in the OS list. The `latest` link always
resolves to the newest release.

**Option B — by hand:**

1. Go to the [latest release](https://github.com/simonerom/Ambrogio-releases/releases/latest).
2. Download `ambrogio-<version>.img.xz` and, optionally, its `.sha256`.
3. In Raspberry Pi Imager, choose **"Use custom"** and select the `.img.xz` you downloaded.

## Step 2 — Write the card

1. In the Imager, select your Ambrogio image (from Step 1).
2. Choose your **SD card** as the target. Double-check it's the right device — writing
   erases everything on it.
3. When the Imager offers **OS customisation / advanced options**, you can pre-fill your
   **Wi-Fi network name and password** here. This is the easiest way to get the box online
   with no Ethernet cable — fill it in before writing.
4. Write, and wait for the verify step to finish.

## Step 3 — First boot

1. Put the card in the Pi and connect power.
2. The first boot takes a few minutes — the box sets itself up and joins your Wi-Fi.
3. There is **no screen or keyboard needed**, and **no remote login** — the box is
   designed to be set up entirely from the app.

## Step 4 — Claim it from the app

1. Open the **Ambrogio app** on your phone (same Wi-Fi as the box).
2. The app discovers the box on your network and asks you to **claim** it — this makes the
   box yours. Follow the prompts.
3. Give the box a **brain**: paste a Claude **subscription token** (from `claude
   setup-token`) or an **Anthropic API key**. Ambrogio needs this to think.
4. That's it — say hello in the app.

## Verifying your download (optional)

If you downloaded the image by hand and want to confirm it's intact:

```
sha256sum -c ambrogio-<version>.img.xz.sha256
```

A `... OK` line means the download matches the published checksum.

## Troubleshooting

- **The app doesn't find the box.** Give it a couple of minutes after first boot, and make
  sure your phone is on the **same Wi-Fi** as the Pi. If you didn't pre-fill Wi-Fi in the
  Imager, the box may have come up without a network — re-flash with Wi-Fi filled in
  (Step 2.3), or use the app's Wi-Fi setup flow.
- **You want to start over.** Re-flash the SD card from Step 2. Your data lives on the box;
  a re-flash returns it to a fresh, unclaimed state.

## License

These images are provided under [PolyForm Noncommercial 1.0.0](LICENSE.md) — for personal,
hobby, educational, and other noncommercial use.
