import subprocess
import pytest

def test_memory_capacity():
    """Validates that system memory is accessible and reports a total capacity > 0 MB."""
    try:
        out = subprocess.check_output(["free", "-m"], text=True)
        print("\\n[DDR TEST LOG] System Memory (free -m):")
        print(out.strip())
        # Parse the 'Mem:' line
        mem_line = [line for line in out.splitlines() if line.startswith("Mem:")][0]
        total_mem = int(mem_line.split()[1])
        assert total_mem > 0, f"Reported total memory is {total_mem} MB, expected > 0 MB"
    except Exception as e:
        pytest.fail(f"Failed to check memory capacity: {e}")

def test_memory_health():
    """Checks the kernel ring buffer for DDR or ECC hardware errors."""
    try:
        out = subprocess.check_output(["dmesg"], text=True)
        # Scan for memory related events
        memory_events = [line for line in out.splitlines() if "ECC" in line.upper() or "DDR" in line.upper()]
        
        print(f"\\n[DDR TEST LOG] Found {len(memory_events)} memory-related events in dmesg.")
        if memory_events:
            print("--- Memory Events (Top 10) ---")
            for event in memory_events[:10]:
                print(event)
            print("------------------------------")
            
        # Filter for actual errors or failures
        critical_errors = []
        for event in memory_events:
            if any(keyword in event.lower() for keyword in ['error', 'failed', 'critical', 'panic']):
                critical_errors.append(event)
                
        assert len(critical_errors) == 0, f"Found critical DDR/ECC hardware errors in dmesg: {critical_errors}"
    except Exception as e:
        pytest.fail(f"Failed to check dmesg for memory errors: {e}")

def test_proc_meminfo():
    """Validates that detailed kernel memory statistics are available via /proc/meminfo."""
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
            
        print("\\n[DDR TEST LOG] /proc/meminfo Statistics:")
        for line in meminfo.splitlines()[:5]:
            print(line)
            
        assert "MemTotal:" in meminfo, "MemTotal not found in /proc/meminfo"
        assert "MemFree:" in meminfo, "MemFree not found in /proc/meminfo"
        assert "MemAvailable:" in meminfo, "MemAvailable not found in /proc/meminfo"
    except Exception as e:
        pytest.fail(f"Failed to read /proc/meminfo: {e}")

def test_oom_killer_logs():
    """Checks the kernel ring buffer to ensure the Out-Of-Memory (OOM) killer has not been invoked."""
    try:
        out = subprocess.check_output(["dmesg"], text=True)
        oom_events = [line for line in out.splitlines() if "Out of memory" in line or "Killed process" in line]
        
        print(f"\\n[DDR TEST LOG] OOM Killer checks complete. Found {len(oom_events)} OOM invocations.")
        if oom_events:
            for event in oom_events:
                print(event)
                
        assert len(oom_events) == 0, f"OOM Killer was invoked, indicating potential memory exhaustion: {oom_events}"
    except Exception as e:
        pytest.fail(f"Failed to check dmesg for OOM logs: {e}")
