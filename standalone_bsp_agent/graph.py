import os
import re
import time
from typing import TypedDict, Annotated, List, Any
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from dotenv import load_dotenv

from personas import DISCOVERER_PROMPT, SYNTHESIZER_PROMPT, DIAGNOSER_PROMPT
from tools import run_ssh_command, read_dmesg_logs

load_dotenv(override=True)

class AgentState(TypedDict):
    hardware_topology: str
    user_test_requests: str
    synthesized_script: str
    test_results: str
    test_exit_code: int
    diagnosis: str
    report_content: str
def robust_invoke(bind_tools_list, messages):
    provider = os.environ.get("MODEL_PROVIDER", "groq").lower()
    
    models = []
    if provider == "groq":
        models = [
            os.environ.get("MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct"),
            "llama-3.1-8b-instant"
        ]
    
    # Remove duplicates in case MODEL_NAME is already in the list
    unique_models = list(dict.fromkeys(models))
    
    for idx, model_name in enumerate(unique_models):
        try:
            time.sleep(5) # Rate limit protection
            
            if provider == "openrouter":
                llm = ChatOpenAI(
                    model=model_name,
                    temperature=0.1,
                    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
                    base_url="https://openrouter.ai/api/v1",
                    max_retries=0
                )
            else:
                llm = ChatGroq(
                    model=model_name,
                    temperature=0.1,
                    api_key=os.environ.get("GROQ_API_KEY", ""),
                    max_retries=0
                )
            if bind_tools_list:
                llm = llm.bind_tools(bind_tools_list)
                
            return llm.invoke(messages)
        except Exception as e:
            error_msg = str(e).splitlines()[0][:100]
            print(f"  [LLM Error] {model_name} failed ({error_msg}...). Falling back...")
            if idx == len(unique_models) - 1:
                raise Exception(f"All fallback models exhausted. Last error: {e}")

def discover_node(state: AgentState) -> AgentState:
    print("\n[Agent] 🔍 Discovering Hardware Topology...")
    
    # Run the hardware discovery command directly to avoid LLM tool loop crashes
    discovery_cmd = "cat /proc/device-tree/model 2>/dev/null; uname -a; ip -br link; lsblk; lspci 2>/dev/null; lsusb 2>/dev/null; ls /dev/i2c* /dev/spi* /dev/tty* 2>/dev/null"
    print(f"  [Tool] Running run_ssh_command directly for hardware probe...")
    raw_output = run_ssh_command.invoke({"command": discovery_cmd})
    
    # Now ask the LLM to parse this raw output into our beautiful JSON schema
    prompt = f"{DISCOVERER_PROMPT}\n\nRAW HARDWARE OUTPUT:\n{raw_output}"
    messages = [HumanMessage(content=prompt)]
    
    print(f"  [Agent] 🧠 Parsing hardware data into JSON schema...")
    response = robust_invoke(None, messages)
    
    topology = response.content if hasattr(response, 'content') else str(response)
    
    # Strip any markdown backticks if the LLM adds them
    if topology.startswith("```json"):
        topology = topology.replace("```json", "", 1).strip()
    if topology.endswith("```"):
        topology = topology[:-3].strip()
        
    return {"hardware_topology": topology}

def synthesize_node(state: AgentState) -> AgentState:
    print("\n[Agent] 🧪 Synthesizing Test Script...")
    prompt = f"{SYNTHESIZER_PROMPT}\n\nDiscovered Hardware:\n{state['hardware_topology']}\n\nUser Requests:\n{state['user_test_requests']}"
    
    response = robust_invoke(None, [HumanMessage(content=prompt)])
    content = response.content
    
    # Extract bash block
    match = re.search(r"```bash(.*?)```", content, re.DOTALL)
    script = match.group(1).strip() if match else content.strip()
    
    return {"synthesized_script": script}

def hardware_prep_node(state: AgentState) -> AgentState:
    print("\n[Agent] 🔌 Checking for required physical hardware connections...")
    
    prompt = f"""
Analyze the following test script and determine if the user needs to make any physical hardware connections before running it.
Examples: 
- UART loopback requires connecting RX to TX pins.
- SPI loopback requires connecting MOSI to MISO.
- Ethernet tests might require plugging in an active ethernet cable.
- GPIO tests might require shorting specific pins.

If physical wiring/connections ARE required, output exactly "YES" on the first line, followed by the clear, step-by-step instructions for the user.
If NO physical wiring is required (e.g., internal software tests, I2C scan, reading timers, OR if the script uses Software-In-The-Loop kernel stubs like `i2c-stub` or `dummy`), output exactly "NO".

Script:
```bash
{state['synthesized_script']}
```
"""
    
    response = robust_invoke(None, [HumanMessage(content=prompt)])
    content = response.content.strip()
    
    if content.upper().startswith("YES"):
        instructions = content[3:].strip()
        print(f"\n============================================================")
        print(f"⚠️  HARDWARE CONNECTION REQUIRED")
        print(f"============================================================")
        print(instructions)
        print(f"============================================================\n")
        input("[HITL] 🛑 Please make the physical connections described above, then press Enter to execute the tests...")
    else:
        print("  -> No physical hardware connections required. Proceeding...")
        
    return state

def dependency_check_node(state: AgentState) -> AgentState:
    print("\n[Agent] 📦 Checking for missing software dependencies...")
    prompt = f"""
Analyze the following test script. List all standard Linux tools/utilities it uses that typically require installation via `apt-get` (e.g., i2c-tools, iperf3, ethtool, pciutils, can-utils).
Only output the raw package names separated by spaces (e.g., `i2c-tools iperf3`).
If no external packages are needed, output exactly "NONE".

Script:
```bash
{state['synthesized_script']}
```
"""
    response = robust_invoke(None, [HumanMessage(content=prompt)])
    packages = response.content.replace('`', '').strip()
    
    if "NONE" not in packages.upper() and len(packages) > 0:
        print(f"  -> Missing packages detected: {packages}")
        print(f"  -> Installing automatically via apt-get...")
        from tools import install_packages
        result = install_packages.invoke(packages)
        # Truncate result for terminal display
        print(f"  -> Installation Complete. Details: {result[:80]}...")
    else:
        print("  -> No missing software dependencies detected.")
        
    return state

def execute_node(state: AgentState) -> AgentState:
    print("\n[Agent] 🚀 Executing Validation Tests on Target...")
    
    # Write the script to a local file, then scp it, then run it.
    # For simplicity using fabric, we can just run it inline by passing the multi-line string.
    script = state["synthesized_script"]
    
    # We will upload and execute it using a single ssh command via our tool
    # A trick is to base64 encode it, echo it, decode it, and run it.
    import base64
    b64_script = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo {b64_script} | base64 -d > /tmp/bsp_test.sh && chmod +x /tmp/bsp_test.sh && export PATH=$PATH:/usr/local/sbin:/usr/sbin:/sbin && /tmp/bsp_test.sh"
    
    result = run_ssh_command.invoke({"command": cmd})
    
    # Our run_ssh_command doesn't easily expose the raw exit code in its current return string format,
    # so we will check if the tool output indicates an error or we can just parse the output.
    # To be precise, let's run a secondary check.
    code_cmd = f"echo {b64_script} | base64 -d > /tmp/bsp_test.sh && chmod +x /tmp/bsp_test.sh && export PATH=$PATH:/usr/local/sbin:/usr/sbin:/sbin && /tmp/bsp_test.sh; echo EXIT_CODE=$?"
    result_with_code = run_ssh_command.invoke({"command": code_cmd})
    
    exit_code = 0
    if "EXIT_CODE=" in result_with_code:
        try:
            exit_code = int(result_with_code.split("EXIT_CODE=")[-1].strip())
        except:
            exit_code = 1
            
    print(f"  [Result] Exit Code: {exit_code}")
    print(f"  [Output] \n{result_with_code}")
    
    return {"test_results": result_with_code, "test_exit_code": exit_code}

def diagnose_node(state: AgentState) -> AgentState:
    if state.get("test_exit_code", 0) == 0:
        return {"diagnosis": "All tests passed successfully. No diagnosis needed."}
        
    print("\n[Agent] 🚨 Tests failed! Running Root Cause Analysis...")
    
    prompt = f"{DIAGNOSER_PROMPT}\n\nTest Output:\n{state['test_results']}"
    messages = [HumanMessage(content=prompt)]
    
    max_iterations = 15
    iteration = 0
    executed_commands = set()
    while iteration < max_iterations:
        iteration += 1
        response = robust_invoke([run_ssh_command, read_dmesg_logs], messages)
        messages.append(response)
        
        if not getattr(response, 'tool_calls', None):
            break
            
        unique_tool_calls = []
        seen = set()
        for tc in response.tool_calls:
            sig = f"{tc['name']}_{tc['args']}"
            if sig not in seen:
                unique_tool_calls.append(tc)
                seen.add(sig)
                
        for tool_call in unique_tool_calls:
            print(f"  [Tool] Running {tool_call['name']} with args: {tool_call['args']}")
            
            cmd_signature = f"{tool_call['name']}_{tool_call['args']}"
            if cmd_signature in executed_commands:
                result = f"Error: Tool '{tool_call['name']}' with these arguments was already executed. Stop repeating identical tool calls and synthesize a diagnosis."
            elif tool_call['name'] == 'run_ssh_command':
                result = run_ssh_command.invoke(tool_call['args'])
                executed_commands.add(cmd_signature)
            elif tool_call['name'] == 'read_dmesg_logs':
                result = read_dmesg_logs.invoke(tool_call['args'])
                executed_commands.add(cmd_signature)
            else:
                result = "Tool not found."
                
            messages.append(ToolMessage(tool_call_id=tool_call['id'], content=str(result), name=tool_call['name']))
            
    if iteration >= max_iterations:
        print("  [Warning] Maximum diagnosis iterations reached. Returning partial diagnosis.")
        
    return {"diagnosis": messages[-1].content if hasattr(messages[-1], 'content') else "Diagnosis incomplete."}

def report_node(state: AgentState) -> AgentState:
    print("\n[Agent] 📝 Writing Log Report...")
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_content = f"""
============================================================
🚀 BSP VALIDATION RUN REPORT
============================================================
📅 Date: {timestamp}

🔍 1. HARDWARE TOPOLOGY DISCOVERED
------------------------------------------------------------
{state.get('hardware_topology', 'None')}

🧪 2. SYNTHESIZED TEST SCRIPT
------------------------------------------------------------
```bash
{state.get('synthesized_script', 'None')}
```

⚙️ 3. TEST EXECUTION RESULTS (Exit Code: {state.get('test_exit_code', 'N/A')})
------------------------------------------------------------
{state.get('test_results', 'None')}

🚨 4. AGENT DIAGNOSIS & ROOT CAUSE ANALYSIS
------------------------------------------------------------
{state.get('diagnosis', 'None')}

============================================================
✅ END OF REPORT
============================================================
"""
    return {"report_content": log_content}

# --- Graph Assembly ---
workflow = StateGraph(AgentState)

workflow.add_node("discover", discover_node)
workflow.add_node("synthesize", synthesize_node)
workflow.add_node("hardware_prep", hardware_prep_node)
workflow.add_node("dependency_check", dependency_check_node)
workflow.add_node("execute", execute_node)
workflow.add_node("diagnose", diagnose_node)
workflow.add_node("report", report_node)

# Flow:
# 1. We will run Discover manually in main, then HITL, then Synthesize -> Hardware Prep -> Dependency Check -> Execute -> Diagnose -> Report
workflow.add_edge("synthesize", "hardware_prep")
workflow.add_edge("hardware_prep", "dependency_check")
workflow.add_edge("dependency_check", "execute")
workflow.add_edge("execute", "diagnose")
workflow.add_edge("diagnose", "report")
workflow.add_edge("report", END)

workflow.set_entry_point("synthesize")
app = workflow.compile()
