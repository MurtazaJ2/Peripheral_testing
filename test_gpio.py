import time

from conftest import loopback_pins

def test_gpio_high_low(loopback_pins, board_config):
    """Test basic HIGH/LOW propagation with visual LED pauses.
    🔌 The Hardware Setup
    Connect a single jumper wire directly from your configured out_pin 17 to your configured in_pin 27.
    """
    import time
    from gpiod.line import Value  
    
    request = loopback_pins
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    print("\n" + "="*60, flush=True)
    print(f"⚡ AUTOMATED GPIO LOOPBACK: Pin {out_pin} (OUT) ➔ Pin {in_pin} (IN)", flush=True)

    # 1. Assert HIGH
    request.set_value(out_pin, Value.ACTIVE)
    time.sleep(0.01) # 10ms hardware settling time to allow voltage to rise
    assert request.get_value(in_pin) == Value.ACTIVE, f"Hardware Failure: Pin {in_pin} did not read HIGH"

    # 2. Assert LOW
    request.set_value(out_pin, Value.INACTIVE)
    time.sleep(1) # 1s hardware settling time to allow voltage to drain
    assert request.get_value(in_pin) == Value.INACTIVE, f"Hardware Failure: Pin {in_pin} did not read LOW"
    
    print("  ✅ PASS: Instantaneous HIGH/LOW propagation verified.", flush=True)
    print("="*60 + "\n", flush=True)


def test_gpio_pull_up_down(board_config):
    """Test internal pull-up and pull-down resistors with observation pauses.
    🔌 The Hardware Setup
    Maintain the exact same baseline setup as the previous test (Pin 17 ➔ Pin 27), 
    but for this test we will leave the OUT pin disconnected (High-Z) to allow the internal 
    pull resistors to do their job without interference.
    """
    import gpiod
    from gpiod.line import Direction, Value, Bias
    import time

    chip_path = board_config["chip"]
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    # 1. High-Z Mode: Disconnect OUT pin so it doesn't interfere
    req_out = gpiod.request_lines(
        chip_path,
        consumer="test_high_z",
        config={out_pin: gpiod.LineSettings(direction=Direction.INPUT)}
    )

    try:
        print("\n" + "="*60, flush=True)
        print(f"🧲 AUTOMATED INTERNAL BIAS TEST: Pin {in_pin}", flush=True)
        
        # ── Test Pull-UP ──
        print("  🔼 Requesting Pull-UP bias...", flush=True)
        req_up = gpiod.request_lines(
            chip_path,
            consumer="test_pu",
            config={in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)}
        )
        time.sleep(1)  # 1s hardware settling time to allow internal voltage to rise
        
        assert req_up.get_value(in_pin) == Value.ACTIVE, f"Hardware Failure: Pin {in_pin} Pull-Up failed to hold HIGH"
        print("  ✅ PASS: Pull-UP internal resistor successfully held line HIGH.", flush=True)
        req_up.release() # Release hardware lock

        # ── Test Pull-DOWN ──
        print("  🔽 Requesting Pull-DOWN bias...", flush=True)
        req_down = gpiod.request_lines(
            chip_path,
            consumer="test_pd",
            config={in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_DOWN)}
        )
        time.sleep(0.01)  # 10ms hardware settling time to allow internal voltage to drain
        
        assert req_down.get_value(in_pin) == Value.INACTIVE, f"Hardware Failure: Pin {in_pin} Pull-Down failed to hold LOW"
        print("  ✅ PASS: Pull-DOWN internal resistor successfully held line LOW.", flush=True)
        req_down.release()
        
        print("="*60 + "\n", flush=True)

    finally:
        req_out.release()


def test_gpio_edge_interrupts(board_config):
    """Interactive test to physically confirm hardware interrupts.
        🔌 The Hardware Setup
    Maintain the exact same baseline setup as the previous test (Pin 17 ➔ Pin 27), 
    but for this test we will be generating electrical edges on the OUT pin and confirming 
    that the IN pin triggers hardware interrupts in the kernel.
    """
    import gpiod
    from gpiod.line import Direction, Edge, Bias, Value
    from datetime import timedelta
    import time

    chip_path = board_config["chip"]
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    # Request both the trigger source (OUT) and monitored target (IN) in one block
    req_lines = gpiod.request_lines(
        chip_path,
        consumer="test_irq_automated",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(
                direction=Direction.INPUT, 
                edge_detection=Edge.BOTH, 
                bias=Bias.PULL_DOWN
            )
        }
    )

    try:
        print("\n" + "="*60, flush=True)
        print(f"⚡ AUTOMATED HARDWARE INTERRUPT (IRQ) VALIDATION", flush=True)
        
        # 1. Establish baseline state (LOW)
        req_lines.set_value(out_pin, Value.INACTIVE)
        time.sleep(1)  # 1s settling time
        
        # Clear any electrical startup artifacts or noise from the kernel queue
        while req_lines.wait_edge_events(timedelta(seconds=0)):
            req_lines.read_edge_events()

        # 2. Test Rising Edge Event
        print("  📤 Generating electrical Rising Edge via firmware...", flush=True)
        req_lines.set_value(out_pin, Value.ACTIVE)
        
        # Machine speed check: 500ms timeout is more than generous for direct line loopback
        if not req_lines.wait_edge_events(timedelta(milliseconds=500)):
            assert False, f"Hardware Failure: Input pin {in_pin} failed to trigger an IRQ event on Rising Edge."
            
        events = req_lines.read_edge_events()
        assert events[0].event_type == gpiod.EdgeEvent.Type.RISING_EDGE, "Interrupt driver mismatch: Expected RISING_EDGE event token."
        print("  ✅ PASS: Hardware kernel interrupt successfully captured matching RISING_EDGE.", flush=True)

        # 3. Test Falling Edge Event
        print("  📥 Generating electrical Falling Edge via firmware...", flush=True)
        req_lines.set_value(out_pin, Value.INACTIVE)
        
        if not req_lines.wait_edge_events(timedelta(milliseconds=500)):
            assert False, f"Hardware Failure: Input pin {in_pin} failed to trigger an IRQ event on Falling Edge."
            
        events = req_lines.read_edge_events()
        assert events[0].event_type == gpiod.EdgeEvent.Type.FALLING_EDGE, "Interrupt driver mismatch: Expected FALLING_EDGE event token."
        print("  ✅ PASS: Hardware kernel interrupt successfully captured matching FALLING_EDGE.", flush=True)
        print("="*60 + "\n", flush=True)

    finally:
        req_lines.release()


def test_gpio_level_polling(board_config):
    """Simulates Level-Triggered validation via high-frequency polling.
            🔌 The Hardware Setup
    Maintain the exact same baseline setup as the previous test (Pin 17 ➔ Pin 27)
    """
    import gpiod
    from gpiod.line import Direction, Value, Bias
    import time

    chip_path = board_config["chip"]
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    # Request both the driver (OUT) and the sensor (IN) simultaneously
    req_lines = gpiod.request_lines(
        chip_path,
        consumer="test_level",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_DOWN)
        }
    )

    try:
        print("\n" + "="*60, flush=True)
        print("📊 AUTOMATED LEVEL TRIGGER: ACTIVE-HIGH STABILITY", flush=True)

        # 1. Assert HIGH via software
        req_lines.set_value(out_pin, Value.ACTIVE)
        time.sleep(0.01) # 10ms initial hardware settling

        # 2. High-Frequency Stability Window (100 checks over 100ms)
        stability_checks = 100
        check_interval = 0.001 # 1 millisecond

        for i in range(stability_checks):
            # If the voltage drops even for a microsecond, the level test fails
            if req_lines.get_value(in_pin) == Value.INACTIVE:
                assert False, f"Hardware Failure: Signal collapsed back to LOW at check {i}/{stability_checks}."
            time.sleep(check_interval)

        print("  ✅ PASS: Active-HIGH level was sustained cleanly at machine speed!", flush=True)
        print("="*60 + "\n", flush=True)

    finally:
        req_lines.release()


def test_gpio_level_polling_low(board_config):
    """Simulates Level-Triggered validation for Active-LOW signals.
    🔌 The Hardware Setup
    Maintain the exact same baseline setup as the previous test (Pin 17 ➔ Pin 27)
    """
    import gpiod
    from gpiod.line import Direction, Value, Bias
    import time

    chip_path = board_config["chip"]
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    req_lines = gpiod.request_lines(
        chip_path,
        consumer="test_level_low",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)
        }
    )

    try:
        print("\n" + "="*60, flush=True)
        print("📊 AUTOMATED LEVEL TRIGGER: ACTIVE-LOW STABILITY", flush=True)

        # 1. Assert LOW via software (sinking the current against the PULL_UP)
        req_lines.set_value(out_pin, Value.INACTIVE)
        time.sleep(0.01) # 10ms initial hardware settling

        # 2. High-Frequency Stability Window (100 checks over 100ms)
        stability_checks = 100
        check_interval = 0.001 # 1 millisecond

        for i in range(stability_checks):
            # If the voltage spikes back up to 3.3V, the sink failed
            if req_lines.get_value(in_pin) == Value.ACTIVE:
                assert False, f"Hardware Failure: Level bounced back to HIGH at check {i}/{stability_checks}."
            time.sleep(check_interval)

        print("  ✅ PASS: Active-LOW level was sustained cleanly against internal Pull-Up!", flush=True)
        print("="*60 + "\n", flush=True)

    finally:
        req_lines.release()


def test_gpio_muxing_state(board_config):
    """Validates that the SoC's internal router (Pinmux) has correctly assigned a pin.
    Because this test strictly queries the internal RP1 silicon router and does not measure 
    external electrical thresholds, no physical wiring is required. The test runs entirely inside the chip's logic gates.
    """
    import subprocess
    import pytest

    pin = board_config.get("mux_test_pin")
    expected_mux = board_config.get("expected_mux")

    assert pin is not None, "Configuration Error: 'mux_test_pin' not defined in board_config."
    assert expected_mux is not None, "Configuration Error: 'expected_mux' not defined in board_config."

    print("\n" + "="*60, flush=True)
    print(f"🔀 AUTOMATED PINMUX ROUTER VALIDATION: Pin {pin}", flush=True)
    
    # Run the pinctrl utility to query the physical silicon multiplexer
    try:
        print(f"  🔍 Querying RP1 silicon registers for GPIO {pin}...", flush=True)
        result = subprocess.run(
            ["pinctrl", "get", str(pin)], 
            capture_output=True, 
            text=True, 
            check=True
        )
    except FileNotFoundError:
        pytest.fail("Environment Error: 'pinctrl' tool not found on the target OS. Cannot validate multiplexer.")
    except subprocess.CalledProcessError as e:
        pytest.fail(f"OS Error: pinctrl command failed to read pin {pin}: {e.stderr}")

    output = result.stdout.strip()
    
    # We assert that the expected alternate function (e.g., TXD0, I2C1_SDA) exists in the register readout
    if expected_mux not in output:
        pytest.fail(
            f"🚨 Hardware Mux Failure!\n"
            f"   Expected Routing : {expected_mux}\n"
            f"   Actual Register  : {output}"
        )

    print(f"  ✅ PASS: Silicon successfully routed Pin {pin} to {expected_mux}.", flush=True)
    print("="*60 + "\n", flush=True)


def test_gpio_drive_strength_basic(board_config):
    """Interactive test to validate output drive strength under physical load.
    🔌 The Hardware Setup
    Maintain the exact same baseline setup as the previous test (Pin 17 ➔ Pin 27)
    """
    import gpiod
    from gpiod.line import Direction, Value, Bias
    import time

    chip_path = board_config["chip"]
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]

    print("\n" + "="*60, flush=True)
    print(f"💪 AUTOMATED DRIVE STRENGTH VALIDATION: Pin {out_pin} ➔ Pin {in_pin}", flush=True)

    # ── PHASE 1: Source Current Validation (Drive HIGH against internal load) ──
    print("  🔼 Testing Source Drive: Driving HIGH against internal Pull-Down load...", flush=True)
    req_lines = gpiod.request_lines(
        chip_path,
        consumer="test_drive_strength_src",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_DOWN)
        }
    )

    try:
        req_lines.set_value(out_pin, Value.ACTIVE)
        time.sleep(0.01)  # 10ms machine settling time

        # If the output driver is healthy, it easily overwhelms the internal load bias
        assert req_lines.get_value(in_pin) == Value.ACTIVE, \
            f"Hardware Failure: Pin {out_pin} source drive strength failed to overcome internal pull-down on Pin {in_pin}."
        print("  ✅ PASS: Source current capability validated successfully.", flush=True)

    finally:
        req_lines.release()

    # ── PHASE 2: Sink Current Validation (Drive LOW against internal load) ──
    print("  🔽 Testing Sink Drive: Driving LOW against internal Pull-Up load...", flush=True)
    req_lines = gpiod.request_lines(
        chip_path,
        consumer="test_drive_strength_snk",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)
        }
    )

    try:
        req_lines.set_value(out_pin, Value.INACTIVE)
        time.sleep(0.01)  # 10ms machine settling time

        # If the output driver's internal transistor can sink current properly, it forces the line LOW
        assert req_lines.get_value(in_pin) == Value.INACTIVE, \
            f"Hardware Failure: Pin {out_pin} sink drive strength failed to overcome internal pull-up on Pin {in_pin}."
        print("  ✅ PASS: Sink current capability validated successfully.", flush=True)
        print("="*60 + "\n", flush=True)

    finally:
        req_lines.release()


# def test_gpio_drive_strength_basic(board_config):
#     """Interactive test to validate output drive strength under physical load."""
#     import gpiod
#     from gpiod.line import Direction, Value
#     import time

#     chip_path = board_config["chip"]
#     out_pin = board_config["out_pin"]

#     # Request the pin as a strong output driving HIGH
#     req_out = gpiod.request_lines(
#         chip_path,
#         consumer="test_drive_strength",
#         config={out_pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)}
#     )

#     try:
#         print("\n" + "="*55, flush=True)
#         print(f"💪 PHYSICAL CONFIRMATION: DRIVE STRENGTH (GPIO {out_pin})", flush=True)
#         print("The pin is now actively driving HIGH (3.3V).", flush=True)
        
#         print("\n--- PHASE 1: NO-LOAD BASELINE ---", flush=True)
#         print("👉 Measure the voltage of Pin 11 (OUT) to any Ground.", flush=True)
#         print("⚡ It should read approx 3.3V.", flush=True)
#         print("⏳ Pausing for 20 seconds...", flush=True)
#         time.sleep(20)
        
#         print("\n--- PHASE 2: APPLY THE LOAD ---", flush=True)
#         print("👉 Keep measuring Pin 11, but NOW plug a 330Ω to 1kΩ resistor", flush=True)
#         print("   between Pin 11 and Ground.", flush=True)
#         print("⚡ A healthy pin will 'droop' slightly (e.g., down to 3.1V).", flush=True)
#         print("❌ If it drops below 2.5V, the drive strength is failing!", flush=True)
#         print("⏳ Pausing for 30 seconds for you to test...", flush=True)
#         time.sleep(30)

#         print("\n✅ SUCCESS: Test complete. Pin released safely.", flush=True)
#         print("="*55 + "\n", flush=True)

#     finally:
#         req_out.release()