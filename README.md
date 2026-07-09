# Autonomous BSP Validation Framework

Welcome to the **Autonomous BSP Validation Framework**! This project provides a robust, agent-driven hardware testing suite for embedded Linux devices (such as the Raspberry Pi, BeagleBone, and custom boards). 

The framework is designed to seamlessly run hardware tests (GPIO, I2C, SPI, UART, PCIe, Ethernet, Watchdog, RTC) remotely from your host machine while utilizing Agentic AI to both discover unknown hardware and analyze kernel-level test failures.

---

## 🚀 Key Features

- **Zero-Touch Deployment:** The framework automatically packages its code, securely transfers it to the target board over SSH, installs dependencies, and executes the suite natively.
- **AI-Driven Hardware Discovery:** Don't know the GPIO pinout or device tree paths of your custom board? Run `pytest --board auto` and the AI will probe the hardware via SSH to synthesize a safe test configuration.
- **Agentic RCA (Root Cause Analysis):** If a kernel panic occurs or a peripheral test fails, an autonomous AI Agent kicks in. It pulls `dmesg` logs and interrupt data, analyzes the failure, and generates a standalone Markdown report (`bsp_rca_report.md`).
- **Reboot-Resilient Tests:** Built-in continuous session mode tracks test progress on the device. If a test triggers a hard reboot or kernel panic, the framework waits for the board to come back online and resumes testing right where it left off!

---

## 📋 Prerequisites

### On Your Host Machine (Laptop/PC)
1. **Python 3.10+** installed.
2. **SSH Access** to your target board (password or key-based).
3. **OpenRouter API Key** (or standard OpenAI key) for the AI Agent features.

### On the Target Board
- A Debian-based Linux OS (e.g., Raspberry Pi OS, Ubuntu).
- Physical loopback wires for testing interfaces (e.g., connecting a TX pin to an RX pin for UART tests, or jumping an OUT pin to an IN pin for GPIO).

---

## 🛠️ Setup Instructions

### 1. Install Host Dependencies
On your laptop/PC, create a virtual environment and install the required dependencies:
```bash
python3 -m venv venv
source venv/bin/activate

# Install testing dependencies
pip install -r requirements.txt

# Install AI Agent dependencies
pip install -r agent_requirements.txt
```

### 2. Configure Environment Variables
The AI Agent requires access to an LLM to analyze logs and synthesize board configurations. Create a `.env` file in the root directory of this project:
```bash
# .env
OPENROUTER_API_KEY="your_api_key_here"
MODEL_NAME="openai/gpt-4o" # or another model of your choice
```

### 3. Configure the Target Board (`boards.yaml`)
The `boards.yaml` file acts as the single source of truth for hardware mappings. 
Open `boards.yaml` and ensure there is at least a `remote` configuration block pointing to your board's IP address:

```yaml
raspberry_pi_5:
  remote:
    host: "192.168.0.207"
    user: "rpi"
    password: "rpi"  # Optional, but needed if ssh keys aren't set up
```

---

## 🏃 Executing Tests

To enable the AI agent to analyze failures, you must always run your tests with the `--json-report` flag. The AI agent relies on the generated `.report.json` file.

### Method A: Testing Known Boards
If your board profile is already defined in `boards.yaml` (e.g., `raspberry_pi_5`), pass its name to the Pytest runner along with the JSON report flag:
```bash
pytest --board raspberry_pi_5 --json-report
```
*What happens:* The framework intercepts this command, deploys the code via SSH to the board, installs `apt` and `pip` dependencies, executes the tests in continuous session mode, and aggregates the results back to your host.

### Method B: AI Auto-Discovery for Unknown Boards
If you are testing a brand new board and aren't sure how to configure the YAML paths:
```bash
pytest --board auto --json-report
```
*What happens:* 
1. The framework connects using the first available `remote` IP in `boards.yaml`.
2. It probes the hardware (`ls /dev/gpiochip*`, `/dev/i2c*`, `/sys/class/net/`, etc.).
3. The AI Agent synthesizes a complete YAML configuration and presents it in your terminal.
4. If you approve the configuration, it saves the profile to `boards.yaml` and begins test execution automatically!

### Method C: Customizing Execution (Specific Tests & Flags)
You can leverage standard `pytest` syntax to run specific test files, individual test functions, or use standard flags (`-s`, `-v`, `-k`) to adjust how the tests run and output. Don't forget to include `--json-report` and your board target in all custom runs:

**Running a specific test script (e.g., only I2C tests):**
```bash
pytest test_i2c.py --board auto --json-report
```

**Running a specific test function within a script:**
```bash
pytest test_gpio.py::test_gpio_loopback --board auto --json-report
```

---

## 🧠 Autonomous Failure Analysis

You do not need to manually trigger the AI analyzer. The framework is designed to run the Agent autonomously:
- When Pytest completes execution, it synchronizes the `.report.json` back to your host machine.
- If **any tests failed**, `conftest.py` automatically launches `agent.py`.
- The Agent SSHes into the board, scrapes the latest `dmesg` ring buffer and `/proc/interrupts`.
- The LLM reasons over the Python traceback and the physical hardware logs.
- It generates a detailed `bsp_rca_report.md` root-cause analysis report in your project directory.

## 📁 Directory Structure Overview

- `test_*.py`: Modular test scripts for specific hardware peripherals (SPI, I2C, UART, PCIe).
- `conftest.py`: The core test interceptor. Handles remote deployment, syncs logs, manages reboot resilience, and hooks into the AI.
- `detect_board.py`: The AI-driven hardware topology scanner.
- `agent.py`: The post-run AI Root Cause Analysis generator.
- `boards.yaml`: The central repository for board-specific hardware pinouts and SSH credentials.
- `requirements.txt`: Python packages installed on the remote board.
- `agent_requirements.txt`: Python packages installed strictly on the host for AI operations.

Happy Testing! 🚀
