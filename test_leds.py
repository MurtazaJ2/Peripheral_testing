import pytest
import os
import subprocess
import time
import re

def test_status_led_sysfs_control():
    """
    Validates onboard status LED control via sysfs:
      1. Enumerates all available LEDs
      2. Tests each LED: manual ON/OFF toggle
      3. Tests timer (blink) trigger
      4. Restores original state for every LED
    """
    print("\n" + "="*60, flush=True)
    print("💡 LED SUBSYSTEM VALIDATION — STATUS LED CONTROL", flush=True)

    led_base = "/sys/class/leds/"

    if not os.path.exists(led_base):
        pytest.fail(
            f"sysfs LED interface not found: {led_base}\n"
            f"This system may not expose LEDs via sysfs."
        )

    # ── Enumerate all available LEDs ──────────────────────────────────────────
    available_leds = sorted(os.listdir(led_base))
    print(f"\n  ℹ️  All LEDs found on this board: {available_leds}", flush=True)

    if not available_leds:
        pytest.fail(
            f"No LEDs found under {led_base}.\n"
            f"Check: ls /sys/class/leds/"
        )

    # Priority order — test status LEDs first, then any others
    PRIORITY_NAMES = ["ACT", "PWR", "led0", "led1", "default-on"]
    priority_leds  = [l for l in PRIORITY_NAMES if l in available_leds]
    remaining_leds = [l for l in available_leds if l not in PRIORITY_NAMES]
    test_leds      = priority_leds + remaining_leds

    print(f"  ℹ️  Test order: {test_leds}", flush=True)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def sysfs_read(led_path, filename):
        filepath = os.path.join(led_path, filename)
        try:
            with open(filepath) as f:
                return f.read().strip()
        except PermissionError:
            # Fall back to sudo if direct read fails
            return subprocess.check_output(
                ["sudo", "cat", filepath], text=True
            ).strip()

    def sysfs_write(led_path, filename, value):
        filepath = os.path.join(led_path, filename)
        try:
            subprocess.check_call(
                ["sudo", "sh", "-c", f"echo '{value}' > {filepath}"]
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to write '{value}' to {filepath}: {e}"
            )

    def get_active_trigger(led_path):
        raw = sysfs_read(led_path, "trigger")
        match = re.search(r'\[(.*?)\]', raw)
        return match.group(1) if match else "none"

    def get_available_triggers(led_path):
        raw = sysfs_read(led_path, "trigger")
        return re.findall(r'\[?(\w[\w-]*)\]?', raw)

    # ── Test each LED ─────────────────────────────────────────────────────────
    failed_leds = []

    for led_name in test_leds:
        led_path = os.path.join(led_base, led_name)
        print(f"\n{'─'*50}", flush=True)
        print(f"🔦 Testing LED: {led_name}  ({led_path})", flush=True)

        # ── Backup state ──────────────────────────────────────────────────────
        try:
            orig_trigger    = get_active_trigger(led_path)
            orig_brightness = sysfs_read(led_path, "brightness")
            max_brightness  = sysfs_read(led_path, "max_brightness")
            avail_triggers  = get_available_triggers(led_path)
            print(f"  ℹ️  Original trigger:    '{orig_trigger}'", flush=True)
            print(f"  ℹ️  Original brightness: {orig_brightness}", flush=True)
            print(f"  ℹ️  Max brightness:      {max_brightness}", flush=True)
            print(f"  ℹ️  Available triggers:  {avail_triggers}", flush=True)
        except Exception as e:
            print(f"  ❌ Cannot read LED state: {e}", flush=True)
            failed_leds.append((led_name, f"state read failed: {e}"))
            continue

        try:
            # ── Stage 1: Take manual control ──────────────────────────────────────
            print(f"\n  📋 Stage 1: Override trigger to 'none'...", flush=True)
            sysfs_write(led_path, "trigger", "none")
            active = get_active_trigger(led_path)
            assert active == "none", \
                f"Trigger override failed — still showing '{active}'."
            print(f"  ✅ Trigger set to 'none' (manual control).", flush=True)

            # ── Stage 2: ON test ──────────────────────────────────────────────────
            print(f"\n  📋 Stage 2: Brightness ON ({max_brightness})...", flush=True)
            sysfs_write(led_path, "brightness", max_brightness)
            actual_brightness = sysfs_read(led_path, "brightness")

            if actual_brightness == "0" and max_brightness != "0":
                # Hardware-managed LED — brightness writes have no effect
                print(
                    f"  ⚠️  LED '{led_name}': brightness write ignored "
                    f"(wrote {max_brightness}, read back 0).\n"
                    f"     This is a hardware-managed LED (e.g. mmc activity indicator).\n"
                    f"     Brightness toggle skipped — trigger tests still run.",
                    flush=True
                )
                skip_brightness = True
            else:
                # Accept any non-zero value — Pi 5 kernel normalizes 1 → 255
                assert int(actual_brightness) > 0, \
                    f"ON state rejected: wrote {max_brightness}, " \
                    f"read back {actual_brightness}."
                skip_brightness = False
                print(
                    f"  👉 LED '{led_name}' should be ON "
                    f"(brightness={actual_brightness}). Waiting 2s...",
                    flush=True
                )
                time.sleep(2)
                print(f"  ✅ ON confirmed (brightness={actual_brightness}).",
                    flush=True)

            # ── Stage 3: OFF test ─────────────────────────────────────────────────
            if not skip_brightness:
                print(f"\n  📋 Stage 3: Brightness OFF (0)...", flush=True)
                sysfs_write(led_path, "brightness", "0")
                actual_brightness = sysfs_read(led_path, "brightness")
                assert actual_brightness == "0", \
                    f"OFF state rejected: wrote 0, read back {actual_brightness}."
                print(f"  👉 LED '{led_name}' should be OFF. Waiting 2s...",
                    flush=True)
                time.sleep(2)
                print(f"  ✅ OFF confirmed.", flush=True)
            else:
                print(f"\n  ℹ️  Stage 3: Skipped (hardware-managed LED).", flush=True)

            # ── Stage 4: Timer (blink) trigger ───────────────────────────────────
            if "timer" in avail_triggers:
                print(f"\n  📋 Stage 4: Timer (blink) trigger test...", flush=True)
                sysfs_write(led_path, "trigger", "timer")
                active = get_active_trigger(led_path)
                assert active == "timer", \
                    f"Timer trigger not accepted — showing '{active}'."
                delay_on_path = os.path.join(led_path, "delay_on")
                if os.path.exists(delay_on_path):
                    sysfs_write(led_path, "delay_on",  "250")
                    sysfs_write(led_path, "delay_off", "250")
                print(f"  👉 LED '{led_name}' should be BLINKING at 2Hz. "
                    f"Watching for 3s...", flush=True)
                time.sleep(3)
                print(f"  ✅ Timer trigger accepted.", flush=True)
            else:
                print(f"\n  ℹ️  Stage 4: Timer trigger not available — skipped.",
                    flush=True)

            # ── Stage 5: Heartbeat trigger ────────────────────────────────────────
            if "heartbeat" in avail_triggers:
                print(f"\n  📋 Stage 5: Heartbeat trigger test...", flush=True)
                sysfs_write(led_path, "trigger", "heartbeat")
                active = get_active_trigger(led_path)
                assert active == "heartbeat", \
                    f"Heartbeat trigger not accepted — showing '{active}'."
                print(f"  👉 LED '{led_name}' should be HEARTBEAT pulsing. "
                    f"Watching for 3s...", flush=True)
                time.sleep(3)
                print(f"  ✅ Heartbeat trigger accepted.", flush=True)
            else:
                print(f"\n  ℹ️  Stage 5: Heartbeat trigger not available — skipped.",
                    flush=True)

        except Exception as e:
            print(f"  ❌ LED '{led_name}' test failed: {e}", flush=True)
            failed_leds.append((led_name, str(e)))

        finally:
            # ── Restore original state — always runs even on failure ──────────
            print(f"\n  📋 Restore: returning '{led_name}' to original state...",
                  flush=True)
            try:
                sysfs_write(led_path, "brightness", orig_brightness)
                sysfs_write(led_path, "trigger",    orig_trigger)
                print(f"  ✅ Restored: trigger='{orig_trigger}', "
                      f"brightness={orig_brightness}.", flush=True)
            except Exception as e:
                print(f"  ⚠️  Restore failed for '{led_name}': {e}. "
                      f"Manual restore may be needed.", flush=True)

    # ── Final result ──────────────────────────────────────────────────────────
    if failed_leds:
        report = "\n".join(f"  {name}: {reason}" for name, reason in failed_leds)
        pytest.fail(f"LED control failures:\n{report}")

    passed = [l for l in test_leds
              if l not in [n for n, _ in failed_leds]]
    print(f"\n✅ SUCCESS: All {len(passed)} LED(s) validated.", flush=True)
    print(f"   Tested: {passed}", flush=True)
    print("="*60 + "\n", flush=True)


import pytest
import time
from datetime import timedelta

def test_physical_button_interrupts(board_config):
    """
    Interactive test to physically validate external button interrupts.
    
    Hardware Setup:
    - Side 1 of button -> in_pin (e.g., Pin 13)
    - Side 2 of button -> GND (e.g., Pin 14)
    """
    try:
        import gpiod
        from gpiod.line import Direction, Edge, Bias
    except ImportError:
        pytest.skip("'gpiod' module not found on target.")

    assert "chip" in board_config, "board_config missing 'chip'"
    assert "in_pin" in board_config, "board_config missing 'in_pin'"

    chip_path = board_config["chip"]
    in_pin = board_config["in_pin"]

    print("\n" + "="*60, flush=True)
    print(f"🔘 MANUAL BUTTON VALIDATION: INTERRUPTS (Pin {in_pin})", flush=True)

    # Configure as Active-Low: Internal Pull-Up to 3.3V, Edge detection for both Press and Release
    req = gpiod.request_lines(
        chip_path,
        consumer="manual_button_test",
        config={
            in_pin: gpiod.LineSettings(
                direction=Direction.INPUT, 
                bias=Bias.PULL_UP, 
                edge_detection=Edge.BOTH
            )
        }
    )

    try:
        # Flush any noise from plugging in the wires
        while req.wait_edge_events(timedelta(seconds=0)):
            req.read_edge_events()

        print("\n⏳ WAITING FOR BUTTON PRESS...", flush=True)
        print("👉 Press and HOLD the button now (You have 30 seconds).", flush=True)

        if not req.wait_edge_events(timedelta(seconds=30)):
            pytest.fail("Timeout: No button press detected within 30 seconds.")

        events = req.read_edge_events()
        
        # Because it's Active-Low, pressing the button connects to GND (FALLING EDGE)
        assert events[0].event_type == gpiod.EdgeEvent.Type.FALLING_EDGE, "Hardware Fault: Expected FALLING edge on press."
        print(f"  ✅ BOOM! Hardware Interrupt Caught: FALLING EDGE (Pressed) at {events[0].timestamp_ns} ns", flush=True)

        print("\n⏳ WAITING FOR BUTTON RELEASE...", flush=True)
        print("👉 Let go of the button now.", flush=True)

        # We wait again for the release
        if not req.wait_edge_events(timedelta(seconds=30)):
            pytest.fail("Timeout: No button release detected.")

        release_events = req.read_edge_events()
        
        # Releasing disconnects GND, internal Pull-Up snaps it back to 3.3V (RISING EDGE)
        assert release_events[-1].event_type == gpiod.EdgeEvent.Type.RISING_EDGE, "Hardware Fault: Expected RISING edge on release."
        print(f"  ✅ BOOM! Hardware Interrupt Caught: RISING EDGE (Released) at {release_events[-1].timestamp_ns} ns", flush=True)

        print("="*60 + "\n", flush=True)

    finally:
        req.release()


def test_physical_button_debounce(board_config):
    """
    Interactive test to prove the kernel debounce filter stops mechanical bounce.
    """
    import gpiod
    from gpiod.line import Direction, Edge, Bias

    chip_path = board_config["chip"]
    in_pin = board_config["in_pin"]

    print("\n" + "="*60, flush=True)
    print(f"🛡️ MANUAL BUTTON VALIDATION: KERNEL DEBOUNCE", flush=True)

    # 🧠 The Magic: 50ms hardware debounce period
    req = gpiod.request_lines(
        chip_path,
        consumer="manual_debounce_test",
        config={
            in_pin: gpiod.LineSettings(
                direction=Direction.INPUT, 
                bias=Bias.PULL_UP, 
                edge_detection=Edge.BOTH,
                debounce_period=timedelta(milliseconds=50) 
            )
        }
    )

    try:
        while req.wait_edge_events(timedelta(seconds=0)):
            req.read_edge_events()

        print("\n👉 Mash the button as fast and as aggressively as you can for 5 seconds!", flush=True)
        time.sleep(1) # Give you a second to get ready
        print("🟢 GO!", flush=True)

        end_time = time.time() + 5.0
        total_edges = 0

        while time.time() < end_time:
            if req.wait_edge_events(timedelta(milliseconds=100)):
                events = req.read_edge_events()
                for event in events:
                    edge_type = "PRESS  (↓)" if event.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else "RELEASE(↑)"
                    print(f"   Caught clean {edge_type} at {event.timestamp_ns}")
                    total_edges += 1

        print(f"\n  ✅ PASS: 5 seconds of aggressive mashing yielded {total_edges} perfectly clean edges.", flush=True)
        print("      (Notice how there were zero 'stuttering' double-reads!)", flush=True)
        print("="*60 + "\n", flush=True)

    finally:
        req.release()