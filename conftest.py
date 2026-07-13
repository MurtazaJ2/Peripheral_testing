import pytest
import yaml
import sys
import subprocess
import os
from datetime import datetime

def pytest_addoption(parser):
    """Allows us to pass the board target."""
    parser.addoption("--board", action="store", default="raspberry_pi_5")

def pytest_cmdline_main(config):
    """INTERCEPTOR: Hijacks the local pytest command and routes it to the target board."""
    
    # 1. If we are already executing ON the Pi, do not intercept. Let pytest run normally.
    if os.environ.get("RUNNING_ON_PI"):
        return None 

    board_name = config.getoption("--board")
    
    if board_name == "auto":
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [HOST] Auto-detecting board hardware...")
        from detect_board import discover_and_update_board
        detected = discover_and_update_board()
        if not detected:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [ERROR] [HOST] Could not auto-detect board. Exiting.")
            sys.exit(1)
        board_name = detected
        config.option.board = detected

    with open("boards.yaml", "r") as f:
        configs = yaml.safe_load(f)
    
    board = configs.get(board_name)
    
    # 2. If the board profile has no remote config, run locally (e.g., debugging)
    if not board or "remote" not in board:
        return None 
        
    host = board["remote"]["host"]
    user = board["remote"]["user"]
    remote_dir = f"~/hw-val-framework"

    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [HOST] Intercepting Pytest. Auto-deploying to {user}@{host}...")

    # 3. Auto-Install OS Dependencies on the Pi (Fixed syntax error here)
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [1/4] Installing OS dependencies on Pi (if missing)...")
    os_deps_cmd = f"ssh {user}@{host} 'sudo apt-get update && sudo apt install -y i2c-tools python3-venv python3-pip gpiod libgpiod-dev speedtest-cli iperf3 pciutils nvme-cli fio'"
    subprocess.run(os_deps_cmd, shell=True)

    # 4. Sync Code to Pi (Using tar to instantly compress, send, and extract while ignoring caches)
    # Because of this design, requirements.txt is automatically synced to the Pi!
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [2/4] Syncing code to Pi...")
    sync_cmd = f"tar --exclude='venv' --exclude='__pycache__' --exclude='.pytest_cache' -czf - . | ssh {user}@{host} 'mkdir -p {remote_dir} && cd {remote_dir} && tar -xzf -'"
    subprocess.run(sync_cmd, shell=True)

    # 5. Auto-Install Python Dependencies on Pi using requirements.txt
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [3/4] Configuring Python Environment on Pi...")
    setup_cmd = f"ssh {user}@{host} 'cd {remote_dir} && python3 -m venv venv && source venv/bin/activate && pip install -q -r requirements.txt'"
    subprocess.run(setup_cmd, shell=True)

    # 6. Setup Local Logging Directory
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"logs/run_{board_name}_{timestamp}.log"
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [HOST] Live logs will be saved to: {log_file}")

    # 7. Clear tracker on Pi and Execute Tests
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  [4/4] Executing test suite on Pi in continuous session mode...")
    args = " ".join(config.invocation_params.args)
    subprocess.run(f"ssh {user}@{host} 'rm -f {remote_dir}/pytest_attempted.txt'", shell=True)
    
    import time
    import glob
    import json
    
    session_part = 1
    # Cleanup any old parts left over from crashes
    for f in glob.glob(".report_part_*.json"):
        os.remove(f)
        
    with open(log_file, "w") as log:
        while True:
            # Wait for board to be online before starting
            board_online = False
            for _ in range(36): # 3 minutes
                ping_proc = subprocess.run(f"ssh -o ConnectTimeout=3 {user}@{host} 'echo ready'", shell=True, capture_output=True)
                if ping_proc.returncode == 0:
                    board_online = True
                    break
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]    Waiting for board to become reachable over SSH...")
                time.sleep(5)
                
            if not board_online:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [ERROR] Board failed to come online. Aborting run.")
                sys.exit(1)
                
            # If we just recovered from a hard crash, the previous session's partial report is stuck on the Pi.
            # We try to download it again here using the exact same name, so it overwrites any corrupt 
            # or missing files without duplicating the JSON files for the final glob merge!
            if session_part > 1:
                subprocess.run(f"scp -q {user}@{host}:{remote_dir}/.report.json .report_part_{session_part-1}.json 2>/dev/null", shell=True)

            run_cmd = f"ssh {user}@{host} 'cd {remote_dir} && source venv/bin/activate && export RUNNING_ON_PI=1 && pytest {args} --board={board_name} -v -s -o asyncio_default_fixture_loop_scope=function'"
            test_proc = subprocess.Popen(run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            
            for line in test_proc.stdout:
                sys.stdout.write(line)
                log.write(line)
                log.flush()
            test_proc.wait()
            
            # ALWAYS attempt to pull the partial JSON report (if pytest wrote it before exiting)
            subprocess.run(f"scp -q {user}@{host}:{remote_dir}/.report.json .report_part_{session_part}.json 2>/dev/null", shell=True)
            
            if test_proc.returncode in (2, 255):
                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Pytest Session Halted (Code {test_proc.returncode} - Reboot triggered).")
                
                # If it was a graceful scheduled reboot (Code 2), the background script is still waiting to reboot.
                # We must wait for it to actually drop the network before we try to check if it's back online!
                if test_proc.returncode == 2:
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]    Allowing 20 seconds for the scheduled reboot to take down the network...")
                    time.sleep(20)
                    
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Waiting for Pi to recover before resuming tests...")
                session_part += 1
                continue # Loop back and resume the remaining tests
            else:
                # Finished normally (0 = pass, 1 = fail)
                print("\n" + "="*60)
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Pulling final HTML and XML test reports from Pi...")
                subprocess.run(f"scp -q -r {user}@{host}:{remote_dir}/logs/pytest_html_report ./logs/ 2>/dev/null", shell=True)
                subprocess.run(f"scp -q {user}@{host}:{remote_dir}/logs/test-results.xml ./logs/ 2>/dev/null", shell=True)
                
                # Merge JSON parts
                json_out_file = ".report.json"
                parts = sorted(glob.glob(".report_part_*.json"))
                merged = None
                
                for part in parts:
                    try:
                        with open(part, "r") as f:
                            data = json.load(f)
                        if merged is None:
                            merged = data
                        else:
                            merged["duration"] += data.get("duration", 0)
                            for k, v in data.get("summary", {}).items():
                                if k == "collected":
                                    merged.setdefault("summary", {})[k] = max(merged.get("summary", {}).get(k, 0), v)
                                else:
                                    merged.setdefault("summary", {})[k] = merged.get("summary", {}).get(k, 0) + v
                            merged.setdefault("tests", []).extend(data.get("tests", []))
                    except Exception:
                        pass
                        
                if merged:
                    with open(json_out_file, "w") as f:
                        json.dump(merged, f, indent=2)
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Unified JSON Report saved to: {json_out_file}")
                    
                for part in parts:
                    os.remove(part)
                
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Remote execution complete. Host log saved: {log_file}")
                
                if os.path.exists("agent.py"):
                    print("\n" + "="*60)
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO]  Launching Autonomous AI Agent for Analysis...")
                    subprocess.run(["python3", "agent.py"])
                
                sys.exit(0 if test_proc.returncode == 0 else 1)


# --- Hardware Fixtures (Executed only on the Pi) ---

@pytest.fixture(scope="session")
def board_config(request):
    """Reads the boards.yaml file."""
    board = request.config.getoption("--board")
    with open("boards.yaml", "r") as file:
        configs = yaml.safe_load(file)
    return configs[board]

@pytest.fixture(scope="function")
def loopback_pins(board_config):
    """Generic hardware setup using the modern gpiod v2 API."""
    import gpiod
    from gpiod.line import Direction
    
    out_pin = board_config["out_pin"]
    in_pin = board_config["in_pin"]
    
    # v2 API: We request multiple lines in one atomic action
    request = gpiod.request_lines(
        board_config["chip"],
        consumer="pytest_loopback",
        config={
            out_pin: gpiod.LineSettings(direction=Direction.OUTPUT),
            in_pin: gpiod.LineSettings(direction=Direction.INPUT)
        }
    )
    
    yield request
    
    request.release()

def pytest_runtest_teardown(item):
    """Incremental Save: Save JSON report after every test so data isn't lost if the kernel panics."""
    if os.environ.get("RUNNING_ON_PI"):
        json_plugin = item.config.pluginmanager.getplugin("json-report")
        if json_plugin and hasattr(json_plugin, "report"):
            import json
            try:
                with open(".report.json", "w") as f:
                    json.dump(json_plugin.report, f)
            except Exception:
                pass

def pytest_runtest_setup(item):
    """Tracker: Record test as attempted before it runs, so we skip it upon reboot resumption."""
    if os.environ.get("RUNNING_ON_PI"):
        with open("pytest_attempted.txt", "a") as f:
            f.write(item.nodeid + "\n")

def pytest_collection_modifyitems(config, items):
    """Tracker: Remove already attempted tests from the queue upon resumption."""
    if os.environ.get("RUNNING_ON_PI"):
        try:
            with open("pytest_attempted.txt", "r") as f:
                completed = set(f.read().splitlines())
            
            # Keep only items that haven't been attempted yet
            items[:] = [item for item in items if item.nodeid not in completed]
        except FileNotFoundError:
            pass
import contextlib

class TestLogger:
    def __init__(self, nodeid):
        self.nodeid = nodeid
        self.step_counter = 1
        self.is_first_log = True

    def _log(self, level, msg, indent=0):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"{timestamp} [{level:5}] "
        indent_str = "  " * indent
        
        if self.is_first_log:
            print()
            self.is_first_log = False
            
        for line in str(msg).split('\n'):
            print(f"{prefix}{indent_str}{line}", flush=True)

    def info(self, msg, indent=0):
        self._log("INFO", msg, indent)
        
    def error(self, msg, indent=0):
        self._log("ERROR", msg, indent)
        
    def pass_mark(self, msg, indent=0):
        self._log("PASS", msg, indent)

    def fail_mark(self, msg, indent=0):
        self._log("FAIL", msg, indent)

    def skip_mark(self, msg, indent=0):
        self._log("SKIP", msg, indent)

    @contextlib.contextmanager
    def step(self, name, action, expected):
        step_num = self.step_counter
        self.step_counter += 1
        
        self.info(f"STEP {step_num}: {name}")
        self.info(f"Action: {action}", indent=1)
        self.info(f"Expected: {expected}", indent=1)
        
        class StepResult:
            def __init__(self):
                self.actual = None
            def success(self, actual):
                self.actual = actual
        
        result = StepResult()
        
        try:
            yield result
            if result.actual is not None:
                self.info(f"Actual: {result.actual}", indent=1)
            else:
                self.info(f"Actual: Matches expected", indent=1)
            self.pass_mark(f"STEP {step_num}: {name}", indent=1)
        except AssertionError as e:
            self.error(f"Actual: Assertion Failed - {str(e)}", indent=1)
            self.fail_mark(f"STEP {step_num}: {name}", indent=1)
            raise
        except BaseException as e:
            if type(e).__name__ == "Skipped":
                self.info(f"Actual: Skipped - {str(e)}", indent=1)
                self.skip_mark(f"STEP {step_num}: {name}", indent=1)
                self.info("="*60)
                raise
            if isinstance(e, Exception):
                self.error(f"Actual: Exception Raised - {type(e).__name__}: {str(e)}", indent=1)
                self.fail_mark(f"STEP {step_num}: {name}", indent=1)
            raise

@pytest.fixture
def step_logger(request):
    return TestLogger(request.node.nodeid)
