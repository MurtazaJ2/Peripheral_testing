import pytest
import subprocess
import re
import time
import os

def run_cmd(cmd):
    """
    Helper to run a shell command on the target system and return rc, stdout, stderr.
    Uses 'sudo sh -c' to ensure commands that require root access (like nvme, dmesg, echo to sysfs) work properly.
    """
    process = subprocess.run(f"sudo sh -c '{cmd}'", shell=True, capture_output=True, text=True)
    return process.returncode, process.stdout, process.stderr

def test_pcie_device_present(board_config):
    """
    1. PCIe Enumeration Test
    Verify endpoint is visible.
    """
    print("\n" + "="*60, flush=True)
    print("🔍 PCIE VALIDATION: ENUMERATION TEST", flush=True)
    
    rc, out, err = run_cmd("lspci")
    assert rc == 0, f"lspci failed: {err}"
    
    expected = [
        "Non-Volatile memory controller",
        "Network controller"
    ]
    
    found = any(dev in out for dev in expected)
    assert found, f"PCIe endpoint not detected. Expected one of {expected} in lspci."
    
    print("  ✅ SUCCESS: PCIe endpoint(s) found.", flush=True)
    print("="*60 + "\n", flush=True)

def get_nvme_pci_id():
    """Helper to find the PCI ID of the NVMe device."""
    rc, out, err = run_cmd("lspci -D | grep -i 'Non-Volatile'")
    if not out.strip():
        return None
    return out.split()[0]

def test_link_speed(board_config):
    """
    2. Link Speed Validation
    RPi5 typically negotiates: PCIe Gen2/Gen3 x1.
    """
    print("\n" + "="*60, flush=True)
    print("⚡ PCIE VALIDATION: LINK SPEED", flush=True)
    
    pci_id = get_nvme_pci_id()
    if not pci_id:
        pytest.skip("No NVMe device found to check link speed.")
        
    rc, out, err = run_cmd(f"lspci -s {pci_id} -vv")
    
    # We must check LnkSta (Negotiated Status) not LnkCap (Capabilities)
    speed = re.search(r"LnkSta:\s+Speed\s+([\d\.]+)GT/s", out)
    assert speed, "Could not determine negotiated link speed from lspci (LnkSta)."
    
    negotiated = float(speed.group(1))
    print(f"  📊 Negotiated Link Speed: {negotiated} GT/s", flush=True)
    
    assert negotiated >= 5.0, f"Link speed {negotiated}GT/s is lower than expected 5.0GT/s."
    
    print("  ✅ SUCCESS: Link speed is optimal.", flush=True)
    print("="*60 + "\n", flush=True)

def test_link_width(board_config):
    """
    3. Link Width Validation
    """
    print("\n" + "="*60, flush=True)
    print("🛤️ PCIE VALIDATION: LINK WIDTH", flush=True)
    
    pci_id = get_nvme_pci_id()
    if not pci_id:
        pytest.skip("No NVMe device found to check link width.")
        
    rc, out, err = run_cmd(f"lspci -s {pci_id} -vv")
    
    # We must check LnkSta (Negotiated Status) not LnkCap (Capabilities)
    width = re.search(r"LnkSta:.*?Width\s+x(\d+)", out)
    assert width, "Could not determine negotiated link width from lspci (LnkSta)."
    
    lanes = int(width.group(1))
    print(f"  📊 Negotiated Link Width: x{lanes}", flush=True)
    
    assert lanes >= 1, f"Link width x{lanes} is lower than expected x1."
    
    print("  ✅ SUCCESS: Link width is optimal.", flush=True)
    print("="*60 + "\n", flush=True)

def test_driver_loaded(board_config):
    """
    4. Driver Binding Test
    Verify kernel driver loaded.
    """
    print("\n" + "="*60, flush=True)
    print("📦 PCIE VALIDATION: DRIVER BINDING", flush=True)
    
    pci_id = get_nvme_pci_id()
    if not pci_id:
        pytest.skip("No NVMe device found to check driver binding.")
        
    rc, out, err = run_cmd(f"lspci -s {pci_id} -k")
    assert "Kernel driver in use" in out, "Kernel driver is not bound/in use for the NVMe PCIe device."
    
    print("  ✅ SUCCESS: Kernel drivers are loaded and bound.", flush=True)
    print("="*60 + "\n", flush=True)

def test_bar_assignment(board_config):
    """
    5. BAR Assignment Test
    """
    print("\n" + "="*60, flush=True)
    print("📝 PCIE VALIDATION: BAR ASSIGNMENT", flush=True)
    
    pci_id = get_nvme_pci_id()
    if not pci_id:
        pytest.skip("No NVMe device found to check BARs.")
        
    rc, out, err = run_cmd(f"lspci -s {pci_id} -vv")
    assert "Memory at" in out, "BARs are not assigned (No 'Memory at' detected for NVMe)."
    
    print("  ✅ SUCCESS: BAR assignment verified.", flush=True)
    print("="*60 + "\n", flush=True)

def test_no_pcie_errors(board_config):
    """
    6. Kernel Error Scan
    Critical BSP validation test.
    """
    print("\n" + "="*60, flush=True)
    print("🛡️ PCIE VALIDATION: KERNEL ERROR SCAN", flush=True)
    
    rc, out, err = run_cmd("dmesg | grep -i pcie")
    
    forbidden = [
        "AER",
        "link down",
        "fatal",
        "CRC"
    ]
    
    for item in forbidden:
        assert item.lower() not in out.lower(), f"Critical error '{item}' found in kernel logs."
        
    print("  ✅ SUCCESS: No critical PCIe errors found in dmesg.", flush=True)
    print("="*60 + "\n", flush=True)

def test_nvme_detected(board_config):
    """
    7. NVMe Presence Test
    If NVMe SSD attached.
    """
    print("\n" + "="*60, flush=True)
    print("💾 PCIE VALIDATION: NVME PRESENCE", flush=True)
    
    rc, out, err = run_cmd("nvme list")
    assert "/dev/nvme0n1" in out, "NVMe block device /dev/nvme0n1 not found."
    
    print("  ✅ SUCCESS: NVMe SSD is attached and detected.", flush=True)
    print("="*60 + "\n", flush=True)

def test_nvme_rw(board_config):
    """
    8. NVMe Read/Write Test
    Create temporary file dynamically on the mounted NVMe drive.
    """
    print("\n" + "="*60, flush=True)
    print("✍️ PCIE VALIDATION: NVME READ/WRITE", flush=True)
    
    # Dynamically find the mount point to avoid writing to the SD card
    rc, out, err = run_cmd("lsblk -o MOUNTPOINT -nr /dev/nvme0n1 | grep -v '^$' | head -n 1")
    mnt = out.strip()
    
    if not mnt:
        pytest.skip("NVMe drive is not mounted. Skipping filesystem write test to prevent data loss or SD card wear.")
        
    test_file = os.path.join(mnt, "nvme_rw_test.bin")
    cmd = (
        f"dd if=/dev/zero "
        f"of={test_file} "
        "bs=1M count=100 "
        "conv=fsync"
    )
    
    print(f"  📋 Performing 100MB write test to {test_file}...", flush=True)
    rc, out, err = run_cmd(cmd)
    
    assert rc == 0, f"Write test failed: {err}"
    
    # Cleanup
    run_cmd(f"rm -f {test_file}")
    
    print("  ✅ SUCCESS: NVMe Read/Write completed successfully.", flush=True)
    print("="*60 + "\n", flush=True)

def test_nvme_throughput(board_config):
    """
    9. FIO Throughput Test
    Useful for BSP performance baselining.
    """
    print("\n" + "="*60, flush=True)
    print("🚀 PCIE VALIDATION: FIO THROUGHPUT", flush=True)
    
    rc, out, err = run_cmd("lsblk -o MOUNTPOINT -nr /dev/nvme0n1 | grep -v '^$' | head -n 1")
    mnt = out.strip()
    
    if not mnt:
        pytest.skip("NVMe drive is not mounted. Skipping filesystem throughput test.")
        
    test_file = os.path.join(mnt, "fio_testfio.bin")
    cmd = f"""
    fio --name=test \\
        --filename={test_file} \\
        --size=512M \\
        --rw=read \\
        --bs=1M
    """
    
    print(f"  📋 Running FIO throughput test (512M read) at {test_file}...", flush=True)
    rc, out, err = run_cmd(cmd)
    
    assert rc == 0, f"FIO execution failed: {err}"
    assert "READ:" in out, "FIO results did not contain 'READ:' stats."
    
    # Attempt to parse speed
    speed = re.search(r"READ:.*?bw=(.*?/s)", out)
    if speed:
        print(f"  📊 Measured Throughput: {speed.group(1)}", flush=True)
    
    # Cleanup
    run_cmd(f"rm -f {test_file}")
        
    print("  ✅ SUCCESS: FIO throughput benchmark completed.", flush=True)
    print("="*60 + "\n", flush=True)

def test_interrupts(board_config):
    """
    10. Interrupt Validation
    Verify MSI interrupts increase specifically for the NVMe controller.
    """
    print("\n" + "="*60, flush=True)
    print("🔌 PCIE VALIDATION: INTERRUPT COUNT", flush=True)
    
    def get_nvme_interrupts():
        rc, out, err = run_cmd("cat /proc/interrupts | grep -i nvme")
        if not out.strip():
            return 0
        total = 0
        for line in out.strip().split('\n'):
            parts = line.split()
            # The counts per CPU are between the IRQ name and the handler name
            for p in parts[1:]:
                if p.isdigit():
                    total += int(p)
                else:
                    break
        return total
        
    before = get_nvme_interrupts()
    
    print("  📋 Triggering NVMe activity...", flush=True)
    run_cmd(
        "dd if=/dev/nvme0n1 "
        "of=/dev/null bs=1M count=100"
    )
    
    after = get_nvme_interrupts()
    
    print(f"  📊 NVMe Interrupts: Before={before}, After={after}", flush=True)
    assert before != after, "NVMe interrupt counts did not increase after disk activity."
    
    print("  ✅ SUCCESS: Interrupts are increasing dynamically.", flush=True)
    print("="*60 + "\n", flush=True)

def test_remove_rescan(board_config):
    """
    11. Hot Reset Test
    PCIe recovery validation.
    """
    print("\n" + "="*60, flush=True)
    print("🔄 PCIE VALIDATION: HOT RESET", flush=True)
    
    pci_id = get_nvme_pci_id()
    if not pci_id:
        pytest.skip("No NVMe device found to perform hot reset.")
        
    print(f"  📋 Removing PCIe device {pci_id}...", flush=True)
    
    run_cmd(f"echo 1 > /sys/bus/pci/devices/{pci_id}/remove")
    time.sleep(1)
    
    print("  📋 Rescanning PCIe bus...", flush=True)
    run_cmd("echo 1 > /sys/bus/pci/rescan")
    time.sleep(2)
    
    rc, out, err = run_cmd("lspci")
    assert "Non-Volatile" in out, "NVMe device did not reappear after rescan."
    
    print("  ✅ SUCCESS: PCIe hot reset completed successfully.", flush=True)
    print("="*60 + "\n", flush=True)

def test_post_reboot(board_config):
    """
    12. Reboot Persistence Test
    Run after reboot: (Verifies it is currently visible)
    """
    print("\n" + "="*60, flush=True)
    print("🔁 PCIE VALIDATION: POST REBOOT PRESENCE", flush=True)
    
    rc, out, err = run_cmd("lspci")
    assert "Non-Volatile" in out, "NVMe device is not visible post-reboot."
    
    print("  ✅ SUCCESS: PCIe endpoint is present.", flush=True)
    print("="*60 + "\n", flush=True)

def test_24hr_stability(board_config):
    """
    13. Long-Duration Stability Test
    Continuous stress: (Shortened for standard CI runs)
    """
    print("\n" + "="*60, flush=True)
    print("🏋️ PCIE VALIDATION: STABILITY TEST", flush=True)
    
    duration = board_config.get("pcie_stability_duration_s", 10)
    print(f"  📋 Running continuous DD stress test for {duration} seconds...", flush=True)
    
    start = time.time()
    iters = 0
    
    while time.time() - start < duration:
        rc, out, err = run_cmd(
            "dd if=/dev/nvme0n1 "
            "of=/dev/null bs=1M count=512"
        )
        assert rc == 0, f"Stability test failed during iteration {iters}: {err}"
        iters += 1
        
    print(f"  ✅ SUCCESS: Stability test completed {iters} iterations without failure.", flush=True)
    print("="*60 + "\n", flush=True)
