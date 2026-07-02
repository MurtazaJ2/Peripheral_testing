import os
from graph import app, discover_node

def main():
    print("="*60)
    print("🤖 Autonomous BSP Validation Agent (Standalone)")
    print("="*60)
    
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)
    
    # 1. Phase 1: Autonomous Hardware Discovery
    initial_state = {"hardware_topology": "", "user_test_requests": ""}
    discovered_state = discover_node(initial_state)
    topology = discovered_state["hardware_topology"]
    
    print("\n" + "="*60)
    print("📡 DISCOVERED HARDWARE TOPOLOGY:")
    print("="*60)
    print(topology)
    print("="*60)
    
    # 2. Phase 2: Human-In-The-Loop (HITL) Intervention
    print("\n[HITL] Based on the discovered topology above, what features would you like to validate?")
    print("       (e.g., 'Test the NVMe throughput', 'Validate UART loopback', 'Test Ethernet speed')")
    user_input = input("Enter test instructions (or press Enter for a default full suite): ")
    
    if not user_input.strip():
        user_input = "Please generate and run standard validation tests for all discovered hardware interfaces."
        
    print(f"\n[Agent] Proceeding with instructions: '{user_input}'")
    
    # 3. Phase 3: Execute full graph (Synthesize -> Execute -> Diagnose -> Report)
    final_state = app.invoke({
        "hardware_topology": topology,
        "user_test_requests": user_input,
    })
    
    # 4. Save Report
    report_path = "logs/bsp_validation.md"
    with open(report_path, "a") as f:
        f.write(final_state["report_content"])
        
    print(f"\n[Agent] ✅ Run complete. Full log saved to {report_path}")

if __name__ == "__main__":
    main()
