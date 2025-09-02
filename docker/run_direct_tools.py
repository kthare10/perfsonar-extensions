import argparse
import subprocess
import os
from datetime import datetime, timezone
import logging
from typing import Any
import re
import json

# Define tools and base commands
TOOLS = {
    "ping": ["ping", "-c", "5"],
    "iperf3": ["iperf3", "-c"],
    "nuttcp": ["nuttcp", "-fparse", "-fxmitstats", "-frunningtotal", "-j", "-T5"],
    #"traceroute": ["traceroute", "--mtu"],
}

def parse_traceroute_output(output):
    result = []
    lines = output.strip().splitlines()
    for line in lines:
        # Skip the header line
        if line.lower().startswith("traceroute"):
            continue
        hop_match = re.match(r'\s*(\d+)\s+(.+)', line)
        if hop_match:
            hop_num = int(hop_match.group(1))
            rest = hop_match.group(2)

            # Extract IP addresses
            ip_match = re.search(r'\(([\d\.]+)\)', rest)
            ip_address = ip_match.group(1) if ip_match else None

            # Extract RTT times
            rtt_times = re.findall(r'(\d+\.\d+)\s+ms', rest)

            result.append({
                'hop': hop_num,
                'ip': ip_address,
                'rtt_ms': [float(rtt) for rtt in rtt_times] if rtt_times else []
            })
    return result

def parse_nuttcp_output(output):
    result_dict = {}
    # Split on whitespace to get key=value pairs
    for pair in output.strip().split():
        if "=" in pair:
            key, value = pair.split("=")
            # Attempt to convert to float or int where possible
            try:
                if '.' in value:
                    result_dict[key] = float(value)
                else:
                    result_dict[key] = int(value)
            except ValueError:
                result_dict[key] = value
    return result_dict


def parse_ping_output(ping_output: str) -> dict[str, dict[str, Any]]:
    """Parses the output of a ping command to extract RTT and packet loss statistics."""
    sections = ping_output.strip().split("PING ")
    results: Dict[str, Dict[str, Any]] = {}

    for section in sections[1:]:  # Skip first empty split
        lines = section.split("\n")

        # Extract destination IP
        first_line: str = lines[0]
        match = re.search(r'\((.*?)\)', first_line)
        if not match:
            continue
        dest_ip: str = match.group(1)

        # Extract RTT statistics
        rtt_line: Optional[str] = next((l for l in lines if "rtt min/avg/max/mdev" in l), None)
        if rtt_line:
            rtt_values = re.findall(r"[0-9]+\.[0-9]+", rtt_line)
            if len(rtt_values) == 4:
                min_rtt, avg_rtt, max_rtt, mdev_rtt = map(float, rtt_values)
            else:
                continue
        else:
            continue

        # Extract packet loss percentage
        packet_loss_line: Optional[str] = next((l for l in lines if "packet loss" in l), None)
        match = re.search(r'([0-9]+)% packet loss', packet_loss_line)
        packet_loss: int = int(match.group(1)) if match else 0

        results[dest_ip] = {
            "min_rtt": min_rtt,
            "avg_rtt": avg_rtt,
            "max_rtt": max_rtt,
            "mdev_rtt": mdev_rtt,
            "packet_loss": packet_loss
        }

    return results

def setup_logger(output_dir):
    """Set up logging to file and console."""
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    log_file = os.path.join(log_dir, f"direct_tools_run_{timestamp}.log")

    logger = logging.getLogger("direct_tool_runner")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(file_formatter)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    ch.setFormatter(console_formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Logging to {log_file}")
    return logger

def run_tool(tool, base_cmd, host, output_dir, logger):
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    category_dir = os.path.join(output_dir, tool)
    os.makedirs(category_dir, exist_ok=True)

    output_file = f"{category_dir}/{host.replace(':', '_')}_{tool}_{timestamp}.json"

    cmd = list(base_cmd)
    # Add host where necessary
    if tool == "iperf3":
        # Insert host after '-c'
        c_index = cmd.index("-c")
        cmd.insert(c_index + 1, host)
        # Add other options after
        cmd.extend(["-P", "4", "-t", "30", "-i", "10", "-O", "10", "-J"])
    else:
        cmd.append(host)

    logger.info(f"Running {tool} to {host}")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
        output = result.stdout
        if tool == "ping":
            output = json.dumps(parse_ping_output(result.stdout), indent=4)
        elif tool == "nuttcp":
            output = json.dumps(parse_nuttcp_output(result.stdout), indent=4)
        elif tool == "traceroute":
            output = json.dumps(parse_traceroute_output(result.stdout), indent=4)

        with open(output_file, "w") as f:
            f.write(output)
        logger.info(f"Completed {tool} to {host}, output saved to {output_file}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {tool} on {host}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Run network tools directly and save output.")
    parser.add_argument("--hosts", nargs="+", required=True, help="Target hosts")
    parser.add_argument("--output-dir", default="./direct_results", help="Directory to save outputs")
    parser.add_argument("--tools", nargs="+", choices=list(TOOLS.keys()), default=list(TOOLS.keys()), help="Tools to run (default: all)")

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    logger = setup_logger(args.output_dir)

    logger.info(f"Starting direct network tool tests for hosts: {', '.join(args.hosts)}")
    logger.info(f"Tools to run: {', '.join(args.tools)}")

    for host in args.hosts:
        for tool in args.tools:
            run_tool(tool, TOOLS[tool], host, args.output_dir, logger)

    logger.info("All direct tests completed.")

if __name__ == "__main__":
    main()

