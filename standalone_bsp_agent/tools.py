from fabric import Connection
import yaml
from langchain_core.tools import tool
import os

def get_connection():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)["target"]
    
    connect_kwargs = {}
    if config.get("password"):
        connect_kwargs["password"] = config["password"]
        
    return Connection(host=config["host"], user=config["user"], connect_kwargs=connect_kwargs)

@tool
def run_ssh_command(command: str) -> str:
    """Executes a bash command on the target Raspberry Pi board via SSH and returns the stdout and stderr."""
    try:
        with get_connection() as c:
            result = c.run(command, hide=True, in_stream=False, warn=True)
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\nSTDERR:\n{result.stderr.strip()}"
            
            if not output and result.exited == 0:
                return "Command executed successfully with no output."
                
            # Truncate output to prevent hitting LLM context limits (Error 413)
            if len(output) > 3000:
                output = output[:1500] + "\n\n... [OUTPUT TRUNCATED DUE TO LENGTH] ...\n\n" + output[-1500:]
                
            return output
    except Exception as e:
        return f"Error executing SSH command: {e}"

@tool
def read_dmesg_logs(lines: int = 200) -> str:
    """Reads the last N lines of the kernel ring buffer (dmesg) to look for hardware errors, PCIe link status, or driver crashes."""
    return run_ssh_command.invoke(f"dmesg | tail -n {lines}")

@tool
def install_packages(packages: str) -> str:
    """Installs the given apt packages on the target device using sudo."""
    try:
        with get_connection() as c:
            # We use sudo which automatically uses the connection password
            result = c.sudo(f"apt-get update && apt-get install -y {packages}", hide=True, warn=True)
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\nSTDERR:\n{result.stderr.strip()}"
            return output
    except Exception as e:
        return f"Error installing packages: {e}"
