import argparse
import subprocess
import yaml
import sys
import re

def get_ip_from_mac(mac):
    """Finds the IP address associated with the MAC using local arp cache or ip neigh."""
    print(f"[INFO] Searching for MAC address: {mac}")
    
    # Check arp -a
    try:
        arp_out = subprocess.check_output(["arp", "-a"], text=True)
        for line in arp_out.splitlines():
            if mac.lower() in line.lower():
                # Extract IP (e.g. ? (192.168.1.5) at ...)
                match = re.search(r'\(([\d\.]+)\)', line)
                if match:
                    return match.group(1)
    except Exception:
        pass

    # Fallback to ip neigh
    try:
        ip_out = subprocess.check_output(["ip", "neigh"], text=True)
        for line in ip_out.splitlines():
            if mac.lower() in line.lower():
                match = re.search(r'^([\d\.]+)', line)
                if match:
                    return match.group(1)
    except Exception:
        pass

    return None

def check_status(ip, credentials_list):
    """Attempt SSH and print status."""
    try:
        from fabric import Connection
        import fabric
    except ImportError:
        print("[ERROR] fabric module is required. Run 'pip install fabric' (or pip install -r agent_requirements.txt).")
        sys.exit(1)
        
    for creds in credentials_list:
        user = creds.get('user', 'root')
        password = creds.get('password', '')
        identity_file = creds.get('identity_file', '')
        
        connect_kwargs = {}
        if password:
            connect_kwargs["password"] = password
        if identity_file:
            connect_kwargs["key_filename"] = identity_file
            
        print(f"[INFO] Attempting to connect as {user}@{ip}...")
        try:
            with Connection(host=ip, user=user, connect_kwargs=connect_kwargs, config=fabric.Config(overrides={'run': {'hide': True}})) as c:
                result = c.run("uptime && echo '---' && free -m && echo '---' && (cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 'N/A')", warn=True, pty=False)
                
                if result.ok:
                    print("\n[PASS] Successfully connected!")
                    print("="*50)
                    print("               MACHINE STATUS")
                    print("="*50)
                    
                    parts = result.stdout.split('---')
                    uptime_str = parts[0].strip() if len(parts) > 0 else "Unknown"
                    mem_str = parts[1].strip() if len(parts) > 1 else "Unknown"
                    temp_raw = parts[2].strip() if len(parts) > 2 else "N/A"
                    
                    print(f"\n[UPTIME & LOAD]\n{uptime_str}")
                    print(f"\n[MEMORY USAGE (MB)]\n{mem_str}")
                    
                    if temp_raw != 'N/A' and temp_raw.isdigit():
                        temp_c = int(temp_raw) / 1000.0
                        print(f"\n[TEMPERATURE]\n{temp_c:.1f} °C")
                    else:
                        print(f"\n[TEMPERATURE]\nNot available")
                        
                    print("="*50)
                    return True
        except Exception as e:
            print(f"[WARN] Connection failed: {e}")
            continue
            
    print("\n[FAIL] Could not connect to the machine with any known credentials.")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get machine status using its MAC ID or check all known boards.")
    parser.add_argument("mac", nargs='?', default="", help="Optional: The MAC address. If omitted, checks all boards in boards.yaml")
    args = parser.parse_args()

    # Load known credentials from boards.yaml
    credentials = []
    board_hosts = []
    try:
        with open("boards.yaml", "r") as f:
            configs = yaml.safe_load(f)
            if configs:
                for board, conf in configs.items():
                    if isinstance(conf, dict) and 'remote' in conf:
                        creds = conf['remote'].copy()
                        if creds not in credentials:
                            credentials.append(creds)
                        if conf['remote'].get('host'):
                            board_hosts.append(conf['remote']['host'])
    except FileNotFoundError:
        print("[WARN] boards.yaml not found.")
        
    if not credentials:
        credentials.append({'user': 'root', 'password': ''})

    if args.mac:
        ip = get_ip_from_mac(args.mac)
        if not ip:
            print(f"[ERROR] Could not resolve MAC address {args.mac} to an IP address on the local network.")
            print("Ensure the device is powered on, connected to the same network, and has communicated recently.")
            sys.exit(1)
            
        print(f"[PASS] Found IP {ip} for MAC {args.mac}")
        check_status(ip, credentials)
    else:
        if not board_hosts:
            print("[INFO] No MAC address provided and no hosts found in boards.yaml to check.")
        else:
            print(f"[INFO] No MAC address provided. Checking status for all {len(board_hosts)} board(s) in boards.yaml...")
            for ip in board_hosts:
                print(f"\n--- Checking Board at {ip} ---")
                check_status(ip, credentials)
