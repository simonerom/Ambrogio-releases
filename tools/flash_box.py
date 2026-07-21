#!/usr/bin/env python3
"""flash_box.py — put a claim code on a flashed Ambrogio SD card (and optionally flash it too).

THIS TOOL IS NOT OPTIONAL. The appliance never invents a claim code of its own: an injected code
is the ONE proof of physical possession it accepts, so a card flashed without one produces a box
that boots, joins the network, announces itself — and refuses every claim, from you and from your
neighbours alike. Writing the code onto the /boot FAT partition (which the box adopts on its next
boot) is the step that turns a flashed card into a claimable box. It also means you know the setup
code before the box ever powers on: no journal spelunking, and it doubles as the SoftAP Wi-Fi
password.

TWO ways to use it:

  * ALL-IN-ONE (macOS/Linux) — no Raspberry Pi Imager needed. This downloads the latest image,
    lets you pick the SD card from a list, flashes it, and injects the code, in one command:

        sudo python3 flash_box.py --flash

  * INJECT-ONLY — if you flashed the card yourself (e.g. with Raspberry Pi Imager), run this with
    NO arguments to write the code into the card still in the reader:

        python3 flash_box.py

Modes:
  * --flash                 download the latest image, pick the disk, flash + inject (needs sudo)
  * (default)               inject into the just-flashed card, auto-detecting its mounted /boot
  * --boot /Volumes/bootfs  inject into a specific mounted /boot partition
  * --device /dev/diskN     flash a SPECIFIC image you name (--image) to a SPECIFIC device, then
                            inject — the manual form of --flash

The code is CSPRNG-generated HERE, on your machine, from a look-alike-free alphabet, unless you
pass --secret. Generating it off-box is the whole point: the value exists where a human can read
and keep it, instead of only inside the appliance.

WHAT YOU GET: the code on your terminal, and a printable code sheet (an HTML file you open and
print) holding the code, the box's Wi-Fi name, and the Wi-Fi QR. PRINT IT AND KEEP IT. The code is
the only thing that can claim this box, it survives a factory reset, and nothing on the box can
print it back to you once the box is out of reach.

LOST THE CODE? Put the card back in a computer and run this again. The box adopts a newly injected
code on its next boot **while it is still unclaimed** — no re-flash needed.

Once a box IS claimed it refuses to be re-keyed, and there is no recovery gesture on the box: a
claimed box whose code you do not have must be re-flashed (its data is lost unless you have a
backup). Do not go looking for a button or a power-cycle trick — there isn't one. This is the
whole reason the sheet says PRINT IT AND KEEP IT.

This tool NEVER boots the image and NEVER writes to a disk without an explicit confirmation.

Examples:
  # All-in-one: download the latest image, pick the card, flash + inject:
  sudo python3 flash_box.py --flash
  # Inject-only: flashed with Raspberry Pi Imager, card still in the reader:
  python3 flash_box.py
  # Inject a chosen code into a specific mount:
  python3 flash_box.py --secret AMBR2G3456 --boot /Volumes/bootfs
  # Flash a specific image you already downloaded, to a specific device:
  sudo python3 flash_box.py --device /dev/disk4 --image ambrogio-0.2.0.img.xz

Runs on stock Python 3 (3.9+). `qrcode` is optional: without it you lose the QR image, never the
code. This file is deliberately self-contained — no Ambrogio imports — so it can ship next to the
images in the public releases repo and run on a machine that has nothing else installed.
"""
from __future__ import annotations

# This is a SELF-CONTAINED script — it imports nothing local, on purpose, so it can ship next to the
# images and run on a bare machine. But it DOES use stdlib modules (urllib.request pulls in `email`,
# `http`, …). When run as `python3 tools/flash_box.py` from the Ambrogio source tree, Python puts
# this file's own directory on sys.path[0] — where a sibling package named like a stdlib module
# (the tree has tools/email/, an Ambrogio tool) SHADOWS it and crashes the import. Since we never
# import a local module, drop this file's own directory from sys.path before importing anything, so
# the standard library always wins. A no-op for the standalone / public copy (no siblings to shadow).
import os as _os
import sys as _sys
_self_dir = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [p for p in _sys.path if _os.path.abspath(p or ".") != _self_dir]

import argparse
import base64
import contextlib
import datetime
import hashlib
import html
import http.client
import json
import lzma
import os
import re
import secrets as pysecrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- constants that MUST stay in lockstep with the appliance ----------------------------------
# lib/setup_claim._ALPHABET / _SECRET_LEN / _MIN_DISTINCT: the box validates an injected code
# against exactly these, and stores nothing that fails. Produce anything else and the box ends up
# with NO code — booting fine, claimable by nobody. tests/test_flash_box.py asserts the lockstep.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no look-alikes: no O/I/0/1
SECRET_LEN = 10                                  # ~50 bits over a 32-symbol alphabet
MIN_DISTINCT = 4                                 # anti-degenerate gate (rejects "AAAAAAAAAA")

# The filename firstboot and the re-inject oneshot probe for, at the root of the FAT boot
# partition (deploy/firstboot/firstboot.sh; core/main._reinject_claim_secret).
SECRET_FILENAME = "ambrogio-claim-secret"

# Where the printable code sheet lands by default. OUTSIDE any repo, in the user's home, 0700 —
# it holds a live secret in plaintext (see _guard_out_dir).
DEFAULT_OUT_DIR = "~/ambrogio-claim-codes"

# --flash (the all-in-one path) reads the SAME repo-JSON rpi-imager does to learn the URL, size
# and checksum of the LATEST published image — so it always fetches the current release with no
# version hard-coded here, and verifies the download against the published .sha256 side-car.
REPO_JSON_URL = ("https://github.com/simonerom/Ambrogio-releases/releases/latest/download/"
                 "ambrogio-repo.json")
# Downloaded images are cached here so a second run (or a retry) doesn't re-fetch ~900 MB. Not a
# repo, not the sheet dir; a plain cache the user can delete.
IMAGE_CACHE_DIR = "~/.cache/ambrogio"
# A hard ceiling on what --flash will download, so a redirected/wrong URL can't fill the disk. The
# image is ~0.9 GB; 8 GB is comfortably above any real release and well below an SD card.
MAX_IMAGE_BYTES = 8 * 1024 * 1024 * 1024

# Files that make a mounted FAT volume recognisable as a Raspberry Pi boot partition. We can prove
# "this is a Pi boot partition"; we CANNOT prove "this is an Ambrogio image" (the image is pi-gen
# derived and leaves no marker of its own on /boot), so the tool says exactly that and no more.
PI_BOOT_MARKERS = ("config.txt", "cmdline.txt")


class UserError(Exception):
    """A failure the person running this can understand and fix.

    Carries the two things a good error owes its reader: WHAT went wrong (`problem`) and WHAT to
    do about it (`fix`). main() renders these — and nothing else — so a wrong flag or an unmounted
    card never lands the user in a Python traceback.
    """

    def __init__(self, problem: str, fix: str = ""):
        super().__init__(problem)
        self.problem = problem
        self.fix = fix


# --- pure helpers (unit-tested; no I/O) -------------------------------------------------------

def gen_secret() -> str:
    """A fresh claim code from the CSPRNG. Loops on the (astronomically rare) degenerate draw so
    we can never emit a code the box would reject for having <4 distinct characters."""
    while True:
        s = "".join(pysecrets.choice(ALPHABET) for _ in range(SECRET_LEN))
        if len(set(s)) >= MIN_DISTINCT:
            return s


def normalize_secret(raw: str) -> str:
    """What a human typed → canonical. Mirrors lib/setup_claim.normalize_secret exactly, so a code
    this tool accepts on the command line is a code the box accepts at claim time: uppercase, no
    spaces, no dashes (people re-type the grouped form off the sheet)."""
    return (raw or "").strip().upper().replace(" ", "").replace("-", "")


def wellformed_problem(secret: str) -> str | None:
    """Why this code is unacceptable, or None if it is fine. Returns the SPECIFIC broken rule
    rather than a generic 'invalid' — the caller quotes it, so a user who typed 11 characters is
    told about the length instead of being made to diff two alphabets by eye."""
    if len(secret) != SECRET_LEN:
        return f"it is {len(secret)} characters long, and a claim code is exactly {SECRET_LEN}"
    bad = sorted({c for c in secret if c not in ALPHABET})
    if bad:
        return (f"it contains {', '.join(repr(c) for c in bad)}, which the code alphabet excludes "
                f"(no O/I/0/1 — they are unreadable on a printed sheet). Allowed: {ALPHABET}")
    if len(set(secret)) < MIN_DISTINCT:
        return (f"it only uses {len(set(secret))} distinct characters and the box requires at "
                f"least {MIN_DISTINCT} (it rejects degenerate codes like 'AAAAAAAAAA')")
    return None


def is_wellformed(secret: str) -> bool:
    """Would the appliance accept this as an injected code? Mirrors lib/setup_claim._is_wellformed."""
    return wellformed_problem(secret) is None


def group(secret: str) -> str:
    """Human-readable grouping for print (ABCD-2G34-56). Only ever for HUMAN text — the file we
    write to /boot carries the ungrouped canonical form."""
    return "-".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def ssid_suffix(secret: str) -> str:
    """Last 6 hex of SHA-256(code), uppercased — the SSID suffix. MUST match core/wifi_qr.py, which
    is how this tool can print the box's exact Wi-Fi name before the box has ever powered on."""
    return hashlib.sha256(secret.encode()).hexdigest()[-6:].upper()


def ap_ssid_for(secret: str) -> str:
    return f"Ambrogio-{ssid_suffix(secret)}"


def wifi_qr_payload(ssid: str, secret: str) -> str:
    """The standard WIFI: string cameras and the app understand. MUST match core/wifi_qr.py."""
    def esc(v: str) -> str:
        for a, b in (("\\", "\\\\"), (";", "\\;"), (",", "\\,"), (":", "\\:"), ('"', '\\"')):
            v = v.replace(a, b)
        return v
    return f"WIFI:S:{esc(ssid)};T:WPA;P:{esc(secret)};H:false;;"


def looks_like_pi_boot(mount: Path) -> bool:
    """Does this mounted volume look like a Raspberry Pi boot partition? A positive signal, so we
    don't drop a plaintext secret onto someone's photo card because it happened to be FAT."""
    try:
        return any((mount / m).exists() for m in PI_BOOT_MARKERS)
    except OSError:
        return False


def select_boot_partition(candidates: list[Path]) -> Path:
    """Pick THE card to inject into, or refuse with an actionable error. Pure — takes the already
    enumerated mounts so it can be tested without an SD card.

    Refuses on zero (nothing to inject into) and on more than one (we will not guess which card
    is yours when guessing wrong means writing a live secret onto the wrong volume, and leaving
    the box you meant to set up unclaimable).
    """
    if not candidates:
        raise UserError(
            "no flashed Raspberry Pi boot partition is mounted on this computer",
            "Flash the image with Raspberry Pi Imager first and leave the card in the reader — "
            "the boot partition mounts by itself (macOS: /Volumes/bootfs, Windows: a new drive "
            "letter like E:, Linux: /media/<you>/bootfs). If the card IS in the reader, unplug "
            "and re-insert it, then run this again. Already know where it is? Name it: "
            "--boot /Volumes/bootfs  (Windows: --boot E:\\)")
    if len(candidates) > 1:
        listed = "\n    ".join(str(c) for c in candidates)
        raise UserError(
            f"{len(candidates)} boot partitions are mounted and I will not guess which one is "
            f"your Ambrogio card:\n    {listed}",
            "Eject the cards you are not setting up, or name the one you want:\n"
            f"    python3 {_prog()} --boot {candidates[0]}")
    return candidates[0]


def _prog() -> str:
    """This script as the user invoked it — so the fix lines we print are commands they can paste."""
    return os.path.basename(sys.argv[0]) or "flash_box.py"


# --- finding the card ------------------------------------------------------------------------

def enumerate_boot_candidates() -> list[Path]:
    """Every mounted FAT volume on a REMOVABLE/EXTERNAL disk that looks like a Pi boot partition.

    Removable-only is deliberate: it keeps an internal EFI system partition (also FAT, also
    carrying config-ish files on some machines) out of the running entirely.
    """
    mounts: list[Path] = []
    if sys.platform == "win32":
        return _windows_boot_candidates()
    if sys.platform == "darwin":
        import plistlib
        try:
            out = subprocess.run(["diskutil", "list", "-plist", "external", "physical"],
                                 capture_output=True, text=True, timeout=15).stdout
            info = plistlib.loads(out.encode())
        except Exception:  # noqa: BLE001 — diskutil missing/odd output → nothing detectable
            return []
        for disk in info.get("AllDisksAndPartitions", []):
            for part in disk.get("Partitions", []):
                mp = part.get("MountPoint")
                name = (part.get("VolumeName") or "").lower()
                content = (part.get("Content") or "").lower()
                if mp and ("fat" in content or name in ("bootfs", "boot")):
                    mounts.append(Path(mp))
    else:
        try:
            out = subprocess.run(["lsblk", "-nro", "NAME,FSTYPE,MOUNTPOINT,RM"],
                                 capture_output=True, text=True, timeout=15).stdout
        except Exception:  # noqa: BLE001 — no lsblk → nothing detectable
            return []
        for ln in out.splitlines():
            p = ln.split()
            if len(p) == 4 and p[1].lower() == "vfat" and p[2].startswith("/") and p[3] == "1":
                mounts.append(Path(p[2]))
    # Only volumes that actually look like a Pi boot partition. If NONE do, we return the empty
    # list rather than falling back to "any FAT volume": the old fallback would happily write a
    # live claim secret onto an unrelated USB stick.
    return [m for m in mounts if looks_like_pi_boot(m)]


def _windows_boot_candidates() -> list[Path]:
    """Windows has no lsblk and no diskutil, so walk the drive letters instead. Raspberry Pi
    Imager on Windows leaves the boot partition mounted as its own drive letter (often E:\\), so
    probing each root for the Pi markers is both the simplest and the most reliable check.

    Removability is a best-effort EXTRA filter: if ctypes can't answer (locked-down Python, an odd
    runtime), the Pi markers alone are signal enough — and a wrong guess still can't get past
    check_boot_dir(). Anything unexpected here degrades to "nothing found", which is a clear error
    naming --boot, not a crash.
    """
    import string

    is_removable = None
    try:
        import ctypes

        k32 = ctypes.windll.kernel32                      # type: ignore[attr-defined]

        def is_removable(root: Path) -> bool:             # noqa: F811 — deliberate late binding
            return k32.GetDriveTypeW(str(root)) == 2      # DRIVE_REMOVABLE
    except Exception:  # noqa: BLE001
        is_removable = None

    found: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if not root.exists() or not looks_like_pi_boot(root):
                continue
            if is_removable is not None and not is_removable(root):
                continue
        except OSError:
            continue                                      # empty card reader / disconnected share
        found.append(root)
    return found


def check_boot_dir(boot_dir: Path, *, force: bool) -> None:
    """Everything that can be wrong with the chosen mount, checked BEFORE we touch it — each with
    the sentence that unsticks the user. Ordered cheapest/most-likely first."""
    if not boot_dir.exists():
        raise UserError(
            f"{boot_dir} does not exist",
            "Check the path. On macOS a flashed card mounts as /Volumes/bootfs; on Linux look "
            "under /media/<you>/ or /mnt. `ls /Volumes` (macOS) or `lsblk` (Linux) lists them.")
    if not boot_dir.is_dir():
        raise UserError(
            f"{boot_dir} is not a directory",
            "Pass the MOUNT POINT of the boot partition (the folder you can open in Finder), not "
            "a file or a device node.")
    if not looks_like_pi_boot(boot_dir):
        if not force:
            raise UserError(
                f"{boot_dir} does not look like a Raspberry Pi boot partition "
                f"(none of {', '.join(PI_BOOT_MARKERS)} are there)",
                "That is almost certainly the wrong volume — injecting here would write a live "
                "claim code onto an unrelated disk and leave your box unclaimable. Double-check "
                "which volume is the flashed card. If you are certain this is right, re-run with "
                "--force.")
        print(f"  WARNING: {boot_dir} has no Pi boot markers — proceeding because --force was given")
    # Writability: probe rather than trust os.access(), which lies on read-only mounts and about
    # ACLs. A read-only FAT mount (macOS does this when a card was pulled without ejecting, or
    # when the filesystem is dirty) is the single most common non-obvious failure here.
    probe = boot_dir / ".ambrogio-write-test"
    try:
        try:
            with open(probe, "wb") as fh:
                fh.write(b"ok")
        finally:
            # Clean up even if the write half-succeeded — a stray dotfile on the boot partition
            # of an appliance image is litter we put there.
            try:
                os.unlink(probe)
            except OSError:
                pass
    except OSError as e:
        raise UserError(
            f"cannot write to {boot_dir} ({e.strerror or e})",
            _write_failure_fix(e, boot_dir)) from None


def _write_failure_fix(e: OSError, boot_dir: Path) -> str:
    """Turn errno into the specific remedy. A generic 'check permissions' would be useless here:
    the three causes need three different actions."""
    import errno
    if e.errno == errno.EROFS:
        return (f"The volume is mounted READ-ONLY. Eject it and re-insert the card. On macOS a "
                f"dirty FAT filesystem remounts read-only — if it keeps happening, re-flash the "
                f"card. On Linux remount it writable: sudo mount -o remount,rw {boot_dir}")
    if e.errno in (errno.EACCES, errno.EPERM):
        return (f"You do not have permission to write there. On Linux the card is often mounted "
                f"root-owned — re-run with sudo: sudo python3 {_prog()} --boot {boot_dir}")
    if e.errno == errno.ENOSPC:
        return ("The boot partition is full. That is odd for a freshly flashed card — re-flash it "
                "and try again.")
    return ("Check that the card is still inserted and the volume is still mounted, then run this "
            "again.")


# --- the injection ---------------------------------------------------------------------------

def read_existing_secret(boot_dir: Path) -> str | None:
    """The code already sitting on this card, if any — so a second run can tell the user what it
    is about to replace instead of silently overwriting a code they have already printed."""
    try:
        raw = (boot_dir / SECRET_FILENAME).read_text(errors="replace")
    except (OSError, UnicodeError):
        return None
    lines = raw.splitlines()
    # An empty leftover file is not a code anyone can have printed, so treat it as "nothing
    # there" and overwrite it without ceremony.
    return (normalize_secret(lines[0]) or None) if lines else None


def inject_secret(boot_dir: Path, secret: str, force_rekey: bool = False) -> Path:
    """Write the code onto the card, flush it to the physical medium, and PROVE it landed.

    Three things this does that a bare write_text() does not, each earning its lines:

    * Atomic replace via a temp file — an interrupted run leaves either the old code or the new
      one, never a half-written line the box would reject as malformed (which would silently
      leave the box with no code at all).
    * fsync of the file AND the directory — the user's next move is to yank the card. Data still
      sitting in the OS page cache is data that never reaches the box. This is THE interrupted
      write that actually happens in practice.
    * Read-back verification against the exact bytes we meant to store — the caller only tells
      the user "this is your code" after the card has read it back to us.

    force_rekey adds a second line, `force-rekey`, which tells the box to adopt this code even if
    it is ALREADY CLAIMED — the escape hatch for an owner who lost the code of a box they own. A
    bare preset (no marker) is refused on a claimed box, so a card forgotten in the slot can't
    silently change an owned box's identity.
    """
    target = boot_dir / SECRET_FILENAME
    tmp = boot_dir / (SECRET_FILENAME + ".tmp")
    payload = secret + "\n" + ("force-rekey\n" if force_rekey else "")
    data = payload.encode("ascii")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)          # bytes → the card, not just the page cache
        finally:
            os.close(fd)
        os.replace(tmp, target)   # atomic within the filesystem
        try:
            os.chmod(target, 0o600)   # FAT ignores mode; harmless where it doesn't
        except OSError:
            pass
        _fsync_dir(boot_dir)      # the RENAME → the card too
    except OSError as e:
        try:
            os.unlink(tmp)        # don't leave a stray .tmp on the boot partition
        except OSError:
            pass
        raise UserError(f"failed to write the claim code to {target} ({e.strerror or e})",
                        _write_failure_fix(e, boot_dir)) from None

    verify_written_secret(target, secret)
    return target


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync. FAT on macOS may not support it; that is not a failure worth
    stopping for, because the file fsync above already did the load-bearing work."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def verify_written_secret(target: Path, expected: str) -> None:
    """Read the file back off the card and compare. A mismatch here is the difference between
    'your box is ready' and 'your box will never accept the code on your sheet', so it is a hard
    failure — dying cards, silently read-only unions and truncated FAT writes all surface here."""
    try:
        raw = target.read_bytes()
    except OSError as e:
        raise UserError(
            f"wrote {target} but could not read it back ({e.strerror or e}) — the code is NOT "
            f"confirmed on the card",
            "Eject and re-insert the card, then run this again. If it repeats, the card is "
            "failing — use another one.") from None
    got = normalize_secret(raw.decode("ascii", "replace").splitlines()[0]
                           if raw.splitlines() else "")
    if got != expected:
        raise UserError(
            f"verification FAILED: {target} reads back as a different value than was written",
            "Nothing on that card can be trusted right now — the box would end up with a code "
            "you do not have. Eject and re-insert the card and run this again; if it repeats, "
            "re-flash the card or use another one.")


# --- the printable code sheet -----------------------------------------------------------------

def _qr_png_data_uri(payload: str) -> str | None:
    """The Wi-Fi QR as a self-contained data: URI, or None if we cannot make one. Never raises:
    the QR is a convenience, the CODE is the load-bearing part of the sheet, and a missing PIL
    must not cost the user their only printable copy."""
    try:
        import io

        import qrcode
        img = qrcode.make(payload)          # PIL image (qrcode[pil])
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — no qrcode, no PIL, an odd backend: all the same to us
        return None


def _invoking_user() -> "tuple[int, int] | None":
    """When we're root via an elevation tool, WHO really invoked us — (uid, gid) — or None if we're
    genuinely root / can't tell. This is the linchpin of the security model: the code sheet and the
    image cache live in the real user's home, and we DROP to this user (via _as_real_user) to touch
    those paths, so a symlink the user planted in their own home can only ever hit their OWN files —
    never trick root into chmod/chown-ing /root/.ssh or /etc/sudoers.d.

    Source, most explicit first: SUDO_UID/SUDO_GID (sudo), then the owner of the controlling terminal
    (doas / run0 / `su` don't set SUDO_*, but the tty stays owned by the login user). Returns None
    when not root, when the resolved user IS root, or on a platform without os.geteuid (Windows)."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    su, sg = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if su and su.isdigit() and sg and sg.isdigit():
        uid, gid = int(su), int(sg)
        return (uid, gid) if uid != 0 else None
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            st = os.stat(os.ttyname(stream.fileno()))
        except (OSError, ValueError, AttributeError):
            continue
        return (st.st_uid, st.st_gid) if st.st_uid != 0 else None
    return None


def _invoking_home() -> Path:
    """The real (non-root) invoker's home — where the sheet + cache belong — even under sudo/doas,
    where ~ resolves to root's home. Falls back to ~ when there's no distinct invoker."""
    ids = _invoking_user()
    if ids:
        try:
            import pwd
            return Path(pwd.getpwuid(ids[0]).pw_dir)
        except (KeyError, ImportError):
            pass
    return Path("~").expanduser()


@contextlib.contextmanager
def _as_real_user():
    """Run a block with euid/egid dropped to the real invoker, so anything we CREATE under their home
    (cache dir, downloaded image, sheet dir + file) is made with THEIR privileges — a planted symlink
    then resolves against what they can already reach, closing the root chmod/chown-follows-symlink
    escalation. No-op when there's no distinct invoker or the platform lacks seteuid. ruid stays 0
    under sudo, so seteuid(0) restores afterwards."""
    ids = _invoking_user()
    if not ids or not hasattr(os, "seteuid"):
        yield
        return
    uid, gid = ids
    os.setegid(gid)
    os.seteuid(uid)                     # euid last: after this we can no longer setegid
    try:
        yield
    finally:
        os.seteuid(0)                   # euid first: regain privilege before restoring egid
        os.setegid(0)


def _default_sheet_dir() -> Path:
    """The --out default. Normally ~/ambrogio-claim-codes (expanded later); under an elevation tool
    the REAL user's home — not root's — so the sheet lands where the person can find and read it."""
    return (_invoking_home() / "ambrogio-claim-codes") if _invoking_user() else Path(DEFAULT_OUT_DIR)


def _guard_out_dir(out_dir: Path) -> None:
    """Refuse to write a live secret inside a git working tree.

    The sheet is plaintext credentials. Dropped into a checkout, one `git add -A` publishes the
    key to somebody's house. Walk up looking for a .git; if we find one, stop and say why.
    """
    p = out_dir.expanduser().resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            # The remedy must not name a path that is ALSO inside that repo — which is exactly
            # what happens when $HOME is itself a checkout (a dotfiles repo is common), because
            # the default lives under $HOME. Suggesting the path that just failed leaves the user
            # with no way forward at all.
            default_is_trapped = str(Path(DEFAULT_OUT_DIR).expanduser().resolve()).startswith(
                str(d) + os.sep)
            remedy = (
                f"Pass a directory outside any repository, e.g. --out /tmp/ambrogio-claim-codes"
                if default_is_trapped else
                f"Pass a directory outside any repository, e.g. --out {DEFAULT_OUT_DIR}")
            raise UserError(
                f"{p} is inside the git repository at {d} — refusing to write a live claim code "
                f"there, where `git add` could commit it",
                remedy)


def write_code_sheet(out_dir: Path, ssid: str, secret: str, payload: str) -> Path:
    """Write the printable code sheet: one self-contained HTML file, 0600, outside the repo.

    HTML and not PDF on purpose — every machine has a browser (File → Print → Save as PDF), and
    it costs zero dependencies. The QR is inlined as a data: URI so the file is one artifact you
    can move, keep, or mail to yourself with nothing else attached.
    """
    _guard_out_dir(out_dir)
    out_dir = out_dir.expanduser()
    path = out_dir / f"ambrogio-{ssid_suffix(secret)}-claim-code.html"
    doc = _render_sheet(ssid, secret, payload)
    # Create + write DROPPED to the real user (under sudo/doas): the sheet is then owned by the human
    # who needs to read it, and a symlink they may have planted here can only reach their own files —
    # never let root write this live secret through a link into a place they couldn't otherwise.
    try:
        with _as_real_user():
            out_dir.mkdir(parents=True, exist_ok=True)
            # Accumulates live secrets → keep other local users out. On Windows chmod only toggles
            # the read-only bit; the per-user home directory is the protection there.
            os.chmod(out_dir, 0o700)
            # 0600 from the instant it exists — never a world-readable window on a shared machine.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(doc)
            os.chmod(path, 0o600)        # in case the file pre-existed with a laxer mode
    except OSError as e:
        raise UserError(f"cannot write {path} ({e.strerror or e})",
                        f"Pass a writable directory with --out, e.g. --out {DEFAULT_OUT_DIR}") from None
    return path


def _render_sheet(ssid: str, secret: str, payload: str) -> str:
    """The sheet itself. Print-first CSS: black on white, no backgrounds to drink your toner, and
    a page that fits on one A4/Letter sheet."""
    qr = _qr_png_data_uri(payload)
    date = datetime.date.today().isoformat()
    e = html.escape
    qr_block = (
        f'<img class="qr" src="{qr}" alt="Wi-Fi QR for {e(ssid)}">'
        # Say BOTH jobs this QR does. It encodes the code as a Wi-Fi password, so scanning it in
        # the app fills the claim code in — which is the ONLY thing it does when the box reached
        # the network by Ethernet or by Wi-Fi pre-filled in Raspberry Pi Imager. In that case the
        # setup hotspot is never raised and the network named here will not exist; a caption that
        # mentions only Wi-Fi sends those users off hunting for it, or has them type the code by
        # hand for no reason.
        '<p class="cap">Scan in the Ambrogio app to fill in the claim code.<br>'
        'It also joins the box\'s setup Wi-Fi — if the box raised one (it doesn\'t need to '
        'when it is on Ethernet, or when you pre-filled Wi-Fi while flashing).</p>'
        if qr else
        '<p class="cap nq">(QR unavailable — install the <code>qrcode</code> Python package to '
        'get one. Join the network by hand: pick the network name above and type the code as '
        'its password.)</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Ambrogio claim code — {e(ssid)}</title>
<style>
  @page {{ margin: 18mm; }}
  html, body {{ background: #fff; color: #000; }}
  body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; line-height: 1.5;
          max-width: 46em; margin: 3em auto; padding: 0 1.5em; }}
  h1 {{ font-size: 1.3rem; letter-spacing: .02em; margin: 0 0 .2em; }}
  .sub {{ color: #444; margin: 0 0 2em; font-size: .95rem; }}
  .box {{ border: 2px solid #000; border-radius: 6px; padding: 1.4em 1.6em; margin: 0 0 1.6em; }}
  .lbl {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; color: #555;
          margin: 0 0 .35em; }}
  .code {{ font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 2.6rem;
           font-weight: 700; letter-spacing: .12em; margin: 0; word-break: break-all; }}
  .plain {{ font-family: "SF Mono", Menlo, Consolas, monospace; color: #555; font-size: .9rem;
            margin: .5em 0 0; }}
  .ssid {{ font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 1.3rem; margin: 0; }}
  .qr {{ width: 46mm; height: 46mm; image-rendering: pixelated; display: block; }}
  .cap {{ font-size: .8rem; color: #555; margin: .5em 0 0; }}
  .nq {{ max-width: 30em; }}
  .note {{ border-top: 1px solid #bbb; padding-top: 1em; font-size: .88rem; color: #333; }}
  .note strong {{ color: #000; }}
  .foot {{ color: #777; font-size: .78rem; margin-top: 2em; }}
  .row {{ display: flex; gap: 2em; align-items: flex-start; flex-wrap: wrap; }}
</style></head><body>

<h1>Ambrogio — claim code</h1>
<p class="sub">Keep this sheet. It is what proves the box is yours.</p>

<div class="box">
  <p class="lbl">Claim code</p>
  <p class="code">{e(group(secret))}</p>
  <p class="plain">type it without the dashes: {e(secret)}</p>
</div>

<div class="box row">
  <div>
    <p class="lbl">Setup Wi-Fi network</p>
    <p class="ssid">{e(ssid)}</p>
    <p class="cap">Password = the claim code above</p>
  </div>
  <div>{qr_block}</div>
</div>

<p class="note">
  <strong>What this is.</strong> The claim code is how your Ambrogio box knows that you are the
  person holding it. You will type it once, in the app, to claim the box. It is also the password
  of the box's own setup Wi-Fi network, shown above.
  <br><br>
  <strong>If you lose it</strong> there is no way to recover it from the box — nothing on the box
  will print it back to you. You would have to put the SD card back in a computer and inject a new
  code (which only works while the box is still unclaimed), or start over from a re-flash.
  Photograph this sheet or keep it somewhere safe.
</p>

<p class="foot">Injected {e(date)} · this sheet is the only copy · treat it like a house key</p>
</body></html>
"""


# --- terminal QR ------------------------------------------------------------------------------

def print_qr_ascii(payload: str) -> None:
    """The Wi-Fi QR as terminal ASCII — scannable straight off the screen, so a user who cannot
    print right now can still join the box's setup network."""
    try:
        import qrcode
    except ImportError:
        print("  (no QR here: pip3 install 'qrcode[pil]' — the code above is all you strictly need)")
        return
    try:
        qr = qrcode.QRCode(border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        qr.print_ascii(tty=False)
    except Exception:  # noqa: BLE001 — a cosmetic QR must never take the run down
        print("  (couldn't render the QR here — the code above is all you strictly need)")


# --- optional: flashing the image (--device) ---------------------------------------------------

def die(msg: str) -> None:
    raise UserError(msg)


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        raise UserError(
            "this step needs an interactive confirmation, but stdin is not a terminal",
            "Run the command directly in a terminal (not through a pipe or a CI job).")
    try:
        return input(f"{prompt} [type 'yes' to proceed]: ").strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def _whole_disk_id(device: str) -> str:
    """Normalize a device node to its WHOLE-disk id for safety checks, stripping any partition/
    slice suffix. /dev/rdisk4s1 → disk4, /dev/nvme0n1p2 → nvme0n1, /dev/mmcblk0p1 → mmcblk0,
    /dev/sdb3 → sdb. Handles the macOS r-prefix (raw device)."""
    base = device.rsplit("/", 1)[-1]
    if base.startswith("r"):           # macOS raw device: rdisk4 → disk4
        base = base[1:]
    m = re.match(r"^(disk\d+)(s\d+)?$", base)                      # macOS diskNsM → diskN
    if m:
        return m.group(1)
    m = re.match(r"^(nvme\d+n\d+|mmcblk\d+)(p\d+)?$", base)        # nvme0n1p2 / mmcblk0p1
    if m:
        return m.group(1)
    m = re.match(r"^(sd[a-z]+)(\d+)?$", base)                      # sdb3 → sdb
    if m:
        return m.group(1)
    return base


def _is_removable_target(device: str) -> bool:
    """Positive safety check: is this device an EXTERNAL/REMOVABLE disk (an SD card / USB reader),
    NOT the machine's internal boot disk? A blocklist of guessed names can't enumerate every
    system-disk spelling (/dev/rdisk0, /dev/nvme0n1, /dev/mmcblk0 …); asking the OS 'is this
    removable' is the property that actually matters. Fails CLOSED (returns False) if we can't
    tell."""
    whole = _whole_disk_id(device)
    if sys.platform == "darwin":
        import plistlib
        try:
            out = subprocess.run(["diskutil", "info", "-plist", whole],
                                 capture_output=True, text=True, timeout=15).stdout
            info = plistlib.loads(out.encode())
        except Exception:  # noqa: BLE001
            return False
        if info.get("Internal") is True:
            return False
        return bool(info.get("Removable") or info.get("RemovableMedia")
                    or info.get("Ejectable") or info.get("External"))
    else:
        try:
            out = subprocess.run(["lsblk", "-no", "RM,MOUNTPOINT", f"/dev/{whole}"],
                                 capture_output=True, text=True, timeout=15).stdout
        except Exception:  # noqa: BLE001
            return False
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if not lines:
            return False
        removable = lines[0].split()[0] == "1"
        mounted_system = any(ln.split()[-1:] == ["/"] for ln in lines)
        return removable and not mounted_system


def _unmount_disk(device: str) -> None:
    """Unmount (NOT eject) the target disk's partitions so dd can open it — a mounted volume makes
    dd fail with 'Resource busy'. Unmount keeps /dev/diskN present; eject would remove it."""
    whole = _whole_disk_id(device)
    if sys.platform == "darwin":
        r = subprocess.run(["diskutil", "unmountDisk", f"/dev/{whole}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  unmounted /dev/{whole}")
        else:
            msg = (r.stderr or r.stdout).strip()
            if "unmount" not in msg.lower() or "busy" in msg.lower():
                print(f"  (unmount note: {msg})")
    else:
        try:
            out = subprocess.run(["lsblk", "-nro", "NAME,MOUNTPOINT", f"/dev/{whole}"],
                                 capture_output=True, text=True, timeout=15).stdout
            for ln in out.splitlines():
                parts = ln.split()
                if len(parts) == 2 and parts[1]:
                    subprocess.run(["umount", parts[1]], capture_output=True, text=True)
                    print(f"  unmounted {parts[1]}")
        except Exception:  # noqa: BLE001
            pass


def _uncompressed_size(image: Path) -> int | None:
    """Decompressed byte size of the image, for pv's progress bar. For .xz read the 'totals' line
    of `xz --robot --list` (field 5 = uncompressed size — the per-file column layout isn't stable
    across xz versions, so always read totals)."""
    if image.suffix != ".xz":
        try:
            return image.stat().st_size
        except OSError:
            return None
    try:
        out = subprocess.run(["xz", "--robot", "--list", str(image)],
                             capture_output=True, text=True, timeout=30).stdout
        for ln in out.splitlines():
            if ln.startswith("totals"):
                return int(ln.split()[4])
    except Exception:  # noqa: BLE001
        pass
    return None


def _run_dd_with_progress(dd: "subprocess.Popen") -> None:
    """Drive a running dd to completion while printing periodic progress — used when pv is absent.
    BSD dd (macOS) prints a stats line to stderr on SIGINFO; GNU dd (Linux) on SIGUSR1."""
    sig = signal.SIGINFO if hasattr(signal, "SIGINFO") else signal.SIGUSR1
    try:
        while dd.poll() is None:
            time.sleep(3)
            try:
                dd.send_signal(sig)
            except ProcessLookupError:
                break
    finally:
        dd.wait()


# --- the all-in-one path: fetch the image, pick the card (--flash) --------------------------------

def _http_get(url: str, timeout: int = 60):
    """Open an HTTPS URL with cert validation (urllib's default) and a real User-Agent — GitHub's
    asset CDN 403s an empty UA. Cross-host redirects (github.com → the signed CDN) are followed by
    urllib automatically. Raises UserError with an actionable message on any network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "flash_box.py"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — https, our own repo
    except (urllib.error.URLError, OSError) as e:
        raise UserError(f"couldn't reach {url} ({e})",
                        "Check your internet connection and try again. If it persists, download the "
                        ".img.xz from the releases page by hand and flash it with Raspberry Pi Imager.")


def _latest_image_meta() -> dict:
    """Read the published repo-JSON and return the latest image's {name,url,size,sha256_url}. `url`
    is the image; the download checksum is the published `<image>.sha256` side-car (repo.json's own
    extract_sha256 is the DECOMPRESSED image's hash, verified by rpi-imager post-write, not ours)."""
    with _http_get(REPO_JSON_URL) as r:
        raw = r.read(1_000_000)  # a metadata file; cap the read so a wrong URL can't stream forever
    try:
        entry = json.loads(raw)["os_list"][0]
        url = entry["url"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise UserError("the release index (repo.json) was not in the expected shape",
                        "Flash with Raspberry Pi Imager instead (download the .img.xz from the "
                        "releases page), then run this tool with no --flash to inject the code.")
    # Defence in depth: we then fetch this URL AS ROOT. It comes from our own HTTPS release index,
    # but pin the scheme so a mangled index can't turn the download into a file:// read or an
    # http:// (downgradeable) or internal-host fetch.
    if not isinstance(url, str) or not url.startswith("https://"):
        raise UserError("the release index points the image at a non-HTTPS URL — refusing",
                        "Download the .img.xz from the releases page by hand and flash it with "
                        "Raspberry Pi Imager.")
    return {"name": url.rsplit("/", 1)[-1], "url": url,
            "size": entry.get("image_download_size"), "sha256_url": url + ".sha256"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(sha_url: str) -> str | None:
    """Fetch and parse a coreutils-style `<hex>  <name>` side-car. None if it can't be had — the
    caller decides whether a missing checksum is fatal (for --flash it is: no silent unverified write)."""
    try:
        with _http_get(sha_url, timeout=30) as r:
            first = r.read(200).decode("utf-8", "replace").split()
    except UserError:
        return None
    return first[0].lower() if first and re.fullmatch(r"[0-9a-fA-F]{64}", first[0]) else None


def _download_with_progress(url: str, dest: Path, total: int | None) -> None:
    """Stream `url` to `dest` (a .part file, renamed on success) with a one-line progress readout,
    capped at MAX_IMAGE_BYTES so a redirect to the wrong thing can't fill the disk. A connection that
    drops or stalls mid-stream (the common failure on flaky Wi-Fi) is a NETWORK error, not a tool
    bug — catch it here and say so, rather than let it reach the last-resort 'please report a bug'."""
    part = dest.with_suffix(dest.suffix + ".part")
    got = 0
    last = 0.0
    try:
        with _http_get(url) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_IMAGE_BYTES:
                    f.close()
                    part.unlink(missing_ok=True)
                    raise UserError(f"the download exceeded {MAX_IMAGE_BYTES // (1024**3)} GB and "
                                    "was stopped", "That is not the Ambrogio image — check the "
                                    "release, or flash with Raspberry Pi Imager instead.")
                f.write(chunk)
                now = time.monotonic()
                if now - last >= 0.5:                       # throttle the redraw
                    last = now
                    mb = got / (1024 * 1024)
                    if total:
                        pct = got * 100 // total
                        sys.stdout.write(f"\r  downloading… {pct:3d}%  ({mb:,.0f} MB)")
                    else:
                        sys.stdout.write(f"\r  downloading… {mb:,.0f} MB")
                    sys.stdout.flush()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        # IncompleteRead is an HTTPException (not OSError); a reset/stall is an OSError. Either way
        # the body stopped early — leave the .part (the next run re-downloads over it) and explain.
        sys.stdout.write("\n")
        raise UserError(f"the download stopped early ({type(e).__name__})",
                        "That's usually a flaky connection — run the same command again to download "
                        "it fresh. Or download the .img.xz from the releases page and flash it with "
                        "Raspberry Pi Imager.") from None
    sys.stdout.write("\r  download complete." + " " * 24 + "\n")
    part.replace(dest)


def fetch_latest_image() -> Path:
    """Download the latest published image (or reuse a cached, checksum-matching copy) and return
    its local path. Always verifies against the published .sha256 — a mismatch deletes the file and
    aborts, because the very next step writes it to a disk. Cache dir is created 0700 (it is only a
    cache, but keep it tidy and private)."""
    meta = _latest_image_meta()
    want = _expected_sha256(meta["sha256_url"])
    if want is None:
        raise UserError(f"couldn't fetch the checksum for {meta['name']}",
                        "Refusing to flash an unverified image. Try again, or download the .img.xz "
                        "and its .sha256 from the releases page and verify by hand.")

    # Resolve the cache path while STILL ROOT: _invoking_home() keys off euid, which _as_real_user
    # is about to change — computing it inside the drop would see the dropped euid, decide there's no
    # invoker, and fall back to ~ = root's home under `sudo -H` (exactly the bug this avoids).
    cache = _invoking_home() / ".cache" / "ambrogio"
    dest = cache / meta["name"]

    # Then create + download DROPPED to the real user (under sudo/doas): the cache lives in THEIR
    # ~/.cache (readable by them, not root-only), and a symlink they planted there can only ever
    # reach their own files — root never writes/chmods a linked-to target. dd later runs back at
    # root; root can still read this user-owned image.
    with _as_real_user():
        try:
            cache.mkdir(parents=True, exist_ok=True)
            os.chmod(cache, 0o700)
        except OSError as e:
            raise UserError(f"cannot prepare the download cache {cache} ({e.strerror or e})",
                            "Check that your home directory is writable, or download the .img.xz "
                            "from the releases page and flash it with Raspberry Pi Imager.") from None

        if dest.is_file() and _sha256_file(dest) == want:
            print(f"  using the cached image {dest} (checksum verified)")
            return dest

        print(f"  fetching {meta['name']} (~{(meta['size'] or 0) // (1024*1024):,} MB) to {cache}")
        _download_with_progress(meta["url"], dest, meta.get("size"))
        print("  verifying checksum…")
        if _sha256_file(dest) != want:
            dest.unlink(missing_ok=True)
            raise UserError("the downloaded image failed its checksum — it is corrupt or was "
                            "tampered with, and has been deleted",
                            "Run the same command again to download it fresh.")
        print("  checksum OK.")
        return dest


def _removable_disks() -> list[dict]:
    """List EXTERNAL/removable whole disks the OS reports — candidates for the SD card. Each entry is
    {dev,size,label}. macOS via diskutil, Linux via lsblk; Windows returns [] (dd-style flashing is
    Unix-only). Every entry is still re-checked with _is_removable_target before any write."""
    disks: list[dict] = []
    if sys.platform == "darwin":
        import plistlib
        try:
            out = subprocess.run(["diskutil", "list", "-plist", "external", "physical"],
                                 capture_output=True, timeout=20).stdout
            plist = plistlib.loads(out)
        except Exception:  # noqa: BLE001
            return []
        for d in plist.get("AllDisksAndPartitions", []):
            ident = d.get("DeviceIdentifier")
            if not ident:
                continue
            size = d.get("Size")
            label = d.get("VolumeName") or ""
            if not label:
                parts = d.get("Partitions") or []
                label = next((p.get("VolumeName") for p in parts if p.get("VolumeName")), "")
            disks.append({"dev": f"/dev/{ident}", "size": _human_size(size), "label": label})
    elif sys.platform.startswith("linux"):
        try:
            out = subprocess.run(["lsblk", "-dpno", "NAME,SIZE,RM,TYPE,MODEL"],
                                 capture_output=True, text=True, timeout=20).stdout
        except Exception:  # noqa: BLE001
            return []
        for ln in out.splitlines():
            f = ln.split(None, 4)
            if len(f) >= 4 and f[2] == "1" and f[3] == "disk":
                disks.append({"dev": f[0], "size": f[1], "label": f[4] if len(f) > 4 else ""})
    return disks


def _human_size(n: "int | None") -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def pick_target_device() -> str:
    """Show the removable disks and let the user choose one, by number. Never guesses: zero disks is
    an actionable error, and the choice is confirmed again (by name + size) at write_image."""
    if sys.platform not in ("darwin",) and not sys.platform.startswith("linux"):
        raise UserError("flashing from this tool is only supported on macOS and Linux",
                        "On Windows, flash the image with Raspberry Pi Imager (Choose OS → Use "
                        "custom → the downloaded .img.xz), then run this tool with no --flash to "
                        "inject the code.")
    disks = _removable_disks()
    if not disks:
        raise UserError("no external/removable disk found",
                        "Insert the SD card and run this again. Note: a card in a laptop's BUILT-IN "
                        "SD slot often reports as non-removable and won't appear here (nor will this "
                        "tool write to it) — use a USB SD reader, or flash with Raspberry Pi Imager "
                        "instead.")
    if not sys.stdin.isatty():
        raise UserError("cannot pick a disk without a terminal to ask in",
                        "Run this in an interactive terminal, or name the device explicitly: "
                        f"sudo python3 {_prog()} --device /dev/diskN --image <file>.")
    print("\n  Removable disks found — pick the SD card. EVERYTHING on it will be erased:\n")
    for i, d in enumerate(disks, 1):
        label = f"  “{d['label']}”" if d["label"] else ""
        print(f"    [{i}]  {d['dev']}   {d['size']}{label}")
    print()
    while True:
        try:
            raw = input(f"  Which disk? [1-{len(disks)}, or q to quit]  ").strip().lower()
        except EOFError:
            raise UserError("no selection made", "Run it again and pick the SD card's number.")
        if raw in ("q", "quit", ""):
            raise UserError("no disk selected — nothing was written",
                            "Re-run when you're ready and pick the SD card's number.")
        if raw.isdigit() and 1 <= int(raw) <= len(disks):
            return disks[int(raw) - 1]["dev"]
        print(f"  Enter a number from 1 to {len(disks)} (or q to quit).")


def _require_root_for_flash() -> None:
    """Writing a raw disk needs root. Ask for it UP FRONT — before the download and the disk menu —
    so the flow doesn't get all the way to dd and only then die on a permission error. Under sudo
    the whole run is root; the home-touching bits drop back to the real user (see _as_real_user)."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise UserError("flashing a disk needs administrator rights",
                        f"Re-run with sudo:  sudo python3 {_prog()} --flash")


def _preflight_flash() -> None:
    """The cheap checks that MUST pass before the ~900 MB download, so an unsupported machine doesn't
    fetch the whole image only to fail at the end. Platform + `dd` (the only external tool the write
    needs — the .xz is unpacked in-process). pick_target_device re-checks the platform and adds the
    tty + disk-present checks — also before the download."""
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise UserError("flashing from this tool is only supported on macOS and Linux",
                        "On Windows, flash the image with Raspberry Pi Imager (Choose OS → Use "
                        "custom → the downloaded .img.xz), then run this tool with no --flash to "
                        "inject the code.")
    if shutil.which("dd") is None:
        raise UserError("`dd` is not on PATH, so this tool cannot write a card",
                        "Flash with Raspberry Pi Imager instead, then run with no --flash to inject.")
    # No `xz` check: the .img.xz is unpacked in-process by Python's stdlib lzma (see _write_xz_to),
    # so --flash has NO external dependency beyond dd — nothing to install on a fresh macOS.


def _describe_device(dev: str) -> str:
    """A short 'SIZE — “label”' for a device node, for the final overwrite confirmation — so the
    strongest gate names the disk the way the picker did, not a bare /dev node. Best-effort: '' if
    the OS can't tell us."""
    whole = _whole_disk_id(dev)
    try:
        if sys.platform == "darwin":
            import plistlib
            out = subprocess.run(["diskutil", "info", "-plist", whole],
                                 capture_output=True, timeout=15).stdout
            info = plistlib.loads(out)
            size = _human_size(info.get("TotalSize") or info.get("Size"))
            label = info.get("VolumeName") or info.get("MediaName") or ""
        else:
            out = subprocess.run(["lsblk", "-dno", "SIZE,MODEL", f"/dev/{whole}"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            parts = out.split(None, 1)
            size = parts[0] if parts else "?"
            label = parts[1].strip() if len(parts) > 1 else ""
    except Exception:  # noqa: BLE001
        return ""
    return f"{size}" + (f' — “{label}”' if label else "")


def _write_xz_to(image: Path, out) -> None:
    """Stream a .xz image, decompressed IN-PROCESS via stdlib lzma, into `out` (dd's stdin), with a
    percent readout driven by how much of the compressed file we've consumed (raw.tell()). No external
    `xz`. LZMAFile handles a multi-stream .xz, and raises on a truncated/corrupt one — a short write
    must NEVER be mistaken for a whole image (the --flash path also checksum-verifies the download;
    this covers the manual --image path and any mid-read corruption)."""
    comp_total = image.stat().st_size or 1
    last = 0.0
    try:
        with open(image, "rb") as raw, lzma.LZMAFile(raw) as z:
            while True:
                chunk = z.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)                          # OSError here = dd died; let it propagate
                now = time.monotonic()
                if now - last >= 1.0:
                    last = now
                    try:
                        pct = min(raw.tell() * 100 // comp_total, 100)
                    except OSError:
                        pct = 0
                    sys.stdout.write(f"\r  writing… {pct:3d}%")
                    sys.stdout.flush()
    except (lzma.LZMAError, EOFError):
        raise UserError("the image is truncated or not a valid .xz",
                        "Re-download it (or re-run --flash to fetch it fresh) and try again.") from None
    sys.stdout.write("\r  writing… 100%   \n")


def write_image(image: Path, device: str) -> None:
    """Write the (optionally .xz) image to a block device — behind an explicit confirmation and a
    POSITIVE removability check so you can't nuke your system disk by a typo. A .xz image is unpacked
    in-process (stdlib lzma), so no external `xz` is required."""
    if not image.is_file():
        raise UserError(f"image not found: {image}",
                        "Check the path. Download the .img.xz from the releases page and pass it "
                        "with --image.")
    if not device.startswith("/dev/"):
        raise UserError(f"--device must be a /dev/ path, got: {device}",
                        "macOS: find it with `diskutil list` (e.g. /dev/disk4). "
                        "Linux: `lsblk` (e.g. /dev/sdb).")
    if shutil.which("dd") is None:
        raise UserError("`dd` is not on PATH, so this tool cannot write the image",
                        "Flash the card with Raspberry Pi Imager instead, then run this tool with "
                        "no --device to inject the code.")
    if not _is_removable_target(device):
        raise UserError(
            f"refusing to write to {device} — it is not a removable/external disk (or the OS "
            f"couldn't confirm that it is)",
            "Writing to the wrong device destroys it. Double-check with `diskutil list` (macOS) "
            "or `lsblk` (Linux) and pass the SD-card reader's device only.")

    desc = _describe_device(device)
    print(f"\n  ABOUT TO OVERWRITE {device}" + (f"  ({desc})" if desc else "") + f" with {image.name}")
    print("  This ERASES everything on that device. Make sure it's the SD card.")
    if not confirm(f"  Overwrite {device}?"):
        raise UserError("aborted — no disk was written",
                        "Nothing changed. Re-run when you are sure of the device.")

    _unmount_disk(device)

    dd_target = device
    if sys.platform == "darwin" and "/dev/disk" in device and "/dev/rdisk" not in device:
        dd_target = device.replace("/dev/disk", "/dev/rdisk")   # raw device: much faster
    print(f"  writing to {dd_target} …")

    if image.suffix == ".xz":
        # Unpack the .xz IN-PROCESS (stdlib lzma) straight into dd's stdin — no external `xz`, so a
        # fresh macOS needs nothing installed. dd still does the block-aligned raw write (writing to
        # /dev/rdiskN by hand needs block-multiple writes; dd handles that + is everywhere).
        dd = subprocess.Popen(["dd", f"of={dd_target}", "bs=4m"], stdin=subprocess.PIPE)
        try:
            _write_xz_to(image, dd.stdin)
            dd.stdin.close()
        except UserError:
            with contextlib.suppress(Exception):
                dd.stdin.close()
            dd.wait()
            raise
        except (OSError, lzma.LZMAError):
            with contextlib.suppress(Exception):
                dd.stdin.close()
            dd.wait()
            raise UserError("the image write failed while unpacking/writing", _dd_failure_fix(device))
        dd.wait()
        if dd.returncode != 0:
            raise UserError("the image write failed (dd returned an error)", _dd_failure_fix(device))
    else:
        have_pv = shutil.which("pv") is not None
        total = _uncompressed_size(image)
        if have_pv and total:
            pvp = subprocess.Popen(["pv", "-s", str(total), str(image)], stdout=subprocess.PIPE)
            dd = subprocess.Popen(["dd", f"of={dd_target}", "bs=4m"], stdin=pvp.stdout)
            if pvp.stdout:
                pvp.stdout.close()
            dd.communicate()
            pvp.wait()
            if dd.returncode or pvp.returncode:
                raise UserError("the image write failed (dd/pv returned an error)",
                                _dd_failure_fix(device))
        else:
            dd = subprocess.Popen(["dd", f"if={image}", f"of={dd_target}", "bs=4m"])
            _run_dd_with_progress(dd)
            if dd.returncode != 0:
                raise UserError("the image write failed (dd returned an error)",
                                _dd_failure_fix(device))
    subprocess.call(["sync"])
    print("  write complete.")


def _dd_failure_fix(device: str) -> str:
    return (f"The card is now in an unknown state — do NOT boot it. Common causes: the volume was "
            f"re-mounted mid-write (close Finder windows on it), the card is write-protected "
            f"(check the lock switch on a full-size SD adapter), or you need sudo: "
            f"sudo python3 {_prog()} --device {device} --image <image>. Re-run the write.")


def find_boot_after_write(device: str) -> Path | None:
    """After writing, the OS re-mounts the image's FAT partition. Find its mount point by asking
    the OS which partition of THIS device is mounted — NEVER guess by volume name (/Volumes/boot
    is predictable and could be another card's still-mounted partition, so name-guessing risks
    writing the plaintext secret onto the wrong volume). None if we can't confirm."""
    whole = _whole_disk_id(device)
    if sys.platform == "darwin":
        import plistlib
        try:
            out = subprocess.run(["diskutil", "list", "-plist", whole],
                                 capture_output=True, text=True, timeout=15).stdout
            info = plistlib.loads(out.encode())
        except Exception:  # noqa: BLE001
            return None
        for disk in info.get("AllDisksAndPartitions", []):
            for part in disk.get("Partitions", []):
                mp = part.get("MountPoint")
                content = (part.get("Content") or "").lower()
                name = (part.get("VolumeName") or "").lower()
                if mp and ("fat" in content or "efi" in content or name in ("bootfs", "boot")):
                    if part.get("DeviceIdentifier", "").startswith(whole):
                        return Path(mp)
        return None
    else:
        try:
            out = subprocess.run(["lsblk", "-nro", "NAME,FSTYPE,MOUNTPOINT", f"/dev/{whole}"],
                                 capture_output=True, text=True, timeout=15).stdout
        except Exception:  # noqa: BLE001
            return None
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) == 3 and parts[1].lower() == "vfat" and parts[2].startswith("/"):
                return Path(parts[2])
        return None


def _wait_for_remount(device: str, seconds: int = 20) -> Path | None:
    """After dd + sync the OS needs a moment to notice the new partition table and mount it.
    Poll instead of racing it — the alternative is telling the user to re-run with --boot for a
    card that would have mounted a second later."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = find_boot_after_write(device)
        if found and looks_like_pi_boot(found):
            return found
        time.sleep(2)
    return find_boot_after_write(device)


# --- eject guidance ----------------------------------------------------------------------------

def eject_command(boot_dir: Path) -> str:
    """The exact command to safely eject this card. Pulling the card without ejecting is how a
    freshly written file goes missing, so we hand over something they can paste."""
    if sys.platform == "darwin":
        return f"diskutil eject {boot_dir}"
    if sys.platform == "win32":
        return f"right-click {boot_dir} in File Explorer and choose Eject"
    return f"sudo umount {boot_dir}"


# --- main --------------------------------------------------------------------------------------

def _resolve_secret(arg: str | None) -> str:
    if not arg:
        return gen_secret()
    secret = normalize_secret(arg)
    problem = wellformed_problem(secret)
    if problem:
        raise UserError(f"--secret is not a usable claim code: {problem}",
                        "Fix it, or omit --secret entirely and let this tool generate a good one.")
    return secret


def _resolve_boot_dir(args) -> Path:
    """Where we are going to inject, having flashed first if asked. Every path out of here is
    either a directory we have verified, or a UserError that says what to do."""
    if args.device:
        if not args.image:
            raise UserError("--device also needs --image (the image file to write)",
                            f"e.g. sudo python3 {_prog()} --device {args.device} "
                            f"--image ambrogio-<version>.img.xz")
        write_image(args.image, args.device)
        if args.boot:
            return args.boot
        print("  waiting for the card to re-mount …")
        found = _wait_for_remount(args.device)
        if found is None:
            raise UserError(
                "the image was written, but the boot partition did not re-mount so the claim code "
                "was NOT injected",
                "Unplug and re-insert the card, then run this again with no --device (it will "
                "auto-detect), or name the mount: "
                f"python3 {_prog()} --boot /Volumes/bootfs")
        print(f"  card re-mounted at {found}")
        return found
    if args.image:
        raise UserError("--image only makes sense together with --device",
                        "To flash AND inject: --device /dev/diskN --image <file>. To just inject "
                        "into a card you already flashed with Raspberry Pi Imager, run this with "
                        "no arguments at all.")
    if args.boot:
        return args.boot
    boot = select_boot_partition(enumerate_boot_candidates())
    print(f"  found a flashed card at {boot}")
    return boot


def _handle_existing(boot_dir: Path, secret: str, force: bool) -> None:
    """A code is already on this card. Decide what to do about it OUT LOUD — silently replacing it
    would invalidate a sheet the user may already have printed and taped to the box."""
    existing = read_existing_secret(boot_dir)
    if existing is None:
        return                      # nothing there: the normal first-run case
    if existing == secret:
        print("  this exact code is already on the card — re-writing and re-verifying it")
        return
    shown = group(existing) if is_wellformed(existing) else "(unreadable)"
    print(f"\n  This card ALREADY carries a claim code: {shown}")
    print("  Replacing it means any sheet you already printed for this card is wrong.")
    if force:
        print("  --force given: replacing it.")
        return
    if not sys.stdin.isatty():
        raise UserError(
            "the card already has a claim code and I will not replace it without being asked to",
            "Re-run with --force to replace it, or use the code that is already there.")
    if not confirm("  Replace it with a new one?"):
        raise UserError("stopped — the card's existing claim code was left alone",
                        "Nothing changed. The code already on the card is still the box's code.")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog=_prog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Put a claim code on a flashed Ambrogio SD card. A box flashed without one boots, "
            "joins your network — and can never be claimed, by you or anyone else.\n\n"
            "Normal use, with the freshly flashed card still in the reader:\n"
            "    python3 %(prog)s\n"),
        epilog=("The code is printed here and saved as a printable sheet (HTML — open it and "
                "print it). Keep it: nothing on the box can tell it to you later."))
    ap.add_argument("--flash", action="store_true",
                    help="the all-in-one path (macOS/Linux, needs sudo): download the latest image, "
                         "let you pick the SD card from a list, flash it, then inject the code. No "
                         "Raspberry Pi Imager, no --device/--image to figure out.")
    ap.add_argument("--boot", type=Path, metavar="MOUNT",
                    help="the mounted boot partition to inject into (e.g. /Volumes/bootfs). Omit "
                         "to auto-detect the flashed card.")
    ap.add_argument("--device", metavar="DEV",
                    help="ALSO flash the image to this block device first (e.g. /dev/disk4), then "
                         "inject. Requires --image. Erases the device. (--flash does this for you "
                         "with a picker + download.)")
    ap.add_argument("--image", type=Path, metavar="FILE",
                    help="image file (.img or .img.xz) to write — only used with --device")
    ap.add_argument("--secret", metavar="CODE",
                    help=f"use this claim code instead of a generated one ({SECRET_LEN} characters "
                         f"from {ALPHABET})")
    ap.add_argument("--out", type=Path, default=_default_sheet_dir(), metavar="DIR",
                    help=f"where to write the printable code sheet (default: {DEFAULT_OUT_DIR}). "
                         f"It holds a live secret, so it may not be inside a git repository.")
    ap.add_argument("--force", action="store_true",
                    help="replace a claim code already on the card, and skip the "
                         "'this looks like a Pi boot partition' check")
    ap.add_argument("--force-rekey", action="store_true",
                    help="recover a box you already own but lost the code for: adopt this code "
                         "even though the box is CLAIMED (keeps its data). Without this, a preset "
                         "is refused on a claimed box, so a forgotten card can't hijack it.")
    args = ap.parse_args()

    # --flash is the guided path: it FILLS IN --device (a disk you pick) and --image (downloaded),
    # so it's mutually exclusive with spelling those out yourself.
    if args.flash and (args.device or args.image or args.boot):
        raise UserError("--flash can't be combined with --device/--image/--boot",
                        "Use --flash on its own for the guided download+pick+flash, OR spell it out "
                        "with --device/--image yourself. Not both.")

    # Fail on a bad --secret / --out before touching any hardware, and before we bother the user
    # with a disk-overwrite confirmation.
    secret = _resolve_secret(args.secret)
    _guard_out_dir(args.out)

    # The all-in-one path. ORDER MATTERS: every check that can fail must run BEFORE the ~900 MB
    # download, so an unsupported machine (Windows, no tty, no disk, no xz) never fetches the whole
    # image only to fail. root → cheap tool/platform preflight → pick the disk (tty + a disk present)
    # → THEN download → hand off to the same flash+inject flow as --device.
    if args.flash:
        _require_root_for_flash()
        _preflight_flash()
        args.device = pick_target_device()
        args.image = fetch_latest_image()

    boot_dir = _resolve_boot_dir(args)
    check_boot_dir(boot_dir, force=args.force)
    _handle_existing(boot_dir, secret, args.force)

    target = inject_secret(boot_dir, secret, force_rekey=args.force_rekey)
    print(f"  wrote {target} and read it back — the code is on the card")
    if args.force_rekey:
        print("  (force-rekey marker set: the box will adopt this code even if it is already "
              "claimed — its data is kept)")

    ssid = ap_ssid_for(secret)
    payload = wifi_qr_payload(ssid, secret)

    print("\n" + "=" * 52)
    print(f"  Claim code:   {group(secret)}     (type it as {secret})")
    print(f"  Setup Wi-Fi:  {ssid}")
    print("  The code is the box's claim code AND its setup Wi-Fi password.")
    print("=" * 52)

    # The sheet is the durable copy; the terminal one scrolls away. Never let a sheet failure
    # hide the code that is already on the card.
    try:
        sheet = write_code_sheet(args.out, ssid, secret, payload)
        print(f"\n  Printable code sheet:  {sheet}")
        print("  PRINT IT AND KEEP IT — open it in a browser, then Print (or Save as PDF).")
    except Exception as e:  # noqa: BLE001 — the card is already written; nothing here may abort
        problem = e.problem if isinstance(e, UserError) else f"{type(e).__name__}: {e}"
        print(f"\n  WARNING: couldn't write the code sheet: {problem}", file=sys.stderr)
        if isinstance(e, UserError) and e.fix:
            print(f"           {e.fix}", file=sys.stderr)
        print("           The code above is already on the card — WRITE IT DOWN NOW.",
              file=sys.stderr)

    print("\n  Scan this to join the box's setup Wi-Fi (only needed if it can't reach your "
          "network):\n")
    print_qr_ascii(payload)

    print(f"\n  Next: eject the card  —  {eject_command(boot_dir)}")
    print("        then put it in the Pi and power it up.")
    # The honest caveat about a card that has already been used: the box adopts a newly injected
    # code on the next boot, but ONLY while it is still unclaimed. Saying "re-flash first" here
    # (as this tool used to) would send people to wipe a box that did not need wiping.
    # Do NOT invent a recovery gesture here. An earlier draft printed "power-cycle 3x within 10s
    # of boot"; nothing in the appliance counts power-cycles (`core.main physical-reset` is a CLI
    # verb needing a shell, which the public image does not give you). Printing a rescue that does
    # not exist is worse than printing none: it sends someone to stand over a box pulling the plug.
    print("\n  If this card has booted before: the box picks the new code up on its next boot,\n"
          "  but only while it is still UNCLAIMED. A box that already has an owner refuses to be\n"
          "  re-keyed, and there is no gesture on the box that undoes that — re-flashing is the\n"
          "  only way back in, and it wipes the box. Keep the printed sheet.")
    return 0


def _entry() -> int:
    """Wrap main() so nothing reaches the user as a traceback. A stack trace is a bug report from
    a program that gave up; every path here should be a sentence instead."""
    try:
        return main()
    except UserError as e:
        print(f"\n  Stopped: {e.problem}", file=sys.stderr)
        if e.fix:
            print(f"\n  What to do: {e.fix}", file=sys.stderr)
        print("", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n  Interrupted. If a disk write was in progress the card is incomplete — "
              "re-run it.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 — last line of defence: report, don't dump a traceback
        if os.environ.get("AMBROGIO_DEBUG"):
            raise
        print(f"\n  Stopped: unexpected error — {type(e).__name__}: {e}", file=sys.stderr)
        print("\n  What to do: this is a bug in the tool, not something you did wrong. Re-run "
              "with AMBROGIO_DEBUG=1 for the full details, and please report it.\n",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(_entry())
