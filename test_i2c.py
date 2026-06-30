import os
import subprocess
import re
import pytest

def test_i2c_bus_detection(board_config):
    """
    Validates that the target I2C bus is enabled and recognized by the OS.
    
    Hardware Setup: 
    No external wiring required. This strictly validates the internal 
    SoC I2C controller configuration and Linux device tree.
    """
    bus_num = board_config.get("i2c_bus", 1)
    bus_path = f"/dev/i2c-{bus_num}"

    print("\n" + "="*60, flush=True)
    print(f"🔍 AUTOMATED I2C BUS DETECTION: (Bus {bus_num})", flush=True)

    # 1. OS-Level Device Check
    if not os.path.exists(bus_path):
        pytest.fail(f"Hardware Failure: {bus_path} not found. Is I2C enabled in raspi-config?")
    
    print(f"  ✅ Kernel device recognized: {bus_path}", flush=True)

    # 2. Driver-Level Subsystem Check
    try:
        result = subprocess.run(
                ["/usr/sbin/i2cdetect", "-l"], 
                capture_output=True, 
                text=True, 
                check=True
            )
        output = result.stdout.strip()
        
        # Assert that our specific bus is listed in the hardware map
        if f"i2c-{bus_num}" not in output:
            pytest.fail(f"Driver Error: i2cdetect did not report i2c-{bus_num}.")
            
    except FileNotFoundError:
        pytest.fail("Environment Error: 'i2c-tools' is not installed on the target Pi.")

    print(f"  ✅ SUCCESS: I2C Bus {bus_num} is actively routed and ready for devices!", flush=True)
    print("="*60 + "\n", flush=True)


@pytest.fixture(scope="function")
def virtual_i2c_environment(board_config):
    """
    Dynamically creates a virtual I2C bus via the Linux kernel, 
    yields it to the test, and securely tears it down afterwards.
    
    Hardware Setup:
    Purely Software-In-the-Loop (SIL). No physical hardware required.
    """
    print("\n" + "-"*60, flush=True)
    print("[SETUP] 🛠️ Provisioning Virtual Silicon in RAM...", flush=True)
    
    virtual_devices = ["0x27", "0x68"]
    
    # Forcefully remove any existing stub in the kernel before we start
    subprocess.run(["sudo", "modprobe", "-r", "i2c-stub"], check=False, stderr=subprocess.DEVNULL)

    # 1. Tell the Linux Kernel to hallucinate an I2C bus
    subprocess.run(["sudo", "modprobe", "i2c-stub", "chip_addr=0x27,0x68"], check=True)
    
    # 2. Query the OS to find out what Bus Number it assigned to the stub
    result = subprocess.run(["/usr/sbin/i2cdetect", "-l"], capture_output=True, text=True)
    
    stub_bus = None
    for line in result.stdout.splitlines():
        if "SMBus stub driver" in line:
            match = re.search(r'i2c-(\d+)', line)
            if match:
                stub_bus = int(match.group(1))
                break
                
    if stub_bus is None:
        subprocess.run(["sudo", "modprobe", "-r", "i2c-stub"], check=False)
        pytest.fail("Automation Failure: Kernel did not create the i2c-stub.")
        
    print(f"[SETUP] ✅ Virtual Bus Online and Mapped to: i2c-{stub_bus}", flush=True)
    
    original_bus = board_config.get("i2c_bus")
    original_devices = board_config.get("expected_i2c_devices")
    
    board_config["i2c_bus"] = stub_bus
    board_config["expected_i2c_devices"] = virtual_devices
    
    yield board_config
    
    print("\n[TEARDOWN] 🧹 Destroying Virtual Bus...", flush=True)
    subprocess.run(["sudo", "modprobe", "-r", "i2c-stub"], check=False)
    
    board_config["i2c_bus"] = original_bus
    board_config["expected_i2c_devices"] = original_devices
    print("[TEARDOWN] ✅ Environment restored to physical state.", flush=True)
    print("-" * 60, flush=True)


def test_i2c_virtual_device_scan(virtual_i2c_environment):
    """
    Tests the parsing logic against an automated Software-In-Loop (SIL) environment.
    
    Hardware Setup:
    Dynamically handled by the virtual_i2c_environment fixture.
    """
    board_config = virtual_i2c_environment
    bus_num = board_config.get("i2c_bus")
    expected_devices = board_config.get("expected_i2c_devices")

    print("\n" + "="*60, flush=True)
    print(f"📡 SOFTWARE-IN-LOOP: I2C DEVICE SCAN (Virtual Bus {bus_num})", flush=True)

    try:
        result = subprocess.run(
            ["sudo", "/usr/sbin/i2cdetect", "-y", str(bus_num)], 
            capture_output=True, 
            text=True, 
            check=True
        )
    except subprocess.CalledProcessError:
        pytest.fail(f"Framework Error: Could not ping Virtual Bus {bus_num}.")

    output = result.stdout
    active_addresses = []
    for line in output.split('\n')[1:]:
        if ':' in line:
            cells = line.split(':')[1].strip().split()
            for cell in cells:
                if cell not in ('--', 'UU') and re.match(r'^[0-9a-f]{2}$', cell):
                    active_addresses.append(f"0x{cell}")

    print(f"  🔍 Virtual Devices responding: {active_addresses}", flush=True)

    missing_devices = [exp for exp in expected_devices if exp.lower() not in active_addresses]
    assert not missing_devices, f"SIL Mismatch: Expected {missing_devices} but they did not respond!"

    print(f"  ✅ SUCCESS: All virtual devices ({expected_devices}) detected properly!", flush=True)
    print("="*60 + "\n", flush=True)


def test_i2c_nack_error_handling(board_config):
    """
    Validates that addressing a non-existent device properly catches a NACK.
    
    Hardware Setup: 
    Ensure no physical I2C device is connected to address 0x77 on the 
    target physical bus. The test requires an empty address slot to generate 
    a hardware NACK (Not Acknowledge) signal.
    """
    bus_num = board_config.get("i2c_bus", 1)
    missing_address = "0x77" 

    print("\n" + "="*60, flush=True)
    print(f"🛑 AUTOMATED I2C NACK HANDLING: (Bus {bus_num}, Address {missing_address})", flush=True)

    try:
        subprocess.run(
            ["/usr/sbin/i2cget", "-y", str(bus_num), missing_address], 
            capture_output=True, 
            text=True, 
            check=True
        )
        # If this succeeds, the test FAILS because it was supposed to NACK!
        pytest.fail(f"Hardware Fault: A ghost device responded at {missing_address}! (Expected a NACK)")

    except subprocess.CalledProcessError as e:
        error_output = e.stderr.strip()
        
        if "Error: Read failed" in error_output or "Error:" in error_output:
            print(f"  ✅ SUCCESS: Framework successfully caught the hardware NACK at {missing_address}.", flush=True)
        else:
            pytest.fail(f"Unexpected error format during NACK: {error_output}")
            
    print("="*60 + "\n", flush=True)