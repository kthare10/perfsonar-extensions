import json
import argparse

class PSConfigBuilder:
    """
    A builder class for generating and updating psconfig.json files for perfSONAR tests.
    Reads a base config, adds test definitions, groups, schedules, and tasks for given source/destination pairs.
    Optionally supports remote archive server configuration.
    """

    def __init__(self, base_config_file: str = "./psconfig_base.json", output_file: str = "./psconfig.json"):
        """
        Initialize the PSConfigBuilder.

        Args:
            base_config_file (str): Path to the base psconfig file.
            output_file (str): Path to the output psconfig file.
        """
        self.base_config_file = base_config_file
        self.output_file = output_file


    def add_tests(
        self,
        host_list: list[tuple[str, str]],
        parallel_streams: int = None,
        remote: str = None,
        add_tests: bool = True,
        minimal: bool = True,
        schedule_interval: str = "10M"
    ):
        """
        Add perfSONAR tests to the psconfig file for the given source and destination.

        Args:
            host_list (list of tuples): List of (name, IP) pairs for source and destination addresses.
            parallel_streams (int, optional): Number of parallel streams for throughput tests.
            remote (str, optional): Remote archive server URL.
            add_tests (bool, optional): Whether to add tests or just update addresses/groups.
            minimal (bool, optional): Whether to add minimal tasks for the tests.
            schedule_interval (str, optional): Schedule interval, one of "10M", "2H", "4H", "6H". Default is "10M".
        """
        # Load the base config file
        with open(self.base_config_file, "r") as f:
            config = json.load(f)

        # If remote archive server is provided, add remote_http_archive to config
        if remote:
            config["archives"]["remote_http_archive"] = {
                "archiver": "http",
                "data": {
                    "schema": 3,
                    "_url": f"https://{remote}/logstash",
                    "verify-ssl": False,
                    "op": "put",
                    "_headers": {
                        "x-ps-observer": "{% scheduled_by_address %}",
                        "content-type": "application/json"
                    }
                },
                "_meta": {
                    "esmond_url": f"https://{remote}/esmond/perfsonar/archive/"
                }
            }

        for (name, ip) in host_list:
            config["addresses"][name] = {"address": ip}

        # Collect all address names for mesh group
        address_names = list(config["addresses"].keys())
        # Assuming the first address is central-TOKY and the second is remote-MAX
        # to match the user's scenario. Adjust as needed.
        source_name = address_names[0] if len(address_names) > 0 else ""
        dest_name = address_names[1] if len(address_names) > 1 else ""

        # Define mesh group for all addresses
        config["groups"].update({
            "all_mesh": {
                "type": "mesh",
                "addresses": [{"name": name} for name in address_names]
            }
        })

        # Supported schedule intervals
        valid_intervals = {"10M": "PT10M", "2H": "PT2H", "4H": "PT4H", "6H": "PT6H"}
        if schedule_interval not in valid_intervals:
            raise ValueError(f"Invalid schedule_interval '{schedule_interval}'. Must be one of {list(valid_intervals.keys())}.")
        interval_str = valid_intervals[schedule_interval]

        if not add_tests:
            # Write the updated config to the output file and return if not adding tests
            with open(self.output_file, "w") as f:
                json.dump(config, f, indent=4)
            return

        # Define common source/dest mapping for readability
        forward_source = "{% address[0] %}"
        forward_dest = "{% address[1] %}"

        # Add schedules for the tests
        config["schedules"].update({
            f"{source_name}_{dest_name}_schedule_PT{schedule_interval}": {
                "repeat": interval_str,
                "sliprand": True,
                "slip": interval_str
            }
        })

        # Add test definitions
        config["tests"].update({
            # Forward Throughput
            f"{source_name}_{dest_name}_throughput": {
                "type": "throughput",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest,
                    "duration": "PT60S",
                    "interval": "PT10S",
                    "omit": "PT10S",
                    **({"parallel": parallel_streams} if parallel_streams else {})
                }
            },
            # Reverse Throughput
            f"{source_name}_{dest_name}_throughput_reverse": {
                "type": "throughput",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest,
                    "duration": "PT60S",
                    "interval": "PT10S",
                    "omit": "PT10S",
                    "reverse": True,
                    **({"parallel": parallel_streams} if parallel_streams else {})
                }
            },
            # Forward Latency
            f"{source_name}_{dest_name}_latencybg": {
                "type": "latencybg",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest,
                    "flip": False
                }
            },
            # Reverse Latency
            f"{source_name}_{dest_name}_latencybg_reverse": {
                "type": "latencybg",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest,
                    "flip": True
                }
            },
            # Forward Trace
            f"{source_name}_{dest_name}_trace": {
                "type": "trace",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest
                }
            },
            # Forward RTT
            f"{source_name}_{dest_name}_rtt": {
                "type": "rtt",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest
                }
            },
            # Forward MTU
            f"{source_name}_{dest_name}_mtu": {
                "type": "mtu",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest
                }
            },
            # Forward Clock
            f"{source_name}_{dest_name}_clock": {
                "type": "clock",
                "spec": {
                    "source": forward_source,
                    "dest": forward_dest
                }
            }
        })

        if not minimal:
            # Full task set, including traces
            config["tasks"].update({
                f"{source_name}_{dest_name}_task_throughput": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_throughput",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Throughput Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{dest_name}_{source_name}_task_throughput_reverse": {
                    "group": "all_mesh",
                    "test": f"{dest_name}_{source_name}_throughput_reverse",
                    "schedule": f"{dest_name}_{source_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Reverse Throughput Tests {dest_name} to {source_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_latencybg": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_latencybg",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Latency Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{dest_name}_{source_name}_task_latencybg_reverse": {
                    "group": "all_mesh",
                    "test": f"{dest_name}_{source_name}_latencybg_reverse",
                    "schedule": f"{dest_name}_{source_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Reverse Latency Tests {dest_name} to {source_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_trace": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_trace",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Traceroute Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_rtt": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_rtt",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"RTT Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_mtu": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_mtu",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"MTU Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_clock": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_clock",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Clock Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                }
            })
        else:
            # Minimal task set
            config["tasks"].update({
                f"{source_name}_{dest_name}_task_throughput": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_throughput",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Throughput Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_throughput_reverse": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_throughput_reverse",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Reverse Throughput Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_latencybg": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_latencybg",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Latency Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_latencybg_reverse": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_latencybg_reverse",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Reverse Latency Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_trace": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_trace",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Traceroute Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_rtt": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_rtt",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"RTT Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_mtu": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_mtu",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"MTU Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                },
                f"{source_name}_{dest_name}_task_clock": {
                    "group": "all_mesh",
                    "test": f"{source_name}_{dest_name}_clock",
                    "schedule": f"{source_name}_{dest_name}_schedule_PT{schedule_interval}",
                    "archives": ["http_archive", "remote_http_archive"] if remote else ["http_archive"],
                    "reference": { "display-task-name": f"Clock Tests {source_name} to {dest_name}", "display-task-group": ["Automated Tests"] }
                }
            })

        # Write the updated config to the output file
        with open(self.output_file, "w") as f:
            json.dump(config, f, indent=4)

if __name__ == "__main__":
    # Parse command line arguments for source/destination info and config file paths
    parser = argparse.ArgumentParser(description="Add tests to psconfig.json")
    # Accept a list of hosts and IPs for sources and destinations
    parser.add_argument("--host_list", nargs="+", metavar=("NAME", "IP"), help="List of host name/IP pairs (e.g. --host_list host1 1.2.3.4 host1 5.6.7.8)")
    parser.add_argument("--base_config_file", type=str, default="./psconfig_base.json", help="Path to the base psconfig file")
    parser.add_argument("--output_file", type=str, default="./psconfig.json", help="Path to the output psconfig file")
    parser.add_argument("--remote", type=str, help="Remote Archive server")
    parser.add_argument("--parallel_streams", type=int, help="Number of parallel streams for throughput tests")
    parser.add_argument("--no_add_tests", action="store_false", dest="add_tests",
                        help="If set, only update addresses/groups without adding tests")
    parser.add_argument("--minimal", action="store_false", dest="minimal",
                        help="If set, only add minimal tasks")
    parser.add_argument("--schedule_interval", type=str, choices=["10M", "2H", "4H", "6H"], default="10M",
                        help="Schedule interval for tests (default: 10M)")
    args = parser.parse_args()

    # Convert flat host_list argument to list of tuples
    # Example: ["host1", "1.2.3.4", "host2", "5.6.7.8"] -> [("host1", "1.2.3.4"), ("host2", "5.6.7.8")]
    if args.host_list:
        if len(args.host_list) % 2 != 0:
            raise ValueError("host_list must contain pairs of NAME and IP")
        args.host_list = [(args.host_list[i], args.host_list[i+1]) for i in range(0, len(args.host_list), 2)]

    # Create builder and add tests based on arguments
    builder = PSConfigBuilder(base_config_file=args.base_config_file, output_file=args.output_file)
    builder.add_tests(
        host_list=args.host_list,
        parallel_streams=args.parallel_streams,
        remote=args.remote,
        add_tests=args.add_tests,
        minimal=args.minimal,
        schedule_interval=args.schedule_interval
    )