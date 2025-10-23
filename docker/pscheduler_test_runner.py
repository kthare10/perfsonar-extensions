#!/usr/bin/env python3
import argparse
import json
import subprocess
import os
from datetime import datetime, timezone
import sys
import logging
from typing import List, Optional


from archiver_client import ArchiverClient, NodeRef, MeasurementRequest, ArchiverError, ArchiverHTTPError

# Available tests categorized by logical category -> supported tools
AVAILABLE_TESTS = {
    "latency": ["owping", "twping", "halfping"],
    "rtt": ["ping", "tcpping"],
    "throughput": ["iperf3"],
    "trace": ["traceroute", "tracepath"],
    "mtu": ["fwmtu"],
    "clock": ["psclock"]
}

# Test categories
ALL_TEST_CATEGORIES = sorted(list(AVAILABLE_TESTS.keys()))

# Optional: Custom command arguments for specific test categories
CUSTOM_TEST_ARGS = {
    "latency": [],
    "rtt": [],
    "throughput": ["-P", "4", "-t", "60"],
    "trace": [],
    "mtu": [],
    "clock": [],
}

# Extra args specifically for iperf3 (only applied when tool == iperf3)
IPERF_ARGS = ["-i", "10", "-O", "10"]


def setup_logger(output_dir):
    """Configure logger with file and console output."""
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp_utc = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    log_file = os.path.join(log_dir, f"pscheduler_run_{timestamp_utc}.log")

    logger = logging.getLogger("pscheduler_runner")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if main() is called more than once in a process
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Logging to {log_file}")
    return logger


def build_pscheduler_cmd(*, test, tool, host, output_file, reverse):
    """
    Build a pscheduler command. If tool is None, do NOT include '--tool'
    so that pscheduler chooses automatically.
    NOTE: archiver integration is handled by our client afterwards; we do NOT use --archive here.
    """
    base = ["pscheduler", "task"]

    if tool:
        base += ["--tool", tool]

    base += ["--format", "json", "--output", output_file, test, "--dest", host]

    # Category-level extra args
    extra_args = CUSTOM_TEST_ARGS.get(test, [])
    if extra_args:
        base.extend(extra_args)

    # Tool-specific extras (only when tool is explicit)
    if tool == "iperf3":
        base.extend(IPERF_ARGS)

    # Reverse when requested for categories that support it
    if reverse and test in ["throughput", "latency"]:
        base.append("--reverse")

    return base


def _coalesce(val: Optional[str], fallback: str) -> str:
    return val if val else fallback


def _default_src_noderef() -> NodeRef:
    """
    Best-effort local source identity:
      - IP from $HOST_IP if set, else hostname (acceptable for server if it tolerates non-IP strings)
      - name from $HOST_NAME if set, else system hostname
    """
    hostname = os.uname().nodename
    src_ip = _coalesce(os.environ.get("HOST_IP"), hostname)
    src_name = _coalesce(os.environ.get("HOST_NAME"), hostname)
    return NodeRef(ip=src_ip, name=src_name)


def _dst_noderef_from_host(host: str) -> NodeRef:
    """
    Use the CLI host for both ip and name (works whether it's hostname or IP).
    If you prefer a strict IP, resolve here (but resolution can block).
    """
    return NodeRef(ip=host, name=host)


def _category_to_method_name(category: str) -> str:
    # map category to ArchiverClient method
    return {
        "latency": "create_latency_measurement",
        "rtt": "create_rtt_measurement",
        "throughput": "create_throughput_measurement",
        "trace": "create_trace_measurement",
        "mtu": "create_mtu_measurement",
        "clock": "create_clock_measurement",
    }[category]


def archive_result_to_endpoints(
    archiver_urls: List[str],
    category: str,
    raw_json: dict,
    src: NodeRef,
    dst: NodeRef,
    reverse: bool,
    logger: logging.Logger,
) -> None:
    """
    Sends the raw pscheduler JSON to each archiver base URL using the matching endpoint.
    Uses environment vars ARCHIVER_BEARER / ARCHIVER_API_KEY if present for auth.
    """
    direction = "reverse" if reverse else "forward"
    req = MeasurementRequest(
        src=src,
        dst=dst,
        direction=direction,  # server uses this to label plots
        raw=raw_json,
        # ts and run_id are optional; server may set defaults/derive run_id
    )

    method_name = _category_to_method_name(category)

    for base_url in archiver_urls:
        client = ArchiverClient(base_url=base_url)  # auth picked up from env if set
        try:
            method = getattr(client, method_name)
            resp = method(req, upsert=True)  # keep upsert defaulting to True
            logger.info(f"Archived to {base_url} [{category}] OK: {resp if resp else 'no-content'}")
        except ArchiverHTTPError as e:
            logger.error(f"Archiver HTTP error ({base_url}): {e.status} {e.payload}")
        except ArchiverError as e:
            logger.error(f"Archiver client error ({base_url}): {e}")
        except Exception as e:
            logger.exception(f"Unexpected archiver error ({base_url}): {e}")


def run_pscheduler_test(
    test: str,
    tool: Optional[str],
    host: str,
    output_dir: str,
    logger: logging.Logger,
    archiver_urls: List[str],
    reverse: bool = False,
):
    timestamp_utc = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    category_dir = os.path.join(output_dir, test)
    os.makedirs(category_dir, exist_ok=True)

    suffix = "reverse" if reverse else "forward"
    tool_tag = tool if tool else "auto"
    output_file = os.path.join(
        category_dir,
        f"{host.replace(':', '_')}_{tool_tag}_{timestamp_utc}_{suffix}.json"
    )

    cmd = build_pscheduler_cmd(
        test=test, tool=tool, host=host, output_file=output_file, reverse=reverse
    )

    logger.info(f"Running {test} ({'auto' if tool is None else tool}) -> {host} reverse={reverse}")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        logger.info(f"Completed {test} ({tool_tag}) to {host}, output: {output_file}")

        # Load the pscheduler JSON once and ship to all archiver URLs, if any
        if archiver_urls:
            try:
                with open(output_file, "r") as f:
                    raw = json.load(f)
            except Exception as e:
                logger.error(f"Could not read output JSON ({output_file}): {e}")
                return

            src = _default_src_noderef()
            dst = _dst_noderef_from_host(host)
            archive_result_to_endpoints(
                archiver_urls=archiver_urls,
                category=test,
                raw_json=raw,
                src=src,
                dst=dst,
                reverse=reverse,
                logger=logger,
            )
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {test} ({tool_tag}) on {host}: {e}")


def _parse_archiver_urls(cli_value: Optional[List[str]]) -> List[str]:
    """
    Accepts:
      - --archiver-urls http://a http://b
      - or env ARCHIVER_URLS="http://a,https://b"
    """
    if cli_value and len(cli_value) > 0:
        return [u.rstrip("/") for u in cli_value if u.strip()]
    env_val = os.environ.get("ARCHIVER_URLS", "").strip()
    if env_val:
        return [u.strip().rstrip("/") for u in env_val.split(",") if u.strip()]
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Run pscheduler tests between hosts, save JSON output, and archive to the pscheduler-result-archiver."
    )
    parser.add_argument("--hosts", nargs="+", required=True,
                        help="List of destination hosts")
    parser.add_argument("--output-dir", default="./pscheduler_results",
                        help="Directory to save JSON results")
    parser.add_argument(
        "--tests", nargs="+", choices=ALL_TEST_CATEGORIES, default=ALL_TEST_CATEGORIES,
        help="Test categories to run (default: all)"
    )
    parser.add_argument("--list-tests", action="store_true",
                        help="List all available tests and exit")
    parser.add_argument("--reverse", action="store_true",
                        help="Also run reverse direction for throughput/latency")

    parser.add_argument("--archiver-urls", nargs="+",
                        help="One or more archiver base URLs (e.g., https://archiver.example.org http://localhost:8080). "
                             "Alternatively set ARCHIVER_URLS='url1,url2' env var.")

    # Tool selection controls
    parser.add_argument(
        "--tool-mode",
        choices=["auto", "all", "subset"],
        default="auto",
        help=(
            "auto: do not pass --tool (let pscheduler choose) [default]; "
            "all: run all tools for each selected test; "
            "subset: run only tools listed via --tools"
        ),
    )
    parser.add_argument(
        "--tools",
        nargs="+",
        help="When --tool-mode=subset, run only these tools (e.g., iperf3 ping twping)"
    )

    args = parser.parse_args()

    # List available tests/tools
    if args.list_tests:
        print("\nAvailable Tests/Tools:")
        for category, tools in AVAILABLE_TESTS.items():
            print(f"  {category}: {', '.join(tools)}")
        sys.exit(0)

    os.makedirs(args.output_dir, exist_ok=True)
    logger = setup_logger(args.output_dir)

    archiver_urls = _parse_archiver_urls(args.archiver_urls)
    if archiver_urls:
        logger.info(f"Archiver endpoints: {', '.join(archiver_urls)}")
        logger.info("Auth picked from env if set: ARCHIVER_BEARER and/or ARCHIVER_API_KEY")
    else:
        logger.warning("No archiver endpoints configured (use --archiver-urls or ARCHIVER_URLS). Results will only be saved to disk.")

    logger.info(f"Hosts: {', '.join(args.hosts)}")
    logger.info(f"Tests: {', '.join(args.tests)}")
    logger.info(f"Tool mode: {args.tool_mode}{' (' + ', '.join(args.tools) + ')' if args.tool_mode=='subset' and args.tools else ''}")

    # Prepare subset tool set (if requested)
    subset_tools = set(args.tools or []) if args.tool_mode == "subset" else None

    for host in args.hosts:
        for test in args.tests:
            supported_tools = AVAILABLE_TESTS.get(test, [])

            if args.tool_mode == "auto":
                # Do not pass --tool at all
                run_pscheduler_test(
                    test, None, host, args.output_dir, logger, archiver_urls,
                    reverse=False
                )
                if args.reverse and test in ["throughput", "latency"]:
                    run_pscheduler_test(
                        test, None, host, args.output_dir, logger, archiver_urls,
                        reverse=True
                    )

            elif args.tool_mode == "all":
                for tool in supported_tools:
                    run_pscheduler_test(
                        test, tool, host, args.output_dir, logger, archiver_urls,
                        reverse=False
                    )
                    if args.reverse and test in ["throughput", "latency"] and tool not in ["halfping"]:
                        run_pscheduler_test(
                            test, tool, host, args.output_dir, logger, archiver_urls,
                            reverse=True
                        )

            else:  # subset
                chosen = [t for t in supported_tools if t in subset_tools]
                if not chosen:
                    logger.warning(
                        f"No matching tools for test '{test}' with subset {sorted(subset_tools)}; skipping."
                    )
                    continue
                for tool in chosen:
                    run_pscheduler_test(
                        test, tool, host, args.output_dir, logger, archiver_urls,
                        reverse=False
                    )
                    if args.reverse and test in ["throughput", "latency"] and tool not in ["halfping"]:
                        run_pscheduler_test(
                            test, tool, host, args.output_dir, logger, archiver_urls,
                            reverse=True
                        )

    logger.info("All tests completed.")


# Optional: keep speedtest helper (unchanged except no archiver flag here)
def run_speedtest(output_dir, logger, archiver_urls: Optional[List[str]] = None):
    timestamp_utc = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
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

        if archiver_urls:
            try:
                raw = json.loads(result.stdout)
            except Exception as e:
                logger.error(f"Could not parse speedtest JSON: {e}")
                return
            src = _default_src_noderef()
            # speedtest isn't strictly src->dst pair, but we can name the remote as 'speedtest'
            dst = NodeRef(ip="speedtest", name="speedtest")
            archive_result_to_endpoints(
                archiver_urls=archiver_urls,
                category="throughput",  # or a dedicated 'speedtest' route if you add one later
                raw_json=raw,
                src=src,
                dst=dst,
                reverse=False,
                logger=logger,
            )

    except subprocess.CalledProcessError as e:
        logger.error(f"Speedtest failed: {e.stderr}")


if __name__ == "__main__":
    main()
