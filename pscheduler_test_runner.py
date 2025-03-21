import argparse
import subprocess
import os
from datetime import datetime, timezone
import sys
import logging

# Available tools categorized
AVAILABLE_TESTS = {
    "latency": ["owping", "twping", "halfping"],
    "rtt": ["ping", "tcpping", "twping"],
    "throughput": ["iperf3", "nuttcp", "ethr"],
    "trace": ["traceroute", "paris-traceroute", "tracepath"],
    "mtu": ["fwmtu"],
    "clock": ["psclock"]
}

# Flatten all tool categories
ALL_TOOLS = sorted(list(AVAILABLE_TESTS.keys()))

# Optional: Custom command arguments for specific tools
CUSTOM_TEST_ARGS = {
    "latency": [],
    "rtt": [],
    "throughput": ["--parallel", "4"],
    "trace": [],
    "mtu": [],
    "clock": [],
    # Add other test-specific extra args if needed
}

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

def run_pscheduler_test(test, tool, host, output_dir, logger):
    timestamp_utc = datetime.utcnow().strftime('%Y%m%d-%H%M%SZ')
    category_dir = os.path.join(output_dir, test)
    os.makedirs(category_dir, exist_ok=True)

    output_file = f"{category_dir}/{host.replace(':', '_')}_{tool}_{timestamp_utc}.json"

    # Base pscheduler command
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

    logger.info(f"Running Test - {test} using {tool} to {host}")
    logger.debug(f"Command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"Completed {test} to {host}, output: {output_file}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {test} on {host}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Run pscheduler tests between hosts and save JSON output.")
    parser.add_argument("--hosts", nargs="+", required=True, help="List of destination hosts")
    parser.add_argument("--output-dir", default="./pscheduler_results", help="Directory to save JSON results")
    parser.add_argument("--tests", nargs="+", choices=ALL_TOOLS, default=ALL_TOOLS, help="Tests to run (default: all available tests)")
    parser.add_argument("--list-tests", action="store_true", help="List all available tests and exit")

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
                    run_pscheduler_test(test, t, host, args.output_dir, logger)

    logger.info("All tests completed.")

if __name__ == "__main__":
    main()
