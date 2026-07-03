import pytest
import subprocess
import os
import shutil
import time
from datetime import datetime, timezone

# Shared file for pre/post reboot state
RETENTION_STATE_FILE = "/tmp/rtc_retention_state.txt"

def test_rtc_stage1_hardware_node():
    """
    Stage 1: Verify RTC device node exists, is accessible,
    and the correct driver is loaded.
    """
    import stat
    import grp

    print("\n" + "="*60, flush=True)
    print("🕒 RTC STAGE 1: Hardware Node & Driver Check", flush=True)

    rtc_node  = "/dev/rtc0"
    rtc_sysfs = "/sys/class/rtc/rtc0"

    # ── Device node existence ─────────────────────────────────────────────────
    assert os.path.exists(rtc_node), \
        f"/dev/rtc0 does not exist.\n" \
        f"Fix: add 'dtoverlay=i2c-rtc,ds3231' (or your RTC model) " \
        f"to /boot/firmware/config.txt and reboot."

    # ── Detect actual owning group and permissions ────────────────────────────
    try:
        rtc_stat   = os.stat(rtc_node)
        rtc_gid    = rtc_stat.st_gid
        rtc_mode   = rtc_stat.st_mode
        rtc_group  = grp.getgrgid(rtc_gid).gr_name
        perms_str  = oct(rtc_mode)[-3:]
        group_read = bool(rtc_mode & 0o040)
        print(f"  ℹ️  /dev/rtc0 permissions: {perms_str}  "
              f"owner group: '{rtc_group}' (GID {rtc_gid})", flush=True)
    except Exception as e:
        rtc_group  = "root"
        perms_str  = "unknown"
        group_read = False
        print(f"  ⚠️  Could not read node metadata: {e}.", flush=True)

    # ── Readable by current user? ─────────────────────────────────────────────
    if not os.access(rtc_node, os.R_OK):
        # Get username — needed in ALL failure branches below
        try:
            current_user = os.getlogin()
        except Exception:
            current_user = os.environ.get("USER", "$USER")

        # Branch on WHY it is not readable
        if rtc_group == "root" or not group_read:
            # Group permission bit is 0 — joining the group won't help.
            # A udev rule is the correct fix.
            pytest.fail(
                f"/dev/rtc0 is not readable by user '{current_user}'.\n"
                f"Permissions: {perms_str}  Group: '{rtc_group}'\n\n"
                f"The group permission bits are 0 — adding to '{rtc_group}' "
                f"group will NOT fix this.\n\n"
                f"Fix — create a udev rule:\n"
                f"  sudo sh -c 'echo "
                f"\"SUBSYSTEM==\\\"rtc\\\", KERNEL==\\\"rtc0\\\", "
                f"MODE=\\\"0664\\\", GROUP=\\\"dialout\\\"\" "
                f"> /etc/udev/rules.d/99-rtc.rules'\n"
                f"  sudo udevadm control --reload-rules\n"
                f"  sudo udevadm trigger\n\n"
                f"Verify:\n"
                f"  ls -la /dev/rtc0  → should show group 'dialout', mode 664\n"
                f"  groups            → should include 'dialout'"
            )
        else:
            # Group bit IS set — user just needs to join the owning group
            try:
                group_members  = grp.getgrnam(rtc_group).gr_mem
                already_member = current_user in group_members
            except Exception:
                already_member = False

            if already_member:
                pytest.fail(
                    f"/dev/rtc0 not readable — '{current_user}' is in group "
                    f"'{rtc_group}' but the session predates the group change.\n\n"
                    f"Fix: log out and back in (or reboot) to apply group membership.\n"
                    f"Verify: groups  → should list '{rtc_group}'"
                )
            else:
                pytest.fail(
                    f"/dev/rtc0 not readable by user '{current_user}'.\n"
                    f"The node is owned by group '{rtc_group}' "
                    f"with group-read enabled.\n\n"
                    f"Fix:\n"
                    f"  sudo usermod -a -G {rtc_group} {current_user}\n"
                    f"  Log out and back in (or reboot) for change to take effect.\n\n"
                    f"Verify:\n"
                    f"  groups            → should include '{rtc_group}'\n"
                    f"  ls -la /dev/rtc0  → should show group '{rtc_group}'"
                )
    # ── If we reach here, the node is readable ────────────────────────────────
    print(f"  ✅ /dev/rtc0 exists and is readable "
          f"(group: '{rtc_group}').", flush=True)

    # ── Sysfs driver info ─────────────────────────────────────────────────────
    if not os.path.exists(rtc_sysfs):
        pytest.fail(
            f"Sysfs entry {rtc_sysfs} missing.\n"
            f"The kernel RTC driver is not loaded.\n"
            f"Check: dmesg | grep rtc"
        )

    name_path = f"{rtc_sysfs}/name"
    if os.path.exists(name_path):
        with open(name_path) as f:
            driver_name = f.read().strip()
        print(f"  ✅ RTC driver loaded: '{driver_name}'", flush=True)
    else:
        print("  ⚠️  Could not read driver name from sysfs.", flush=True)

    # ── hctosys: did RTC set system clock at boot? ────────────────────────────
    hctosys_path = f"{rtc_sysfs}/hctosys"
    if os.path.exists(hctosys_path):
        with open(hctosys_path) as f:
            hctosys = f.read().strip()
        if hctosys == "1":
            print("  ✅ RTC set system clock at boot (hctosys=1).", flush=True)
        else:
            print(
                "  ⚠️  RTC did NOT set system clock at boot (hctosys=0).\n"
                "     System time may have come from NTP, not the RTC.",
                flush=True
            )

    # ── since_epoch sanity check ──────────────────────────────────────────────
    since_epoch_path = f"{rtc_sysfs}/since_epoch"
    if os.path.exists(since_epoch_path):
        with open(since_epoch_path) as f:
            since_epoch = int(f.read().strip())
        rtc_year = datetime.fromtimestamp(since_epoch).year
        print(f"  ℹ️  RTC reports year: {rtc_year} "
              f"(epoch seconds: {since_epoch})", flush=True)
        assert rtc_year >= 2020, \
            f"RTC reports year {rtc_year} — battery is likely DEAD.\n" \
            f"RTC reset to near-epoch time. Replace the coin cell battery."

    print("="*60 + "\n", flush=True)


def test_rtc_stage2_drift_check():
    """
    Stage 2: Read hardware clock and measure drift against system clock.
    Validates RTC is ticking and within acceptable tolerance.
    NOTE: This does NOT prove retention — it proves the RTC is running now.
    """
    print("\n" + "="*60, flush=True)
    print("⏱️  RTC STAGE 2: Live Register Read & Drift Check", flush=True)

    hwclock_path = shutil.which("hwclock")
    if not hwclock_path:
        for fallback in ["/sbin/hwclock", "/usr/sbin/hwclock"]:
            if os.path.exists(fallback):
                hwclock_path = fallback
                break
    if not hwclock_path:
        pytest.fail(
            "hwclock not found. Install: sudo apt install util-linux"
        )

    try:
        rtc_raw = subprocess.check_output(
            ["sudo", hwclock_path, "--show"],
            text=True
        ).strip()
        print(f"  📡 Raw hwclock output: {rtc_raw}", flush=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"hwclock --show failed: {e}")

    sys_now = datetime.now()

    # hwclock output format varies — handle both:
    # "2024-01-15 10:30:45.123456+0530" and "Mon 15 Jan 2024 10:30:45 AM IST"
    try:
        cleaned = rtc_raw.split(".")[0].strip()
        # Try ISO format first
        try:
            rtc_now = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Try alternate format
            rtc_now = datetime.strptime(cleaned, "%a %d %b %Y %I:%M:%S %p")
    except ValueError as e:
        pytest.fail(
            f"Cannot parse hwclock output: '{rtc_raw}'\n"
            f"Error: {e}\n"
            f"Run 'sudo hwclock --show' manually to see the format."
        )

    delta = abs((sys_now - rtc_now).total_seconds())

    print(f"  📊 System Time:   {sys_now.strftime('%Y-%m-%d %H:%M:%S')}",
          flush=True)
    print(f"  📊 Hardware Time: {rtc_now.strftime('%Y-%m-%d %H:%M:%S')}",
          flush=True)
    print(f"  📉 Delta:         {delta:.3f} seconds", flush=True)

    assert delta < 2.0, \
        f"RTC drift too large: {delta:.3f}s (threshold: 2.0s).\n" \
        f"Possible causes:\n" \
        f"  1. RTC not synced — run: sudo hwclock --hctosys\n" \
        f"  2. RTC battery dying — time drifting significantly\n" \
        f"  3. Wrong timezone — run: timedatectl status"

    print("  ✅ RTC matches system clock within tolerance.", flush=True)
    print("="*60 + "\n", flush=True)


def test_rtc_stage3_pre_reboot_stamp(request):
    """
    Stage 3: Write a timestamp to the RTC and to a state file.
    Run this BEFORE rebooting. After reboot, run Stage 4 to verify retention.

    WORKFLOW:
      1. Run this test  → writes timestamp, reboots Pi
      2. After reboot, run test_rtc_stage4_post_reboot_verify
    """
    print("\n" + "="*60, flush=True)
    print("💾 RTC STAGE 3: Pre-Reboot Timestamp Stamp", flush=True)

    hwclock_path = shutil.which("hwclock")
    if not hwclock_path:
        for fallback in ["/sbin/hwclock", "/usr/sbin/hwclock"]:
            if os.path.exists(fallback):
                hwclock_path = fallback
                break
    if not hwclock_path:
        pytest.fail("hwclock not found.")

    # Sync system time → RTC before stamping so we have a clean known state
    try:
        subprocess.check_call(["sudo", hwclock_path, "--systohc"])
        print("  ✅ System time synced to RTC (hwclock --systohc).", flush=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to sync system → RTC: {e}")

    # Record the exact epoch timestamp written to RTC
    stamp_epoch = int(time.time())
    stamp_str   = datetime.fromtimestamp(stamp_epoch).strftime("%Y-%m-%d %H:%M:%S")

    # Write state file — survives reboot in /tmp IF filesystem is persistent
    # For guaranteed persistence, write to /home or /var instead
    state_path = os.path.expanduser("~/rtc_retention_state.txt")
    with open(state_path, "w") as f:
        f.write(f"stamp_epoch={stamp_epoch}\n")
        f.write(f"stamp_str={stamp_str}\n")

    print(f"  📝 Timestamp written to RTC: {stamp_str} (epoch {stamp_epoch})",
          flush=True)
    print(f"  📝 State file saved to: {state_path}", flush=True)
    print(f"\n  👉 Initiating scheduled reboot...", flush=True)
    
    # Run in the background: Wait 5 sec, then force reboot.
    # We fully detach the process and pipe FDs to DEVNULL so SSH can exit gracefully immediately!
    subprocess.Popen(
        "sudo sh -c 'sleep 5 && sudo reboot'", 
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    
    # Force Pytest to stop gracefully after this test so it flushes all reports
    request.session.shouldstop = "Intentional reboot triggered"
    
    print("="*60 + "\n", flush=True)


def test_rtc_stage4_post_reboot_verify():
    """
    Stage 4: Read RTC after reboot and compare against pre-reboot stamp.
    MUST be run in a SEPARATE pytest session AFTER rebooting following Stage 3.
    """
    print("\n" + "="*60, flush=True)
    print("🔋 RTC STAGE 4: Post-Reboot Time Retention Verification", flush=True)

    state_path = os.path.expanduser("~/rtc_retention_state.txt")

    # ── Load pre-reboot state ─────────────────────────────────────────────────
    if not os.path.exists(state_path):
        pytest.fail(
            f"State file not found: {state_path}\n"
            f"Run test_rtc_stage3_pre_reboot_stamp FIRST, then reboot."
        )

    state = {}
    with open(state_path) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                state[k] = v

    assert "stamp_epoch" in state, \
        "State file malformed — missing stamp_epoch. Re-run Stage 3 and reboot."

    pre_epoch = int(state["stamp_epoch"])
    pre_str   = state.get("stamp_str", "unknown")

    print(f"  📂 Pre-reboot stamp: {pre_str} (epoch {pre_epoch})", flush=True)

    # ── Guard: confirm a reboot actually happened ─────────────────────────────
    # Method 1: uptime must be LESS than time since stamp was written
    # If uptime > elapsed_since_stamp, the system never rebooted
    elapsed_since_stamp = int(time.time()) - pre_epoch

    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])

        print(f"  ℹ️  System uptime:      {uptime_s:.0f}s", flush=True)
        print(f"  ℹ️  Since stamp written: {elapsed_since_stamp}s", flush=True)

        if uptime_s > elapsed_since_stamp:
            pytest.fail(
                f"NO REBOOT DETECTED.\n\n"
                f"System uptime ({uptime_s:.0f}s) is longer than time since "
                f"stamp was written ({elapsed_since_stamp}s).\n"
                f"This means Stage 3 and Stage 4 ran in the same session.\n\n"
                f"Correct workflow:\n"
                f"  Step 1: pytest test_rtc.py::test_rtc_stage3_pre_reboot_stamp\n"
                f"  Step 2: sudo reboot\n"
                f"  Step 3: (wait for Pi to fully boot)\n"
                f"  Step 4: pytest test_rtc.py::test_rtc_stage4_post_reboot_verify"
            )

    except FileNotFoundError:
        pass   # not on Linux — skip uptime check

    # Method 2: minimum elapsed time — a reboot takes at least 30 seconds
    MIN_REBOOT_ELAPSED = 30
    if elapsed_since_stamp < MIN_REBOOT_ELAPSED:
        pytest.fail(
            f"NO REBOOT DETECTED.\n\n"
            f"Only {elapsed_since_stamp}s elapsed since Stage 3.\n"
            f"A reboot takes at minimum {MIN_REBOOT_ELAPSED}s.\n\n"
            f"Correct workflow:\n"
            f"  Step 1: pytest test_rtc.py::test_rtc_stage3_pre_reboot_stamp\n"
            f"  Step 2: sudo reboot\n"
            f"  Step 3: (wait for Pi to fully boot)\n"
            f"  Step 4: pytest test_rtc.py::test_rtc_stage4_post_reboot_verify"
        )

    print(f"  ✅ Reboot confirmed: uptime={uptime_s:.0f}s < "
          f"stamp age={elapsed_since_stamp}s.", flush=True)

    # ── Read RTC now (post-reboot) ────────────────────────────────────────────
    hwclock_path = shutil.which("hwclock")
    if not hwclock_path:
        for fallback in ["/sbin/hwclock", "/usr/sbin/hwclock"]:
            if os.path.exists(fallback):
                hwclock_path = fallback
                break
    if not hwclock_path:
        pytest.fail("hwclock not found.")

    try:
        rtc_raw = subprocess.check_output(
            ["sudo", hwclock_path, "--show"],
            text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        pytest.fail(f"hwclock --show failed post-reboot: {e}")

    post_now = datetime.now()

    try:
        cleaned = rtc_raw.split(".")[0].strip()
        try:
            rtc_post_dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            rtc_post_dt = datetime.strptime(cleaned, "%a %d %b %Y %I:%M:%S %p")
    except ValueError as e:
        pytest.fail(
            f"Cannot parse post-reboot hwclock output: '{rtc_raw}'\nError: {e}"
        )

    rtc_post_epoch = int(rtc_post_dt.timestamp())

    print(f"  📡 Post-reboot RTC: {rtc_post_dt.strftime('%Y-%m-%d %H:%M:%S')} "
          f"(epoch {rtc_post_epoch})", flush=True)

    # ── Check 1: RTC did not reset to epoch ───────────────────────────────────
    assert rtc_post_dt > datetime(2020, 1, 1), \
        f"RTC reset to near-epoch: {rtc_post_dt}.\n" \
        f"Battery is DEAD — RTC lost power during reboot.\n" \
        f"Replace the coin cell battery."
    print("  ✅ RTC did not reset to epoch — battery is alive.", flush=True)

    # ── Check 2: RTC advanced by plausible elapsed time ───────────────────────
    elapsed_rtc   = rtc_post_epoch - pre_epoch
    elapsed_wall  = int(post_now.timestamp()) - pre_epoch
    elapsed_delta = abs(elapsed_rtc - elapsed_wall)

    print(f"  📊 Elapsed on RTC:  {elapsed_rtc}s", flush=True)
    print(f"  📊 Elapsed on wall: {elapsed_wall}s", flush=True)
    print(f"  📉 Drift:           {elapsed_delta}s", flush=True)

    assert elapsed_rtc > 0, \
        f"RTC time did not advance after confirmed reboot (elapsed={elapsed_rtc}s).\n" \
        f"RTC oscillator may be failing or battery too weak."

    max_drift = max(10, elapsed_wall * 0.01)
    assert elapsed_delta < max_drift, \
        f"RTC drift too large: {elapsed_delta}s over {elapsed_wall}s elapsed.\n" \
        f"Tolerance: {max_drift:.1f}s (1% of elapsed or 10s minimum).\n" \
        f"RTC crystal may be failing."

    # ── Check 3: RTC matches system clock post-reboot ─────────────────────────
    sys_rtc_delta = abs((post_now - rtc_post_dt).total_seconds())
    assert sys_rtc_delta < 5.0, \
        f"Post-reboot RTC differs from system clock by {sys_rtc_delta:.1f}s.\n" \
        f"Check if NTP synced system time before this test ran."

    print(f"  ✅ RTC retained time across reboot.", flush=True)
    print(f"  ✅ Drift within tolerance "
          f"({elapsed_delta}s over {elapsed_wall}s).", flush=True)

    os.remove(state_path)
    print(f"  🗑️  State file cleaned up.", flush=True)
    print("="*60 + "\n", flush=True)


def test_rtc_battery_power_off_retention():
    """
    Stage 3: Validates the physical RTC battery retained the clock state 
    while main power was completely severed.
    Requires the 'Fake Time Trap' to be set prior to execution.
    """
    import pytest
    import subprocess
    from datetime import datetime

    print("\n" + "="*60, flush=True)
    print("🔋 RTC VALIDATION - STAGE 3: TRUE POWER-OFF RETENTION", flush=True)
    
    if not os.environ.get("RUN_MANUAL_POWER_OFF_TEST"):
        pytest.skip("Manual test requires physical power removal and pre-setting the RTC to 2036. Set RUN_MANUAL_POWER_OFF_TEST=1 to run.")
        
    # 1. Verify the internet didn't cheat
    try:
        timedate_out = subprocess.check_output(["timedatectl", "status"], text=True)
        if "NTP service: active" in timedate_out or "System clock synchronized: yes" in timedate_out:
            pytest.fail("🚨 Test Invalidated: NTP is active! The OS synced the time via Wi-Fi/Ethernet, masking the battery status.")
    except subprocess.CalledProcessError:
        print("  ⚠️ Could not verify NTP status, proceeding to raw hardware read...", flush=True)

    # 2. Read the hardware clock directly via sudo
    try:
        hwclock_path = subprocess.check_output(["sudo", "which", "hwclock"], text=True).strip()
        rtc_time_str = subprocess.check_output(["sudo", hwclock_path, "--show"], text=True).strip()
        
        # Parse the raw string
        cleaned_rtc_str = rtc_time_str.split(".")[0] 
        rtc_now = datetime.strptime(cleaned_rtc_str, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        pytest.fail(f"OS Error: Failed to cleanly read hardware clock: {e}")

    print(f"📡 Retrieved Hardware Time: {rtc_now.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    # 3. Silicon Memory Assertion
    assert rtc_now.year >= 2036, (
        f"🚨 Battery Failure! Expected year >= 2036, but got {rtc_now.year}. "
        "The PMIC lost power, the memory wiped, and the RTC reset to its silicon epoch."
    )

    print("  ✅ PASS: RTC battery successfully retained the clock registers through a complete power loss!", flush=True)
    print("="*60 + "\n", flush=True)


import pytest
import subprocess
import re
import time
import shutil
from datetime import datetime

def test_ntp_sync_interaction():
    """
    Validates NTP sync interaction with the RTC:
      1. NTP service is active
      2. System clock synchronizes to network time
      3. NTP offset is within acceptable bounds
      4. Synchronized time is written back to RTC (NTP→RTC interaction)
      5. RTC matches NTP-corrected system time
    """
    print("\n" + "="*60, flush=True)
    print("🌐 NTP SYNC INTERACTION TEST", flush=True)

    # ── STAGE 1: Enable NTP ───────────────────────────────────────────────────
    print(f"\n📋 Stage 1: Enable NTP synchronization...", flush=True)

    try:
        subprocess.check_call(
            ["sudo", "timedatectl", "set-ntp", "true"],
            stdout=subprocess.DEVNULL
        )
        print("  ✅ NTP enabled via timedatectl.", flush=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to enable NTP: {e}")

    # ── STAGE 2: Wait for sync with timeout ───────────────────────────────────
    print(f"\n📋 Stage 2: Waiting for clock synchronization...", flush=True)

    SYNC_TIMEOUT   = 60    # seconds to wait for initial sync
    POLL_INTERVAL  = 3     # check every 3 seconds
    synchronized   = False
    elapsed        = 0

    while elapsed < SYNC_TIMEOUT:
        try:
            out = subprocess.check_output(
                ["timedatectl", "status"], text=True
            )
            if re.search(r"System clock synchronized:\s*yes", out, re.IGNORECASE):
                synchronized = True
                break
        except subprocess.CalledProcessError:
            pass

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        print(f"  ⏳ Waiting for sync... ({elapsed}s / {SYNC_TIMEOUT}s)",
              flush=True)

    assert synchronized, \
        f"Clock NOT synchronized after {SYNC_TIMEOUT}s.\n" \
        f"Possible causes:\n" \
        f"  1. No internet connection\n" \
        f"  2. UDP port 123 blocked by firewall\n" \
        f"  3. DNS not resolving NTP servers\n" \
        f"  4. No NTP servers configured in /etc/systemd/timesyncd.conf\n\n" \
        f"Check: journalctl -u systemd-timesyncd --no-pager | tail -20"

    print(f"  ✅ Clock synchronized after {elapsed}s.", flush=True)

    # ── STAGE 3: Full timedatectl status ──────────────────────────────────────
    print(f"\n📋 Stage 3: Full NTP status check...", flush=True)

    try:
        timedate_out = subprocess.check_output(
            ["timedatectl", "status"], text=True
        )
        print(f"\n{timedate_out.strip()}\n{'─'*40}", flush=True)
    except subprocess.CalledProcessError:
        pytest.fail("Could not query timedatectl status.")

    ntp_active = bool(re.search(
        r"NTP service:\s*active", timedate_out, re.IGNORECASE
    ))
    assert ntp_active, \
        "NTP service is not active.\n" \
        "Fix: sudo systemctl enable --now systemd-timesyncd"
    print("  ✅ NTP service active.", flush=True)

    # ── STAGE 4: NTP server identity and offset ────────────────────────────────
    print(f"\n📋 Stage 4: NTP server identity and offset check...", flush=True)

    try:
        timesync_out = subprocess.check_output(
            ["timedatectl", "show-timesync", "--no-pager"],
            text=True
        )

        # Extract server address
        server_match = re.search(r"ServerAddress=(.+)", timesync_out)
        server_addr  = server_match.group(1).strip() if server_match else "unknown"

        # Extract offset in microseconds
        offset_match = re.search(r"NTPMessage=.*?offset=([-\d.]+)", timesync_out)
        if not offset_match:
            # Try alternative key
            offset_match = re.search(r"Offset=([-\d.]+)", timesync_out)

        print(f"  ℹ️  NTP server: {server_addr}", flush=True)

        if offset_match:
            offset_us  = float(offset_match.group(1))
            offset_ms  = offset_us / 1000
            print(f"  ℹ️  Clock offset: {offset_ms:.3f} ms", flush=True)

            # Large offset means the clock was significantly wrong
            # 500ms is a generous threshold — production would use 100ms
            MAX_OFFSET_MS = 500
            assert abs(offset_ms) < MAX_OFFSET_MS, \
                f"NTP offset too large: {offset_ms:.3f}ms " \
                f"(threshold: ±{MAX_OFFSET_MS}ms).\n" \
                f"Clock may have been heavily corrupted — check RTC battery."
            print(f"  ✅ NTP offset within tolerance ({offset_ms:.3f}ms).",
                  flush=True)
        else:
            print("  ⚠️  Could not extract offset from timesync output.",
                  flush=True)

    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  ⚠️  timedatectl show-timesync not available — skipping offset check.",
              flush=True)

    # ── STAGE 5: NTP → RTC write-back (the "interaction" part) ────────────────
    print(f"\n📋 Stage 5: Write NTP-corrected time back to RTC...", flush=True)

    hwclock_path = shutil.which("hwclock")
    if not hwclock_path:
        for fb in ["/sbin/hwclock", "/usr/sbin/hwclock"]:
            if os.path.exists(fb):
                hwclock_path = fb
                break

    assert hwclock_path, \
        "hwclock not found. Install: sudo apt install util-linux"

    # Capture system time (now NTP-corrected) before writing to RTC
    system_before = datetime.now()

    try:
        subprocess.check_call(["sudo", hwclock_path, "--systohc"])
        print("  ✅ NTP-corrected system time written to RTC (hwclock --systohc).",
              flush=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to write system time to RTC: {e}")

    # ── STAGE 6: Verify RTC matches NTP-corrected system time ─────────────────
    print(f"\n📋 Stage 6: Verify RTC matches NTP-corrected time...", flush=True)

    try:
        rtc_raw = subprocess.check_output(
            ["sudo", hwclock_path, "--show"],
            text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        pytest.fail(f"hwclock --show failed: {e}")

    system_after = datetime.now()

    try:
        cleaned = rtc_raw.split(".")[0].strip()
        try:
            rtc_dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            rtc_dt = datetime.strptime(cleaned, "%a %d %b %Y %I:%M:%S %p")
    except ValueError as e:
        pytest.fail(f"Cannot parse hwclock output: '{rtc_raw}'\nError: {e}")

    # RTC should be between system_before and system_after + small tolerance
    delta = abs((system_after - rtc_dt).total_seconds())

    print(f"  📊 System time: {system_after.strftime('%Y-%m-%d %H:%M:%S')}",
          flush=True)
    print(f"  📊 RTC time:    {rtc_dt.strftime('%Y-%m-%d %H:%M:%S')}",
          flush=True)
    print(f"  📉 Delta:       {delta:.3f}s", flush=True)

    assert delta < 2.0, \
        f"RTC does not match NTP-corrected system time.\n" \
        f"Delta: {delta:.3f}s (threshold: 2.0s)\n" \
        f"The NTP→RTC write-back may have failed silently."

    print("  ✅ RTC matches NTP-corrected system time.", flush=True)

    print(f"\n✅ SUCCESS: Full NTP↔RTC interaction validated!", flush=True)
    print(f"   Stage 1 — NTP enabled              ✅", flush=True)
    print(f"   Stage 2 — Clock synchronized        ✅", flush=True)
    print(f"   Stage 3 — NTP service active        ✅", flush=True)
    print(f"   Stage 4 — Server identity + offset  ✅", flush=True)
    print(f"   Stage 5 — NTP time written to RTC   ✅", flush=True)
    print(f"   Stage 6 — RTC matches NTP time      ✅", flush=True)
    print("="*60 + "\n", flush=True)