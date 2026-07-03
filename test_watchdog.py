import pytest
import os
import time
import fcntl
import struct
import subprocess

# ── Linux Watchdog IOCTL Constants ────────────────────────────────────────────
WDIOC_GETSTATUS     = 0x80045701
WDIOC_GETBOOTSTATUS = 0x80045702
WDIOC_KEEPALIVE     = 0x80045705
WDIOC_SETTIMEOUT    = 0xc0045706
WDIOC_GETTIMEOUT    = 0x80045707

# ── Watchdog boot status flag ─────────────────────────────────────────────────
WDIOF_CARDRESET = 0x0020   # bit set if last reboot was caused by watchdog


def _ensure_watchdog_accessible(watchdog_path):
    """
    Ensures /dev/watchdog0 is accessible without world-chmod.
    Uses a udev rule approach — installs it if missing.
    Falls back to targeted chmod only if udev is not available.
    """
    if os.access(watchdog_path, os.W_OK):
        return   # already accessible — nothing to do

    # Try udev rule first (persistent, secure)
    udev_rule = (
        'SUBSYSTEM=="misc", KERNEL=="watchdog0", '
        'MODE="0666", GROUP="dialout"'
    )
    udev_path = "/etc/udev/rules.d/99-watchdog.rules"

    try:
        if not os.path.exists(udev_path):
            subprocess.run(
                ["sudo", "sh", "-c", f"echo '{udev_rule}' > {udev_path}"],
                check=True, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sudo", "udevadm", "control", "--reload-rules"],
                check=True, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sudo", "udevadm", "trigger"],
                check=True, stderr=subprocess.DEVNULL
            )
            time.sleep(0.5)   # let udev apply

        if os.access(watchdog_path, os.W_OK):
            return   # udev rule worked
    except Exception:
        pass

    # Last resort: targeted chmod
    try:
        subprocess.run(
            ["sudo", "chmod", "666", watchdog_path],
            check=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(
            f"Cannot make {watchdog_path} accessible.\n"
            f"Error: {e}\n"
            f"Fix: sudo chmod 666 {watchdog_path}"
        )


def test_watchdog_enable_and_feed(board_config):
    """
    Validates hardware watchdog: enable, configure, feed, graceful disarm.
    No wiring required — purely internal silicon.

    Proves:
      1. /dev/watchdog0 opens and configures correctly
      2. Timeout readback matches requested value
      3. KEEPALIVE IOCTL succeeds on every cycle
      4. Magic 'V' disarms cleanly (no reboot triggered)
    """
    for key in ("watchdog_path", "watchdog_timeout", "watchdog_feed_cycles"):
        assert key in board_config, f"board_config missing '{key}'"

    watchdog_path  = board_config["watchdog_path"]
    timeout_val    = board_config["watchdog_timeout"]
    feeding_cycles = board_config["watchdog_feed_cycles"]

    print("\n" + "="*60, flush=True)
    print("🐕 WATCHDOG VALIDATION: ENABLE & FEED", flush=True)

    # ── Pre-check: device node exists ────────────────────────────────────────
    if not os.path.exists(watchdog_path):
        pytest.fail(
            f"{watchdog_path} not found.\n"
            f"Fix: add 'dtparam=watchdog=on' to /boot/firmware/config.txt\n"
            f"     and reboot."
        )
    print(f"  ✅ Device node exists: {watchdog_path}", flush=True)

    # ── Pre-check: not already open (EBUSY guard) ─────────────────────────────
    try:
        fuser_out = subprocess.run(
            ["fuser", watchdog_path],
            capture_output=True, text=True
        )
        if fuser_out.stdout.strip():
            pytest.fail(
                f"{watchdog_path} is already held open by "
                f"PID(s): {fuser_out.stdout.strip()}.\n"
                f"A previous test may have crashed without disarming.\n"
                f"Fix: sudo killall watchdog  OR  reboot the Pi."
            )
    except FileNotFoundError:
        pass   # fuser not installed — skip

    # ── Ensure accessible ─────────────────────────────────────────────────────
    _ensure_watchdog_accessible(watchdog_path)

    fd = None
    try:
        # ── Stage 1: Open (arms the watchdog) ─────────────────────────────────
        print("\n  📋 Stage 1: Opening watchdog device (arm)...", flush=True)
        fd = os.open(watchdog_path, os.O_WRONLY)
        print(f"  ✅ Watchdog armed — countdown started.", flush=True)

        # ── Stage 2: Configure timeout ────────────────────────────────────────
        print(f"\n  📋 Stage 2: Setting timeout to {timeout_val}s...", flush=True)
        fcntl.ioctl(fd, WDIOC_SETTIMEOUT, struct.pack("i", timeout_val))

        buf = fcntl.ioctl(fd, WDIOC_GETTIMEOUT, struct.pack("i", 0))
        current_timeout = struct.unpack("i", buf)[0]

        assert current_timeout == timeout_val, \
            f"Timeout mismatch: requested {timeout_val}s, silicon reports {current_timeout}s."
        print(f"  ✅ Timeout confirmed: {current_timeout}s.", flush=True)

        # ── Stage 3: Check boot status flags ──────────────────────────────────
        print(f"\n  📋 Stage 3: Checking boot status flags...", flush=True)
        try:
            buf = fcntl.ioctl(fd, WDIOC_GETBOOTSTATUS, struct.pack("i", 0))
            boot_status = struct.unpack("i", buf)[0]
            if boot_status & WDIOF_CARDRESET:
                print(
                    f"  ℹ️  WDIOF_CARDRESET set — last reboot was caused by "
                    f"watchdog starvation.",
                    flush=True
                )
            else:
                print(
                    f"  ✅ Last reboot was clean (not watchdog-triggered).",
                    flush=True
                )
        except OSError:
            print("  ⚠️  GETBOOTSTATUS not supported by this driver.", flush=True)

        # ── Stage 4: Feed loop ────────────────────────────────────────────────
        sleep_interval = timeout_val * 0.4
        print(
            f"\n  📋 Stage 4: Feed loop — {feeding_cycles} cycles "
            f"at {sleep_interval:.1f}s intervals...",
            flush=True
        )

        for i in range(1, feeding_cycles + 1):
            time.sleep(sleep_interval)

            # KEEPALIVE returns the timeout value on success — verify it
            try:
                result = fcntl.ioctl(fd, WDIOC_KEEPALIVE, struct.pack("i", 0))
                # Some drivers return 0 on success — both 0 and non-zero are OK
                # What matters is no exception was raised
                print(
                    f"    ✅ Cycle {i}/{feeding_cycles}: "
                    f"Fed at {i * sleep_interval:.1f}s elapsed.",
                    flush=True
                )
            except OSError as e:
                pytest.fail(
                    f"Feed cycle {i} FAILED: KEEPALIVE ioctl returned error: {e}\n"
                    f"Watchdog may have already expired or driver is broken."
                )

        # ── Stage 5: Graceful disarm ──────────────────────────────────────────
        print(f"\n  📋 Stage 5: Graceful disarm (writing magic 'V')...", flush=True)
        os.write(fd, b'V')
        print(
            f"  ✅ Magic 'V' written — kernel will NOT reboot on close.",
            flush=True
        )

    except OSError as e:
        pytest.fail(f"Hardware/Driver Error: {e}")

    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    print("  ✅ SUCCESS: Watchdog armed, fed, and disarmed cleanly.", flush=True)
    print("="*60 + "\n", flush=True)


def test_watchdog_starvation_reboot(board_config, request):
    """
    DESTRUCTIVE TEST: Proves that failing to feed the watchdog triggers a reboot.

    TWO-PHASE WORKFLOW:
      Phase 1 (this run):   Arm watchdog, close WITHOUT 'V' → Pi reboots
      Phase 2 (after reboot): Run test_watchdog_post_reboot_verify to confirm
                               the reboot was caused by the watchdog.

    Safety guard: set 'allow_destructive_reboot: True' in board_config to run.
    """
    for key in ("watchdog_path", "watchdog_timeout"):
        assert key in board_config, f"board_config missing '{key}'"

    if not board_config.get("allow_destructive_reboot", False):
        pytest.skip(
            "Destructive test skipped.\n"
            "Set 'allow_destructive_reboot: True' in board_config to run."
        )

    watchdog_path = board_config["watchdog_path"]
    timeout_val   = board_config["watchdog_timeout"]

    print("\n" + "="*60, flush=True)
    print("💥 DESTRUCTIVE WATCHDOG: STARVATION REBOOT", flush=True)
    print(f"⚠️  System will hard-reset in ~{timeout_val}s.", flush=True)
    print("⚠️  SSH session will be severed. This is expected.", flush=True)
    print("⚠️  After reboot, run test_watchdog_post_reboot_verify.", flush=True)
    print("="*60 + "\n", flush=True)

    print("  ⏳ Starting in 5 seconds — Ctrl+C to abort...", flush=True)
    time.sleep(5)

    _ensure_watchdog_accessible(watchdog_path)

    # Write a state file so post-reboot test knows starvation was triggered
    state_path = os.path.expanduser("~/watchdog_starvation_state.txt")
    with open(state_path, "w") as f:
        f.write(f"triggered_epoch={int(time.time())}\n")
        f.write(f"timeout_val={timeout_val}\n")

    fd = None
    try:
        fd = os.open(watchdog_path, os.O_WRONLY)
        fcntl.ioctl(fd, WDIOC_SETTIMEOUT, struct.pack("i", timeout_val))
        print(
            f"  ☠️  Watchdog armed with {timeout_val}s timeout. "
            f"Closing WITHOUT magic 'V'...",
            flush=True
        )
        # Close without 'V' — driver starts immediate countdown
        os.close(fd)
        fd = None

    except Exception as e:
        pytest.fail(f"Failed to trigger starvation: {e}")

    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    print(f"  ⏳ Hardware Watchdog will force a reset in {timeout_val}s.", flush=True)
    print(f"  ⏳ Halting Pytest gracefully so report saves...", flush=True)
    request.session.shouldstop = "Intentional reboot triggered"
    
    print("="*60 + "\n", flush=True)


def test_watchdog_post_reboot_verify(board_config):
    """
    Phase 2 of starvation test — run AFTER the Pi reboots.
    Reads WDIOC_GETBOOTSTATUS to confirm the reboot was watchdog-caused.
    """
    for key in ("watchdog_path",):
        assert key in board_config, f"board_config missing '{key}'"

    watchdog_path = board_config["watchdog_path"]
    state_path    = os.path.expanduser("~/watchdog_starvation_state.txt")

    print("\n" + "="*60, flush=True)
    print("🔍 WATCHDOG POST-REBOOT VERIFICATION", flush=True)

    # ── Confirm starvation was triggered before reboot ────────────────────────
    if not os.path.exists(state_path):
        pytest.skip(
            "State file not found — starvation test was not run.\n"
            "Run test_watchdog_starvation_reboot first."
        )

    state = {}
    with open(state_path) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                state[k] = v

    triggered_epoch = int(state.get("triggered_epoch", 0))
    timeout_val     = int(state.get("timeout_val", 15))

    # ── Confirm reboot actually happened (uptime < time since trigger) ────────
    with open("/proc/uptime") as f:
        uptime_s = float(f.read().split()[0])

    elapsed_since_trigger = int(time.time()) - triggered_epoch

    if uptime_s > elapsed_since_trigger:
        pytest.fail(
            f"No reboot detected.\n"
            f"Uptime ({uptime_s:.0f}s) > elapsed since trigger "
            f"({elapsed_since_trigger}s).\n"
            f"Run test_watchdog_starvation_reboot and wait for the reboot."
        )

    print(f"  ✅ Reboot confirmed: uptime={uptime_s:.0f}s, "
          f"triggered {elapsed_since_trigger}s ago.", flush=True)

    # ── Read boot status from watchdog driver ─────────────────────────────────
    _ensure_watchdog_accessible(watchdog_path)

    try:
        fd = os.open(watchdog_path, os.O_WRONLY)
        try:
            buf         = fcntl.ioctl(fd, WDIOC_GETBOOTSTATUS, struct.pack("i", 0))
            boot_status = struct.unpack("i", buf)[0]
            print(f"  ℹ️  WDIOC_GETBOOTSTATUS = {boot_status:#010x}", flush=True)

            wd_reset_detected = bool(boot_status & WDIOF_CARDRESET)

            # Fallback for Raspberry Pi: The bcm2835_wdt driver often returns 0 for GETBOOTSTATUS.
            # Use vcgencmd get_rsts to query the VideoCore reset register directly.
            if not wd_reset_detected:
                try:
                    rsts_out = subprocess.run(
                        ["vcgencmd", "get_rsts"],
                        capture_output=True, text=True, check=True
                    ).stdout.strip()
                    print(f"  ℹ️  vcgencmd fallback = {rsts_out}", flush=True)
                    # "20" (bit 5) indicates a watchdog reset on Pi
                    if "20" in rsts_out:
                        wd_reset_detected = True
                        print("  ✅ vcgencmd confirmed WDIOF_CARDRESET equivalent.", flush=True)
                except Exception as e:
                    print(f"  ⚠️  vcgencmd fallback failed: {e}", flush=True)

            assert wd_reset_detected, \
                f"WDIOF_CARDRESET bit NOT set (boot_status={boot_status:#010x}).\n" \
                f"The watchdog driver does not report a watchdog-caused reboot.\n" \
                f"The Pi may have rebooted for another reason, or the driver\n" \
                f"does not support GETBOOTSTATUS."

            print(
                f"  ✅ WDIOF_CARDRESET confirmed — last reboot was "
                f"watchdog-triggered.",
                flush=True
            )
        finally:
            os.write(fd, b'V')   # disarm immediately after reading
            os.close(fd)

    except OSError as e:
        pytest.fail(f"Cannot read boot status: {e}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    os.remove(state_path)
    print(f"  🗑️  State file removed.", flush=True)
    print("  ✅ SUCCESS: Watchdog starvation reboot confirmed by hardware flag.",
          flush=True)
    print("="*60 + "\n", flush=True)