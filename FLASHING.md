# Flashing Ambrogio onto a Raspberry Pi

This guide takes you from a blank SD card to a running Ambrogio box you've claimed from
the app. Budget about 15–20 minutes, most of it the card writing itself.

Every box needs a **claim code** written onto its card before first boot — it's the one
proof that *you* are the person holding the box, and without it the box can never be
claimed (see [Why the claim code](#why-the-claim-code)). A small Python script,
[`flash_box.py`](tools/flash_box.py), writes that code. Because you're running the script
anyway, the quickest path lets it do the whole job — download, flash, and code — in one
command.

## Before you start

You'll need:

- A **Raspberry Pi 4 or 5** (2 GB RAM minimum, 4 GB recommended) and its power supply.
- A **microSD card**, 16 GB or larger, and a way to connect it to your computer.
- **Python 3** on your computer (both options below use it for the claim code). macOS and
  Linux have it already; on Windows install it from <https://www.python.org/downloads/>
  (tick "Add Python to PATH").
- The **Ambrogio app** on your iPhone. It's in open beta:
  **[install it via TestFlight](https://testflight.apple.com/join/kft9Hhv3)** (Apple's free
  TestFlight app handles it). No Android build yet — on Android you can still reach the
  box's web console in a browser after setup.

Then pick one of the two ways to write the card.

## Option 1 — one command does everything (macOS & Linux)

The script downloads the latest image, flashes your card, and writes the claim code — no
separate imager app to install, and nothing else to set up: it needs only stock Python 3
(it unpacks the compressed image itself).

1. **Download the script** (anywhere — your Downloads folder is fine):

   ```
   curl -LO https://github.com/simonerom/Ambrogio-releases/raw/main/tools/flash_box.py
   ```

2. **Put your SD card in the reader**, then run:

   ```
   sudo python3 flash_box.py --flash
   ```

   It needs `sudo` because writing a card is a low-level operation. Then it:
   - downloads the newest Ambrogio image and **verifies its checksum**;
   - lists your **removable disks** and asks which one is the SD card (it never lists your
     internal disk);
   - **warns you before erasing** the card and waits for you to confirm;
   - writes the image with a progress bar, then writes the claim code onto it.

3. It finishes by printing the **claim code** and saving a **printable code sheet** — see
   [The code sheet](#the-code-sheet). Then eject the card and go to
   [First boot](#first-boot--getting-the-box-online).

## Option 2 — Raspberry Pi Imager (all platforms, including Windows)

Prefer a graphical tool, or on Windows? Use Raspberry Pi Imager to write the card, then run
the script once to add the code.

1. **Install Raspberry Pi Imager** — <https://www.raspberrypi.com/software/>.
2. **Download the image**: from the
   [latest release](https://github.com/simonerom/Ambrogio-releases/releases/latest),
   download `ambrogio-<version>.img.xz`.
3. **Write it**: open Raspberry Pi Imager, choose your Raspberry Pi model, then
   **Choose OS → Use custom** and pick the `.img.xz` you downloaded. Choose your **SD card**
   as the storage, and write. (There's no OS-customisation step — Ambrogio sets its own
   hostname and accounts, and takes Wi-Fi from the app; just write the image as-is.)
4. **Put the claim code on the card.** Leave the card in the reader. Download the script
   (as in Option 1, step 1) and run it with **no arguments**:

   ```
   python3 flash_box.py
   ```

   It finds the freshly written card, writes the code onto it, and prints the
   [code sheet](#the-code-sheet). (No `sudo` needed here — it only writes a small file to
   the card's boot partition.)

## The code sheet

However you wrote the card, the script prints something like:

```
====================================================
  Claim code:   K7PM-3XQR-VD     (type it as K7PM3XQRVD)
  Setup Wi-Fi:  Ambrogio-9C41A7
  The code is the box's claim code AND its setup Wi-Fi password.
====================================================

  Printable code sheet:  ~/ambrogio-claim-codes/ambrogio-9C41A7-claim-code.html
```

**Print the code sheet and keep it.** Open that HTML file in a browser and print it (or Save
as PDF). It holds the code, the box's setup Wi-Fi name, and a QR you can scan to join that
Wi-Fi. Nothing on the box can ever tell you the code later — this sheet is your only copy.
Treat it like a house key.

<details>
<summary>Script options, and what to do if something goes sideways</summary>

- `python3 flash_box.py --boot /Volumes/bootfs` — inject into a specific mounted boot
  partition (macOS shown; Linux `/media/you/bootfs`, Windows `E:\`) if auto-detect can't
  find it.
- `python3 flash_box.py --secret CODE` — use a code you choose instead of a generated one.
- `python3 flash_box.py --force` — replace a code already on the card.
- `sudo python3 flash_box.py --device /dev/diskN --image FILE` — the manual form of
  `--flash`: write a specific image file you already downloaded to a specific device.
- **Lost a code for a box you already CLAIMED?** `python3 flash_box.py --force-rekey` adopts
  a new code onto an owned box, **keeping its data**. (A plain re-inject is refused on a
  claimed box, so a stray card can't hijack it.)

The script needs only stock Python 3 — no install, no dependencies. The code sheet's Wi-Fi QR
is drawn by the script itself, so it's always there.

</details>

## Why the claim code

An unclaimed box on your network has no users yet, so there's nothing to log in as. The
claim code is not a password — it is **proof that you are the person holding the box**,
which is the only thing that distinguishes you from anyone else who can reach it on your
network. Whoever claims the box gets your email, your Claude token, and an assistant that
acts on your behalf, so Ambrogio will not hand that to whoever asks first.

That's why the box never invents a code of its own: a code the box made up is a code you'd
have no way of knowing. The code has to come from the person who wrote the card — you.

**A box with no code refuses every claim, permanently.** It will say so in the app rather
than asking you for a code that doesn't exist.

## First boot — getting the box online

1. Put the card in the Pi and connect power. The first boot takes a few minutes while the
   box sets itself up. No screen, no keyboard, and no remote login are needed — everything
   is done from the app.
2. Now the box needs to be on your network before the app can reach it. There are two ways
   in — you only need one:
   - **Ethernet (simplest).** Plug the Pi into your router with a network cable. It picks up
     an address automatically and is on your network the moment it finishes booting.
   - **The box's own setup Wi-Fi.** With no cable, the box raises its **own** temporary
     network — the one named on your code sheet (e.g. `Ambrogio-9C41A7`). It's not on your
     home network yet; you'll connect your phone to it in the next step and hand over your
     home Wi-Fi from the app.

## Set up and claim it from the app

Open the **Ambrogio app** on your phone. What you do next depends on how the box got online.

### If the box is already on your network (Ethernet)

1. The app finds the box and offers to **claim** it — this makes the box yours. Type the
   **claim code** from your code sheet.
2. Give the box a **brain**: paste a Claude **subscription token** (from `claude
   setup-token`) or an **Anthropic API key**. Ambrogio needs this to think.
3. That's it — say hello in the app.

### If the box raised its own setup Wi-Fi (no cable)

The box isn't on your network yet, so the app can't discover it until you've handed it your
home Wi-Fi. The app walks you through exactly that:

1. On the app's connect screen, tap **"New box not on Wi-Fi yet? Set up its Wi-Fi"**, then
   **scan the QR on your code sheet**. That connects your phone to the box's `Ambrogio-…`
   setup network (the claim code is its password). On iPhone, tap to join that network when
   prompted — the QR fills the password for you.
2. The app shows the Wi-Fi networks the box can see. Pick **your home Wi-Fi** and enter its
   password. The box joins it and drops its setup network; your phone hops back to your home
   Wi-Fi on its own.
3. Now that the box is on your network, the app finds it and asks you to **claim** it — type
   the **claim code** from your sheet.
4. Give the box a **brain** (Claude subscription token or Anthropic API key), and say hello.

> The box needs Ethernet or Wi-Fi to reach the internet and think. The setup Wi-Fi only
> connects your *phone* to the *box* — the box still joins your home network for its own.

## Troubleshooting

- **The app says the box has no claim code.** The card was written without the script step.
  You do **not** need to re-flash: shut the box down, put its SD card back in your computer,
  run `python3 flash_box.py` on it, put it back in the Pi and power it up. The box picks up
  the new code on that boot and is claimable again (while it's still unclaimed).
- **The app doesn't find the box.** It only appears once it's on your network. On Ethernet,
  give it a couple of minutes after first boot and check your phone is on the **same
  network** as the Pi. Otherwise the box is waiting on its own setup Wi-Fi — follow the
  second path in [Set up and claim](#set-up-and-claim-it-from-the-app) (scan your sheet's
  QR) to hand it your home Wi-Fi first.
- **I've lost the claim code.** There's no on-box override — no button, no power-cycle trick —
  but which recovery you use depends on who owns the box:
  - **It's your box** (you claimed it), you just lost the printed sheet: pull the card, run
    `python3 flash_box.py --force-rekey` on it, put it back and reboot. It writes a **fresh**
    code and **keeps all your data** (a plain re-inject is refused on a claimed box, so a stray
    card can't hijack it; the `--force-rekey` marker is you saying you meant it). Print the new
    sheet.
  - **Someone else claimed it before you** and you can't get in: the only way to take it back is
    to re-flash (Option 1 or 2), which **wipes** the box, then claim it yourself. That's
    deliberate — physical possession of the card is the one thing that beats a first-claim, so
    keep your box on a network you control.
- **You want to start over.** Write the card again (Option 1 or 2).

## Verifying a download (optional)

Option 1 verifies the image's checksum for you. If you downloaded the `.img.xz` by hand
(Option 2) and want to confirm it's intact:

```
sha256sum -c ambrogio-<version>.img.xz.sha256
```

A `... OK` line means the download matches the published checksum.

## License

These images are provided under [PolyForm Noncommercial 1.0.0](LICENSE.md) — for personal,
hobby, educational, and other noncommercial use.
