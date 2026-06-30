import pytest
import time
import subprocess
import os
import threading
from datetime import datetime

def test_timer_jitter(board_config):
    """
    Validates the hardware/OS timer precision by checking for sleep jitter.
    Expects standard 10ms sleeps to complete within an acceptable margin.
    """
    print("\n" + "="*60, flush=True)
    print("⏱️ TIMER VALIDATION: JITTER TEST", flush=True)

    target_sleep = board_config.get("timer_jitter_target_sleep", 0.01)
    iterations = board_config.get("timer_jitter_iterations", 100)
    acceptable_jitter_max = board_config.get("timer_acceptable_jitter_max", 0.005)

    differences = []

    for i in range(iterations):
        start = time.perf_counter()
        time.sleep(target_sleep)
        end = time.perf_counter()
        
        actual_sleep = end - start
        jitter = abs(actual_sleep - target_sleep)
        differences.append(jitter)

    max_jitter = max(differences)
    avg_jitter = sum(differences) / len(differences)

    print(f"  📊 Jitter Stats over {iterations} iterations of {target_sleep*1000:.1f}ms sleep:", flush=True)
    print(f"     Max: {max_jitter*1000:.3f} ms", flush=True)
    print(f"     Avg: {avg_jitter*1000:.3f} ms", flush=True)

    assert max_jitter <= acceptable_jitter_max, (
        f"Timer jitter exceeded acceptable threshold.\n"
        f"Max jitter was {max_jitter*1000:.3f}ms (threshold: {acceptable_jitter_max*1000:.1f}ms)."
    )

    print(f"  ✅ SUCCESS: Timer jitter is within acceptable limits.", flush=True)
    print("="*60 + "\n", flush=True)


def test_timer_stress(board_config):
    """
    Spawns multiple concurrent timers to ensure the system scheduler
    and timer queues handle high concurrency gracefully.
    """
    import random

    print("\n" + "="*60, flush=True)
    print("🔥 TIMER VALIDATION: STRESS TEST", flush=True)

    thread_count = board_config.get("timer_stress_thread_count", 100)
    max_delay = board_config.get("timer_stress_max_delay", 1.0)
    results = [False] * thread_count
    
    def timer_callback(idx):
        results[idx] = True

    timers = []
    print(f"  📋 Scheduling {thread_count} concurrent timers...", flush=True)
    
    # Pre-calculate delays to spawn them as fast as possible
    delays = [random.uniform(0.1, max_delay) for _ in range(thread_count)]
    
    for i in range(thread_count):
        t = threading.Timer(delays[i], timer_callback, args=(i,))
        timers.append(t)
        
    start_time = time.time()
    for t in timers:
        t.start()

    # Wait for the max delay + a buffer
    wait_time = max_delay + 0.5
    print(f"  ⏳ Waiting {wait_time:.1f}s for all timers to fire...", flush=True)
    time.sleep(wait_time)

    success_count = sum(results)
    
    print(f"  ✅ {success_count}/{thread_count} timers fired successfully.", flush=True)
    
    assert success_count == thread_count, f"Stress test failed: only {success_count} out of {thread_count} timers fired."
    
    print(f"  ✅ SUCCESS: System handled {thread_count} concurrent timers.", flush=True)
    print("="*60 + "\n", flush=True)


def test_timer_cron(board_config):
    """
    Validates that the cron daemon is actively monitoring the system clock
    and dispatching tasks at the correct minute boundaries.
    """
    print("\n" + "="*60, flush=True)
    print("📅 TIMER VALIDATION: CRON TEST", flush=True)

    marker_file = board_config.get("cron_test_marker_file", "/tmp/pytest_cron_test.txt")
    cron_job = f"* * * * * touch {marker_file}\n"
    
    if os.path.exists(marker_file):
        os.remove(marker_file)

    # 1. Backup current crontab
    print("  📋 Backing up current crontab...", flush=True)
    try:
        backup_out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        original_crontab = backup_out.stdout if backup_out.returncode == 0 else ""
    except Exception as e:
        pytest.fail(f"Could not read crontab: {e}")

    new_crontab = original_crontab + cron_job

    try:
        # 2. Inject new crontab
        print("  💉 Injecting test cron job...", flush=True)
        process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        process.communicate(new_crontab)
        if process.returncode != 0:
            pytest.fail("Failed to install temporary crontab.")

        # 3. Calculate time to next minute boundary
        now = datetime.now()
        seconds_to_next_minute = 60 - now.second
        
        # Add 5 seconds grace period for cron to wake up and execute
        wait_time = seconds_to_next_minute + 5
        print(f"  ⏳ Waiting {wait_time}s for the next minute boundary...", flush=True)
        time.sleep(wait_time)

        # 4. Verify execution
        assert os.path.exists(marker_file), (
            f"Cron job failed to create {marker_file} at the minute boundary.\n"
            f"Ensure the 'cron' daemon is running on the Pi."
        )

        print(f"  ✅ Marker file created! Cron successfully fired.", flush=True)

    finally:
        # 5. Restore original crontab
        print("  🧹 Restoring original crontab and cleaning up...", flush=True)
        try:
            if original_crontab.strip():
                process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
                process.communicate(original_crontab)
            else:
                subprocess.run(["crontab", "-r"], capture_output=True)
                
            if os.path.exists(marker_file):
                os.remove(marker_file)
        except Exception as e:
            print(f"  ⚠️ Cleanup warning: {e}", flush=True)

    print(f"  ✅ SUCCESS: Cron daemon is functioning correctly.", flush=True)
    print("="*60 + "\n", flush=True)
