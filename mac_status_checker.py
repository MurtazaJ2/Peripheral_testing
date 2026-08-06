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

def check_status(ip, credentials_list, mac="Unknown"):
    """Attempt SSH and print status."""
    try:
        from fabric import Connection
        import fabric
    except ImportError:
        print("[ERROR] fabric module is required. Run 'pip install fabric' (or pip install -r agent_requirements.txt).")
        sys.exit(1)
        
    power_status = "Offline"
    sys_status = "N/A"
    
    for creds in credentials_list:
        user = creds.get('user', 'root')
        password = creds.get('password', '')
        identity_file = creds.get('identity_file', '')
        
        connect_kwargs = {}
        if password:
            connect_kwargs["password"] = password
        if identity_file:
            connect_kwargs["key_filename"] = identity_file
            
        try:
            with Connection(host=ip, user=user, connect_kwargs=connect_kwargs, config=fabric.Config(overrides={'run': {'hide': True}}), connect_timeout=5) as c:
                result = c.run("uptime && echo '---' && free -m | grep Mem && echo '---' && (cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 'N/A')", warn=True, pty=False)
                
                if result.ok:
                    power_status = "Online"
                    parts = result.stdout.split('---')
                    uptime_str = parts[0].strip().replace('\n', ' ') if len(parts) > 0 else "Unknown"
                    mem_str = parts[1].strip().replace('\n', ' ') if len(parts) > 1 else "Unknown"
                    temp_raw = parts[2].strip() if len(parts) > 2 else "N/A"
                    
                    if temp_raw != 'N/A' and temp_raw.isdigit():
                        temp_c = f"{int(temp_raw) / 1000.0:.1f} °C"
                    else:
                        temp_c = "Not available"
                        
                    sys_status = f"\n  [Uptime & Load] {uptime_str}\n  [Memory Usage (MB)] {mem_str}\n  [Temperature] {temp_c}"
                    break
        except Exception:
            continue
            
    output = "\n".join([
        "==================================================",
        f"IP address: {ip}",
        f"Machine address: {mac}",
        f"Power On status: {power_status}",
        f"System hardware and software status: {sys_status}",
        "=================================================="
    ])
    print(output)
    
    try:
        import os
        os.makedirs("logs", exist_ok=True)
        with open("logs/execution.log", "a") as f:
            f.write(output + "\n")
    except Exception as e:
        print(f"[WARN] Could not write to logs/execution.log: {e}")
    return power_status == "Online"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get machine status using its MAC ID or check all known boards.")
    parser.add_argument("mac", nargs='?', default="", help="Optional: The MAC address. If omitted, checks all boards in boards.yaml")
    parser.add_argument("--board", default="", help="Optional: The name of the board to update in boards.yaml if the IP is found.")
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

    any_online = False

    if args.mac:
        ip = get_ip_from_mac(args.mac)
        if not ip:
            output = "\n".join([
                "==================================================",
                "IP address: Unknown",
                f"Machine address: {args.mac}",
                "Power On status: Offline",
                "System hardware and software status: N/A",
                "=================================================="
            ])
            print(output)
            
            try:
                import os
                os.makedirs("logs", exist_ok=True)
                with open("logs/execution.log", "a") as f:
                    f.write(output + "\n")
            except Exception as e:
                print(f"[WARN] Could not write to logs/execution.log: {e}")
            sys.exit(0)
            
        # Dynamically update boards.yaml if a specific board was targeted
        if args.board and args.board != "all":
            try:
                with open("boards.yaml", "r") as f:
                    configs = yaml.safe_load(f)
                if configs and args.board in configs and isinstance(configs[args.board], dict) and 'remote' in configs[args.board]:
                    configs[args.board]['remote']['host'] = ip
                    with open("boards.yaml", "w") as f:
                        yaml.dump(configs, f, default_flow_style=False)
                    print(f"[INFO] Successfully updated boards.yaml: {args.board} is now pointing to {ip}")
            except Exception as e:
                print(f"[WARN] Could not update boards.yaml: {e}")
                
        if check_status(ip, credentials, mac=args.mac):
            any_online = True
    else:
        if not board_hosts:
            print("[INFO] No MAC address provided and no hosts found in boards.yaml to check.")
        else:
            print(f"[INFO] No MAC address provided. Checking status for all {len(board_hosts)} board(s) in boards.yaml...")
            for ip in board_hosts:
                print(f"\n--- Checking Board at {ip} ---")
                if check_status(ip, credentials):
                    any_online = True
                    
    if any_online:
        try:
            with open("machine_is_online.txt", "w") as f:
                f.write("online")
        except Exception:
            pass
