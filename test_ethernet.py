import pytest
import subprocess
import socket
import re
import os

def test_ethernet_interface_state(board_config):
    """
    Validates that the Ethernet interface is physically up and active.
    Checks the /sys/class/net/ethX/operstate file.
    """
    eth_interface = board_config.get("eth_interface", "eth0")
    
    print("\n" + "="*60, flush=True)
    print(f"🔌 ETHERNET VALIDATION: INTERFACE STATE ({eth_interface})", flush=True)
    
    operstate_path = f"/sys/class/net/{eth_interface}/operstate"
    if not os.path.exists(operstate_path):
        pytest.fail(f"Interface {eth_interface} does not exist in sysfs.")
        
    with open(operstate_path, "r") as f:
        state = f.read().strip()
        
    print(f"  ℹ️  Link State: {state.upper()}", flush=True)
    assert state in ["up", "unknown"], f"Ethernet interface {eth_interface} is physically down (state: {state}). Plug in a cable!"
    print(f"  ✅ SUCCESS: Interface {eth_interface} is active.", flush=True)
    print("="*60 + "\n", flush=True)

def test_ethernet_ip_check(board_config):
    """
    Validates that the interface has an assigned IPv4 address.
    """
    eth_interface = board_config.get("eth_interface", "eth0")
    
    print("\n" + "="*60, flush=True)
    print(f"🌐 ETHERNET VALIDATION: IP ALLOCATION ({eth_interface})", flush=True)
    
    try:
        ip_out = subprocess.run(["ip", "-4", "addr", "show", eth_interface], capture_output=True, text=True, check=True).stdout
        match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_out)
        
        assert match is not None, f"No IPv4 address found for interface {eth_interface}."
        
        ip_addr = match.group(1)
        print(f"  ✅ Allocated IP Address: {ip_addr}", flush=True)
        print(f"  ✅ SUCCESS: Valid IPv4 address is assigned.", flush=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to query IP address: {e}")
    except Exception as e:
        pytest.fail(f"Error checking IP: {e}")
    print("="*60 + "\n", flush=True)

def test_ethernet_ping_connectivity(board_config):
    """
    Validates external connectivity by pinging a known target.
    """
    eth_interface = board_config.get("eth_interface", "eth0")
    ping_target = board_config.get("eth_ping_target", "8.8.8.8")
    
    print("\n" + "="*60, flush=True)
    print(f"📡 ETHERNET VALIDATION: PING CONNECTIVITY ({ping_target})", flush=True)
    
    try:
        print(f"  📋 Pinging {ping_target} via {eth_interface}...", flush=True)
        # We pass -I to force traffic out of the specific ethernet interface
        ping_out = subprocess.run(["ping", "-c", "4", "-I", eth_interface, ping_target], capture_output=True, text=True)
        
        if ping_out.returncode != 0:
            pytest.fail(f"Ping failed to {ping_target}. Network might be unreachable.\nOutput:\n{ping_out.stderr}")
            
        print(f"  ✅ SUCCESS: Successfully pinged {ping_target} 4 times.", flush=True)
    except Exception as e:
        pytest.fail(f"Ping execution error: {e}")
    print("="*60 + "\n", flush=True)

def test_ethernet_latency(board_config):
    """
    Validates network delay/latency is within acceptable thresholds.
    Extracts the 'avg' rtt from a ping.
    """
    eth_interface = board_config.get("eth_interface", "eth0")
    ping_target = board_config.get("eth_ping_target", "8.8.8.8")
    max_latency = board_config.get("eth_max_latency_ms", 50.0)
    
    print("\n" + "="*60, flush=True)
    print(f"⏱️ ETHERNET VALIDATION: LATENCY DELAY ({ping_target})", flush=True)
    
    try:
        print(f"  📋 Measuring latency to {ping_target}...", flush=True)
        ping_out = subprocess.run(["ping", "-c", "5", "-q", "-I", eth_interface, ping_target], capture_output=True, text=True)
        
        if ping_out.returncode != 0:
            pytest.fail(f"Ping failed. Cannot measure latency.")
            
        # Example output line: rtt min/avg/max/mdev = 8.123/10.456/12.789/1.234 ms
        match = re.search(r"rtt min/avg/max/mdev = ([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+) ms", ping_out.stdout)
        assert match, "Failed to parse ping output for latency."
        
        avg_latency = float(match.group(2))
        print(f"  📊 Average Latency: {avg_latency} ms", flush=True)
        
        assert avg_latency <= max_latency, f"Latency {avg_latency}ms exceeds max acceptable threshold of {max_latency}ms."
        print(f"  ✅ SUCCESS: Latency is acceptable.", flush=True)
    except Exception as e:
        pytest.fail(f"Latency test error: {e}")
    print("="*60 + "\n", flush=True)

def test_ethernet_socket(board_config):
    """
    Validates local networking stack by opening a raw TCP socket.
    """
    target_host = board_config.get("eth_ping_target", "8.8.8.8")
    target_port = 53
    
    print("\n" + "="*60, flush=True)
    print(f"🔌 ETHERNET VALIDATION: TCP SOCKET", flush=True)
    
    try:
        print(f"  📋 Opening TCP socket to {target_host}:{target_port}...", flush=True)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((target_host, target_port))
        
        local_ip, local_port = s.getsockname()
        print(f"  ✅ Socket connected successfully from local endpoint {local_ip}:{local_port}.", flush=True)
        s.close()
        print(f"  ✅ SUCCESS: Local network stack is performing correctly.", flush=True)
    except Exception as e:
        pytest.fail(f"Socket connection failed: {e}")
    print("="*60 + "\n", flush=True)

def test_ethernet_speedtest(board_config):
    """
    Measures Internet bandwidth using speedtest-cli.
    Requires speedtest-cli to be installed via apt.
    """
    print("\n" + "="*60, flush=True)
    print(f"🚀 ETHERNET VALIDATION: SPEEDTEST BANDWIDTH", flush=True)
    print(f"  ⏳ Running speedtest (this may take up to a minute)...", flush=True)
    
    try:
        # We use --simple to get clean output like:
        # Ping: 12.34 ms
        # Download: 123.45 Mbit/s
        # Upload: 67.89 Mbit/s
        speed_out = subprocess.run(["speedtest-cli", "--simple"], capture_output=True, text=True)
        if speed_out.returncode != 0:
            pytest.fail(f"Speedtest failed. Ensure speedtest-cli is installed and internet is reachable.\nError: {speed_out.stderr}")
            
        print("\n  📊 Results:")
        for line in speed_out.stdout.strip().split('\n'):
            print(f"     {line}", flush=True)
            
        print(f"  ✅ SUCCESS: Internet bandwidth measured.", flush=True)
    except FileNotFoundError:
        pytest.fail("speedtest-cli is not installed. Add it to OS dependencies.")
    except Exception as e:
        pytest.fail(f"Speedtest execution error: {e}")
    print("="*60 + "\n", flush=True)

def test_ethernet_iperf(board_config):
    """
    Measures local network professional throughput using iperf3.
    Requires an iperf3 server running on the target network.
    """
    print("\n" + "="*60, flush=True)
    print(f"🏎️ ETHERNET VALIDATION: IPERF3 THROUGHPUT", flush=True)
    
    # Try to get explicitly configured server, otherwise use the SSH client IP automatically
    iperf_server = board_config.get("eth_iperf_server", "")
    if not iperf_server:
        ssh_client = os.environ.get("SSH_CLIENT", "")
        if ssh_client:
            iperf_server = ssh_client.split()[0]
            print(f"  ℹ️  Auto-detected iperf server from SSH session: {iperf_server}", flush=True)
        else:
            pytest.skip("No iperf_server configured in boards.yaml, and not running via SSH. Skipping iperf test.")
    else:
        print(f"  ℹ️  Using configured iperf server: {iperf_server}", flush=True)
            
    print(f"  📋 Running iperf3 client against {iperf_server} for 5 seconds...", flush=True)
    
    try:
        # Run iperf3 for 5 seconds (-t 5) to keep the test quick but accurate
        iperf_out = subprocess.run(["iperf3", "-c", iperf_server, "-t", "5", "-f", "m"], capture_output=True, text=True)
        
        if iperf_out.returncode != 0:
            pytest.skip(
                f"iPerf3 failed to connect to {iperf_server}.\n"
                f"This usually means the iperf3 server is not running on the host machine.\n"
                f"Please start it with: 'iperf3 -s' on {iperf_server}\n"
                f"Error: {iperf_out.stderr.strip()}"
            )
            
        # Parse the sender output line to get the throughput
        # Example line: [  5]  0.00-5.00   sec   564 MBytes   946 Mbits/sec                  sender
        match = re.search(r"([\d\.]+)\s+Mbits/sec\s+sender", iperf_out.stdout)
        if match:
            throughput = float(match.group(1))
            print(f"  📊 Throughput: {throughput} Mbps", flush=True)
        else:
            print("  ⚠️  Failed to parse raw iperf3 output, dumping stdout:", flush=True)
            print(iperf_out.stdout)
            
        print(f"  ✅ SUCCESS: Professional throughput measured.", flush=True)
    except FileNotFoundError:
        pytest.fail("iperf3 is not installed. Add it to OS dependencies.")
    except Exception as e:
        pytest.fail(f"iperf3 execution error: {e}")
    print("="*60 + "\n", flush=True)
