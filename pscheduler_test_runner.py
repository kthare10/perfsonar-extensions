import argparse
import json
import subprocess
import os
from datetime import datetime, timezone
import sys
import logging

# Available tools categorized
AVAILABLE_TESTS = {
    "latency": ["owping", "twping", "halfping"],
    "rtt": ["ping", "tcpping"],
    "throughput": ["iperf3"],
    "trace": ["traceroute", "tracepath"],
    "mtu": ["fwmtu"],
    "clock": ["psclock"]
}

# Flatten all tool categories
ALL_TOOLS = sorted(list(AVAILABLE_TESTS.keys()))

# Optional: Custom command arguments for specific tools
CUSTOM_TEST_ARGS = {
    "latency": [],
    "rtt": [],
    "throughput": ["-P", "4", "-t", "60"],
    "trace": [],
    "mtu": [],
    "clock": [],
    # Add other test-specific extra args if needed
}

IPERF_ARGS = ["-i", "10", "-O", "10"]


def send_file(url, filepath, category, timestamp_utc):
    import requests  # Import locally to avoid global dependency
    try:
        with open(filepath, 'r') as f:
            content = json.load(f)
        payload = {
            "timestamp_utc": timestamp_utc,
            "category": category,
            "filename": os.path.basename(filepath),
            "content": content
        }
        headers = {
            "Content-Type": "application/json"
        }
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            print(f"Pushed: {filepath}")
        else:
            print(f"Push failed for {filepath}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Error pushing {filepath}: {e}")


def setup_logger(output_dir):
    """Configure logger with file and console output."""
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp_utc = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    log_file = os.path.join(log_dir, f"pscheduler_run_{timestamp_utc}.log")

    logger = logging.getLogger("pscheduler_runner")
    logger.setLevel(logging.DEBUG)

    # File handler (DEBUG)
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(file_formatter)

    # Console handler (INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    ch.setFormatter(console_formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Logging to {log_file}")
    return logger


def run_pscheduler_test(test, tool, host, output_dir, logger, archive, url, reverse=False):
    timestamp_utc = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    category_dir = os.path.join(output_dir, test)
    os.makedirs(category_dir, exist_ok=True)

    suffix = "reverse" if reverse else ""
    output_file = f"{category_dir}/{host.replace(':', '_')}_{tool}_{timestamp_utc}_{suffix}.json"

    # Base pscheduler command
    if archive:
        cmd = [
            "pscheduler", "task", "--archive", f"@{archive}",
            "--tool", tool,
            "--format", "json",
            "--output", output_file,
            test, "--dest", host
        ]
    else:
        cmd = [
            "pscheduler", "task",
            "--tool", tool,
            "--format", "json",
            "--output", output_file,
            test, "--dest", host
        ]

    # Add custom arguments if defined for tool
    extra_args = CUSTOM_TEST_ARGS.get(test, [])
    if extra_args:
        cmd.extend(extra_args)

    if tool == "iperf3":
        cmd.extend(IPERF_ARGS)

    if reverse and test in ["throughput", "latency"]:
        cmd.append("--reverse")

    logger.info(f"Running Test - {test} using {tool} to {host} reverse status: {reverse}")
    logger.debug(f"Command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        if url:
            send_file(url, output_file, test, timestamp_utc)
        logger.info(f"Completed {test} to {host}, output: {output_file}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {test} on {host}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Run pscheduler tests between hosts and save JSON output.")
    parser.add_argument("--hosts", nargs="+", required=True, help="List of destination hosts")
    parser.add_argument("--output-dir", default="./pscheduler_results", help="Directory to save JSON results")
    parser.add_argument("--tests", nargs="+", choices=ALL_TOOLS, default=ALL_TOOLS, help="Tests to run (default: all available tests)")
    parser.add_argument("--list-tests", action="store_true", help="List all available tests and exit")
    parser.add_argument("--reverse", action="store_true", help="Additionally run throughput tests in reverse direction")
    parser.add_argument("--archive", type=str, help="Location of the archive config")
    parser.add_argument("--url", type=str, help="Remote Archive server url")

    args = parser.parse_args()

    # List available tests
    if args.list_tests:
        print("\nAvailable Tests:")
        for category, tools in AVAILABLE_TESTS.items():
            print(f"\n{category.capitalize()} Tests: {', '.join(tools)}")
        sys.exit(0)

    os.makedirs(args.output_dir, exist_ok=True)
    logger = setup_logger(args.output_dir)

    logger.info(f"Starting pscheduler tests for hosts: {', '.join(args.hosts)}")
    logger.info(f"Tests to run: {', '.join(args.tests)}")

    for host in args.hosts:
        for test in args.tests:
            tools = AVAILABLE_TESTS.get(test)
            if tools:
                for t in tools:
                    run_pscheduler_test(test, t, host, args.output_dir, logger, args.archive,
                                        args.url)

                    # Run reverse test if requested and this is a throughput test
                    if True and test in ["throughput", "latency"] and t not in ["halfping"]:
                        run_pscheduler_test(
                            test, t, host,
                            args.output_dir, logger,
                            args.archive, args.url,
                            reverse=True
                        )

    #run_speedtest(output_dir=args.output_dir, logger=logger, url=args.url)

    logger.info("All tests completed.")


def run_speedtest(output_dir, logger, url=None):
    timestamp_utc = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    output_file = os.path.join(output_dir, f"speedtest_{timestamp_utc}.json")

    logger.info("Running speedtest CLI...")

    try:
        result = subprocess.run(
            ["speedtest", "--accept-license", "--accept-gdpr", "-f", "json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )

        with open(output_file, "w") as f:
            f.write(result.stdout)

        logger.info(f"Speedtest completed. Results saved to: {output_file}")

        if url:
            send_file(url, output_file, "speedtest", timestamp_utc)

    except subprocess.CalledProcessError as e:
        logger.error(f"Speedtest failed: {e.stderr}")


if __name__ == "__main__":
    main()
