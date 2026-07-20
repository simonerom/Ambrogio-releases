# Flashing Ambrogio onto a Raspberry Pi

This guide takes you from a blank SD card to a running Ambrogio box you've claimed from
the app. It should take about 15–20 minutes, most of which is the SD card writing.

## Before you start

You'll need:

- A **Raspberry Pi 4 or 5** (2 GB RAM minimum, 4 GB recommended) and its power supply.
- A **microSD card**, 16 GB or larger, and a way to connect it to your computer.
- **Raspberry Pi Imager** installed — <https://www.raspberrypi.com/software/>.
- **Python 3** on your computer, for Step 3. macOS and Linux already have it; on Windows
  install it from <https://www.python.org/downloads/> (tick "Add Python to PATH").
- The **Ambrogio app** on your iPhone, on the same Wi-Fi you'll use for the box. It is in open
  beta: **[install it via TestFlight](https://testflight.apple.com/join/kft9Hhv3)** (Apple's
  free TestFlight app handles the install; the link explains it). There is no Android build
  yet — on Android you can still reach the box's web console in a browser after setup.

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
3. When the Imager offers **OS customisation / advanced options**, you can *optionally*
   pre-fill your **Wi-Fi network name and password**. If you do, the box joins that network
   by itself on first boot — the smoothest path. If you skip it, you'll get the box online
   another way in Step 4 (an Ethernet cable, or the box's own setup Wi-Fi). Any of the three
   works; you only need one.
4. Write, and wait for the verify step to finish.
5. **Leave the card in the reader.** Step 3 needs it. (The Imager ejects the card when it
   finishes — just unplug and re-insert it.)

## Step 3 — Put a claim code on the card

**Do not skip this.** A box flashed without a claim code boots and comes up on your network
just fine — but **can never be claimed, by you or by anyone else.** See
[Why the claim code](#why-the-claim-code) below.

Download **[`flash_box.py`](tools/flash_box.py)** from this repository. Then, with the
freshly flashed card still in the reader, run it with no arguments — from wherever you
saved it:

```
python3 ~/Downloads/flash_box.py
```

It finds the card, writes a randomly generated claim code onto it, reads the code back to
confirm it landed, and prints:

```
====================================================
  Claim code:   K7PM-3XQR-VD     (type it as K7PM3XQRVD)
  Setup Wi-Fi:  Ambrogio-9C41A7
  The code is the box's claim code AND its setup Wi-Fi password.
====================================================

  Printable code sheet:  ~/ambrogio-claim-codes/ambrogio-9C41A7-claim-code.html
```

**Print the code sheet and keep it.** Open that HTML file in your browser and print it (or
Save as PDF). It holds the code, the box's Wi-Fi name, and a QR you can scan to join that
Wi-Fi. Nothing on the box can ever tell you the code later — this sheet is your only copy.
Treat it like a house key.

Then **eject the card properly** (the tool prints the exact command for your system) and
move on to Step 4.

<details>
<summary>Options, and what to do if it can't find your card</summary>

If the tool says it can't find a flashed boot partition, or that it found more than one,
name the card yourself:

```
python3 flash_box.py --boot /Volumes/bootfs        # macOS
python3 flash_box.py --boot E:\                    # Windows
python3 flash_box.py --boot /media/you/bootfs      # Linux
```

Other useful flags:

- `--out DIR` — where to save the printable code sheet (default `~/ambrogio-claim-codes`).
- `--secret CODE` — use a code you choose instead of a generated one.
- `--force` — replace a code already on the card.
- `--device /dev/diskN --image ambrogio-<version>.img.xz` — write the image **and** inject
  the code in one step, if you'd rather not use Raspberry Pi Imager. This erases the
  device and asks you to confirm first.

The tool only needs plain Python 3 — no installation, no dependencies. Installing the
optional `qrcode` package (`pip3 install "qrcode[pil]"`) adds the QR image to the sheet;
without it you still get the code, which is the part that matters.

</details>

## Step 4 — First boot, and getting the box online

1. Put the card in the Pi and connect power. The first boot takes a few minutes while the
   box sets itself up. No screen, no keyboard, and no remote login are needed — everything
   is done from the app.
2. Now the box needs to be on your network before the app can reach it. There are three ways
   in — you only need one:
   - **Ethernet (simplest).** Plug the Pi into your router with a network cable. It picks up
     an address automatically and is on your network the moment it finishes booting. (This
     works because home routers hand out addresses over the cable — no configuration needed.)
   - **Wi-Fi you pre-filled in the Imager.** If you filled in your Wi-Fi back in Step 2, the
     box joins it on this first boot. Nothing more to do here.
   - **The box's own setup Wi-Fi.** If you did neither, the box raises its **own** temporary
     network — the one named on your code sheet (e.g. `Ambrogio-9C41A7`). It's not on your
     home network yet; you'll connect your phone to this setup network in Step 5 and hand
     over your home Wi-Fi from the app.

## Step 5 — Set up and claim it from the app

Open the **Ambrogio app** on your phone. What you do next depends on how the box got online
in Step 4.

### If the box is already on your network (Ethernet, or Wi-Fi pre-filled in the Imager)

1. The app finds the box and offers to **claim** it — this makes the box yours. Type the
   **claim code** from your code sheet (Step 3).
2. Give the box a **brain**: paste a Claude **subscription token** (from `claude
   setup-token`) or an **Anthropic API key**. Ambrogio needs this to think.
3. That's it — say hello in the app.

### If the box raised its own setup Wi-Fi (no cable, no pre-filled Wi-Fi)

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

> No Wi-Fi at all and no Ethernet? The box needs one of the two to reach the internet and
> think. The setup Wi-Fi only connects your *phone* to the *box* — the box still joins your
> home Wi-Fi (or Ethernet) for its actual network.

## Why the claim code

An unclaimed box on your network has no users yet, so there is nothing to log in as. The
claim code is not a password — it is **proof that you are the person holding the box**,
which is the only thing that distinguishes you from anyone else who can reach it on your
Wi-Fi. Whoever claims the box gets your email, your Claude token, and an assistant that
acts on your behalf, so Ambrogio will not hand that to whoever asks first.

That's why the box never invents a code of its own: a code the box made up is a code you'd
have no way of knowing. The code has to come from the person who flashed the card — you.

**A box with no code refuses every claim, permanently.** It will say so in the app rather
than asking you for a code that doesn't exist.

## Troubleshooting

- **The app says the box has no claim code.** The card was flashed without Step 3. You do
  **not** need to re-flash: shut the box down, put its SD card back in your computer, run
  `python3 flash_box.py` on it, put it back in the Pi and power it up. The box picks up the
  new code on that boot and is claimable again. (This works while the box is still unclaimed.)
- **I lost the claim code, and I HAVE claimed the box.** Pull the SD card, run
  `python3 flash_box.py --force-rekey`, put it back and reboot. The box adopts the new code
  even though it is already yours, **keeping all your data** — print the sheet this time and
  keep it. (A plain re-inject is refused on a claimed box, so a card left in the reader can't
  hijack it; the `--force-rekey` marker is what tells the box you did this on purpose.)
- **The app doesn't find the box.** It only appears once it's on your network. If you used
  Ethernet or pre-filled Wi-Fi, give it a couple of minutes after first boot and check your
  phone is on the **same Wi-Fi** as the Pi. If you did neither, the box is waiting on its own
  setup Wi-Fi — follow the second path in [Step 5](#step-5--set-up-and-claim-it-from-the-app)
  (scan the QR on your code sheet) to hand it your home Wi-Fi first.
- **Someone claimed my box and I don't have the code.** There is no on-box recovery — no
  button, no power-cycle trick. If you have the code sheet, use `--force-rekey` above. If you
  don't, the only way back in is to re-flash (Step 2), which wipes the box. This is deliberate:
  the code is the only thing standing between your household data and anyone who reaches the box.
- **You want to start over.** Re-flash the SD card from Step 2 — and do Step 3 again.

## Verifying your download (optional)

If you downloaded the image by hand and want to confirm it's intact:

```
sha256sum -c ambrogio-<version>.img.xz.sha256
```

A `... OK` line means the download matches the published checksum.

## License

These images are provided under [PolyForm Noncommercial 1.0.0](LICENSE.md) — for personal,
hobby, educational, and other noncommercial use.
