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
    with open("boards.yaml", "r") as f:
        configs = yaml.safe_load(f)
    
    board = configs.get(board_name)
    
    # 2. If the board profile has no remote config, run locally (e.g., debugging)
    if not board or "remote" not in board:
        return None 
        
    host = board["remote"]["host"]
    user = board["remote"]["user"]
    remote_dir = f"~/hw-val-framework"

    print(f"\n🚀 [HOST] Intercepting Pytest. Auto-deploying to {user}@{host}...")

    # 3. Auto-Install OS Dependencies on the Pi (Fixed syntax error here)
    print("⚙️  [1/4] Installing OS dependencies on Pi (if missing)...")
    os_deps_cmd = f"ssh {user}@{host} 'sudo apt-get update && sudo apt install -y i2c-tools python3-venv python3-pip gpiod libgpiod-dev speedtest-cli iperf3 pciutils nvme-cli fio'"
    subprocess.run(os_deps_cmd, shell=True)

    # 4. Sync Code to Pi (Using tar to instantly compress, send, and extract while ignoring caches)
    # Because of this design, requirements.txt is automatically synced to the Pi!
    print("📦 [2/4] Syncing code to Pi...")
    sync_cmd = f"tar --exclude='venv' --exclude='__pycache__' --exclude='.pytest_cache' -czf - . | ssh {user}@{host} 'mkdir -p {remote_dir} && cd {remote_dir} && tar -xzf -'"
    subprocess.run(sync_cmd, shell=True)

    # 5. Auto-Install Python Dependencies on Pi using requirements.txt
    print("🐍 [3/4] Configuring Python Environment on Pi...")
    setup_cmd = f"ssh {user}@{host} 'cd {remote_dir} && python3 -m venv venv && source venv/bin/activate && pip install -q -r requirements.txt'"
    subprocess.run(setup_cmd, shell=True)

    # 6. Setup Local Logging Directory
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"logs/run_{board_name}_{timestamp}.log"
    print(f"📝 [HOST] Live logs will be saved to: {log_file}")

    # 7. Execute the test, stream to terminal, and write to file simultaneously
    args = " ".join(config.invocation_params.args)
    print(f"🔥 [4/4] Executing test on Pi: pytest {args}\n")
    print("="*60)
    
    run_cmd = f"ssh {user}@{host} 'cd {remote_dir} && source venv/bin/activate && export RUNNING_ON_PI=1 && pytest {args} --board={board_name} -v -s'"
    
    with open(log_file, "w") as log:
        # Popen allows us to read the output line-by-line as it happens
        process = subprocess.Popen(run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            sys.stdout.write(line)  # Print to your laptop's screen
            log.write(line)         # Write to the local log file
            log.flush()             # Ensure it writes to disk immediately
            
        process.wait()
    
    print("="*60)
    print(f"✅ [HOST] Remote execution complete. Artifact saved: {log_file}")
    
    # 8. Abort the local pytest run and exit with the Pi's success/fail code
    sys.exit(process.returncode)


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