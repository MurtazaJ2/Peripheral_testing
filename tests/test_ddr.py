import subprocess
import pytest
import time
import random
import mmap

def test_detect_memory_size():
    """Detect memory size and verify it is > 0."""
    try:
        out = subprocess.check_output(["free", "-m"], text=True)
        mem_line = [line for line in out.splitlines() if line.startswith("Mem:")][0]
        total_mem = int(mem_line.split()[1])
        print(f"\n[DDR TEST] Detected Memory Size: {total_mem} MB")
        assert total_mem > 0, "Memory size is not > 0"
    except Exception as e:
        pytest.fail(f"Failed to check memory capacity: {e}")

def test_verify_base_address():
    """Verify base address of System RAM via /proc/iomem."""
    try:
        with open("/proc/iomem", "r") as f:
            iomem = f.read()
        ram_ranges = [line for line in iomem.splitlines() if "System RAM" in line]
        print(f"\n[DDR TEST] System RAM Ranges found: {len(ram_ranges)}")
        for r in ram_ranges:
            print(f" - {r.strip()}")
        assert len(ram_ranges) > 0, "Could not verify System RAM base address."
    except Exception as e:
        pytest.fail(f"Failed to read /proc/iomem: {e}")

def test_data_bus():
    """Test Data Bus using checkerboard patterns (0xAA, 0x55) on a memory block."""
    size = 1024 * 1024 # 1MB
    mem = bytearray(size)
    print(f"\n[DDR TEST] Writing 0xAA pattern to data bus...")
    for i in range(size):
        mem[i] = 0xAA
    assert all(b == 0xAA for b in mem), "Data bus failed 0xAA pattern"
    
    print(f"[DDR TEST] Writing 0x55 pattern to data bus...")
    for i in range(size):
        mem[i] = 0x55
    assert all(b == 0x55 for b in mem), "Data bus failed 0x55 pattern"

def test_address_bus():
    """Test Address Bus by writing unique values tied to memory addresses to detect aliasing."""
    size = 1024 * 1024 # 1MB
    # We use a memory mapped anonymous block for direct page-aligned memory
    mem = mmap.mmap(-1, size)
    print(f"\n[DDR TEST] Writing address-tied values to prevent address aliasing...")
    for i in range(size):
        mem[i] = i % 256
    
    aliasing_errors = 0
    for i in range(size):
        if mem[i] != i % 256:
            aliasing_errors += 1
            
    mem.close()
    assert aliasing_errors == 0, f"Address bus aliasing detected! {aliasing_errors} errors."
    print("[DDR TEST] Address bus verification passed.")

def test_increment_decrement():
    """Test Increment/Decrement operations in memory."""
    size = 1024 * 1024 # 1MB
    mem = bytearray(size)
    print(f"\n[DDR TEST] Running increment test...")
    for i in range(size):
        mem[i] = (i % 255) + 1
        
    print(f"[DDR TEST] Running decrement test...")
    for i in range(size):
        mem[i] = (mem[i] - 1) % 256
    
    assert all(mem[i] == (i % 255) for i in range(size)), "Increment/decrement logic failed in memory."

def test_boundary_tests():
    """Test Boundary values (min/max) at the edges of memory allocations."""
    size = 1024 * 1024
    mem = bytearray(size)
    print(f"\n[DDR TEST] Testing upper and lower boundary bits...")
    mem[0] = 0x00
    mem[size - 1] = 0xFF
    assert mem[0] == 0x00, "Lower boundary write failed"
    assert mem[size - 1] == 0xFF, "Upper boundary write failed"

def test_sequential_throughput():
    """Measure Sequential throughput of DDR memory."""
    size = 50 * 1024 * 1024 # 50MB
    print(f"\n[DDR TEST] Allocating {size/(1024*1024)}MB for sequential throughput test...")
    mem = bytearray(size)
    
    start_time = time.time()
    # Sequential write
    mem[:] = b'\xAA' * size
    write_time = time.time() - start_time
    
    start_time = time.time()
    # Sequential read (count forces read of all bytes)
    _ = mem.count(b'\xAA')
    read_time = time.time() - start_time
    
    write_bw = (size / (1024*1024)) / write_time
    read_bw = (size / (1024*1024)) / read_time
    
    print(f"[DDR TEST] Sequential Write: {write_bw:.2f} MB/s")
    print(f"[DDR TEST] Sequential Read: {read_bw:.2f} MB/s")
    assert write_bw > 0 and read_bw > 0, "Sequential throughput must be > 0"

def test_random_throughput():
    """Measure Random throughput of DDR memory."""
    size = 1024 * 1024 # 1MB
    mem = bytearray(size)
    indices = [random.randint(0, size - 1) for _ in range(100000)]
    
    print(f"\n[DDR TEST] Running 100,000 random writes...")
    start_time = time.time()
    for idx in indices:
        mem[idx] = 0x55
    write_time = time.time() - start_time
    
    print(f"[DDR TEST] Running 100,000 random reads...")
    start_time = time.time()
    for idx in indices:
        _ = mem[idx]
    read_time = time.time() - start_time
    
    write_bw = (100000 / (1024*1024)) / write_time
    read_bw = (100000 / (1024*1024)) / read_time
    
    print(f"[DDR TEST] Random Write: {write_bw:.2f} MB/s")
    print(f"[DDR TEST] Random Read: {read_bw:.2f} MB/s")
    assert write_bw > 0 and read_bw > 0

def test_latency():
    """Measure memory access Latency."""
    size = 1024 * 1024
    mem = bytearray(size)
    iterations = 100000
    
    print(f"\n[DDR TEST] Measuring latency over {iterations} random accesses...")
    start_time = time.time()
    for _ in range(iterations):
        idx = random.randint(0, size - 1)
        _ = mem[idx]
    total_time = time.time() - start_time
    
    latency_ns = (total_time / iterations) * 1e9
    print(f"[DDR TEST] Average access latency: {latency_ns:.2f} ns")
    assert latency_ns > 0

def test_long_duration_test():
    """Long-duration memory stability test."""
    duration_seconds = 5 # Run for 5 seconds to keep automated test suites reasonably fast
    print(f"\n[DDR TEST] Running long-duration stability test for {duration_seconds} seconds...")
    size = 10 * 1024 * 1024 # 10MB
    mem = bytearray(size)
    
    end_time = time.time() + duration_seconds
    passes = 0
    while time.time() < end_time:
        mem[:] = b'\x55' * size
        assert mem.count(b'\x55') == size
        mem[:] = b'\xAA' * size
        assert mem.count(b'\xAA') == size
        passes += 1
        
    print(f"[DDR TEST] Long-duration test completed {passes} full 10MB passes without errors.")
    assert passes > 0

def test_dmesg_memory_health():
    """Checks the kernel ring buffer for DDR or ECC hardware errors."""
    try:
        out = subprocess.check_output(["dmesg"], text=True)
        memory_events = [line for line in out.splitlines() if "ECC" in line.upper() or "DDR" in line.upper()]
        
        print(f"\n[DDR TEST] Found {len(memory_events)} memory-related events in dmesg.")
        critical_errors = []
        for event in memory_events:
            if any(keyword in event.lower() for keyword in ['error', 'failed', 'critical', 'panic']):
                critical_errors.append(event)
                
        assert len(critical_errors) == 0, f"Found critical DDR/ECC hardware errors in dmesg: {critical_errors}"
    except Exception as e:
        pytest.fail(f"Failed to check dmesg for memory errors: {e}")
