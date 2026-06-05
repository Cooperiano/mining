#!/usr/bin/env python3
"""Miner control — manage self-hosted and vast.ai Pearl miners.

Usage:
  minerctl list                          List all miners (hosted + vast)
  minerctl dashboard [-w SECONDS]        Live monitoring dashboard

  minerctl host add <ip> <port> [...]    Register a self-hosted miner
  minerctl host remove <name>            Remove a hosted miner
  minerctl host list                     List hosted miners
  minerctl host deploy <name>            Deploy miner to hosted machine
  minerctl host start <name>             Start miner on hosted machine
  minerctl host stop <name>              Stop miner on hosted machine
  minerctl host restart <name>           Restart miner on hosted machine
  minerctl host status <name>            Check miner status on hosted machine

  minerctl vast list                     List vast.ai instances
  minerctl vast search [--gpu GPU]       Search vast.ai for offers
  minerctl vast rent <offer_id>          Create an instance from an offer
  minerctl vast deploy <instance_id>     Deploy miner to vast.ai instance
  minerctl vast kill <instance_id>       Destroy a vast.ai instance
  minerctl vast ssh <instance_id>        Get SSH URL for an instance
  minerctl vast wait <instance_id>       Wait for instance to be ready
  minerctl vast autodeploy               Run full autodeploy cycle
  minerctl vast scan                     Scan for cost-effective offers (TH/$/hr)
  minerctl vast interruptible            Scan for interruptible offers (DLPerf/$)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from manager import hosts, vast, dashboard


def cmd_list(_args: argparse.Namespace) -> None:
    print(hosts.list_hosts())
    print()
    print(vast.list_instances())


def cmd_dashboard(args: argparse.Namespace) -> None:
    if args.watch and args.watch > 0:
        try:
            while True:
                frame = dashboard.get_dashboard()
                print(f"\033[H\033[J{frame}")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print()
    else:
        print(dashboard.get_dashboard())


def cmd_host_add(args: argparse.Namespace) -> None:
    print(hosts.add(args.ip, args.port, args.label, args.gpus, args.gpu_type))


def cmd_host_remove(args: argparse.Namespace) -> None:
    print(hosts.remove(args.name))


def cmd_host_list(_args: argparse.Namespace) -> None:
    print(hosts.list_hosts())


def cmd_host_deploy(args: argparse.Namespace) -> None:
    print(f"Deploying to {args.name}...")
    print(hosts.deploy(args.name))


def cmd_host_start(args: argparse.Namespace) -> None:
    print(hosts.start(args.name))


def cmd_host_stop(args: argparse.Namespace) -> None:
    print(hosts.stop(args.name))


def cmd_host_restart(args: argparse.Namespace) -> None:
    print(hosts.restart(args.name))


def cmd_host_status(args: argparse.Namespace) -> None:
    print(hosts.status(args.name))


def cmd_vast_list(_args: argparse.Namespace) -> None:
    print(vast.list_instances())


def cmd_vast_search(args: argparse.Namespace) -> None:
    print(vast.search_offers(
        gpu_name=args.gpu,
        num_gpus=args.gpus,
        max_price=args.max_price,
        verified=not args.unverified,
        limit=args.limit,
    ))


def cmd_vast_rent(args: argparse.Namespace) -> None:
    print(vast.create_instance(
        offer_id=args.offer_id,
        image=args.image,
        disk=args.disk,
        onstart_cmd=args.onstart_cmd,
        direct=not args.no_direct,
    ))


def cmd_vast_deploy(args: argparse.Namespace) -> None:
    print(f"Deploying to {args.instance_id}...")
    print(vast.deploy_instance(args.instance_id))


def cmd_vast_kill(args: argparse.Namespace) -> None:
    print(vast.kill_instance(args.instance_id, args.reason or ""))


def cmd_vast_ssh(args: argparse.Namespace) -> None:
    print(vast.get_ssh_url(args.instance_id))


def cmd_vast_wait(args: argparse.Namespace) -> None:
    print(vast.wait_ready(args.instance_id, args.timeout))


def cmd_vast_autodeploy(args: argparse.Namespace) -> None:
    print(vast.autodeploy_cycle())


def cmd_vast_scan(_args: argparse.Namespace) -> None:
    """Scan vast.ai for cost-effective GPU offers (by TH/$/hr)."""
    print(vast.scan_cost_effective_offers())


def cmd_vast_interruptible(_args: argparse.Namespace) -> None:
    """Scan vast.ai for interruptible offers with high DLPerf efficiency."""
    print(vast.scan_interruptible_offers())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Miner control — manage self-hosted and vast.ai Pearl miners",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # --- list ---
    sub.add_parser("list", help="List all miners (hosted + vast)")

    # --- dashboard ---
    dash = sub.add_parser("dashboard", help="Live monitoring dashboard")
    dash.add_argument("-w", "--watch", type=int, default=0,
                      help="Refresh interval in seconds")

    # --- host ---
    host_p = sub.add_parser("host", help="Manage self-hosted miners")
    host_sub = host_p.add_subparsers(dest="host_command")

    h_add = host_sub.add_parser("add", help="Register a self-hosted miner")
    h_add.add_argument("ip", help="IP address")
    h_add.add_argument("port", type=int, help="SSH port")
    h_add.add_argument("--label", "-l", help="Friendly name for this miner")
    h_add.add_argument("--gpus", "-g", type=int, default=1, help="Number of GPUs")
    h_add.add_argument("--gpu-type", "-t", default="auto",
                       help="GPU type (e.g. 3080, 5090, 4060ti)")

    h_rm = host_sub.add_parser("remove", help="Remove a hosted miner")
    h_rm.add_argument("name", help="Label or IP of the miner")

    host_sub.add_parser("list", help="List hosted miners")

    h_dep = host_sub.add_parser("deploy", help="Deploy miner to hosted machine")
    h_dep.add_argument("name", help="Label or IP of the miner")

    h_start = host_sub.add_parser("start", help="Start miner on hosted machine")
    h_start.add_argument("name", help="Label or IP of the miner")

    h_stop = host_sub.add_parser("stop", help="Stop miner on hosted machine")
    h_stop.add_argument("name", help="Label or IP of the miner")

    h_restart = host_sub.add_parser("restart", help="Restart miner on hosted machine")
    h_restart.add_argument("name", help="Label or IP of the miner")

    h_stat = host_sub.add_parser("status", help="Check miner status on hosted machine")
    h_stat.add_argument("name", help="Label or IP of the miner")

    # --- vast ---
    vast_p = sub.add_parser("vast", help="Manage vast.ai instances")
    vast_sub = vast_p.add_subparsers(dest="vast_command")

    vast_sub.add_parser("list", help="List vast.ai instances")

    v_search = vast_sub.add_parser("search", help="Search vast.ai for GPU offers")
    v_search.add_argument("--gpu", default="RTX_5090", help="GPU model to search for")
    v_search.add_argument("--gpus", type=int, default=1,
                          help="Minimum GPUs per instance")
    v_search.add_argument("--max-price", type=float, help="Max price per hour")
    v_search.add_argument("--unverified", action="store_true",
                          help="Include unverified hosts")
    v_search.add_argument("--limit", "-l", type=int, default=20,
                          help="Max results to show")

    v_rent = vast_sub.add_parser("rent", help="Create instance from offer")
    v_rent.add_argument("offer_id", help="Offer ID from search")
    v_rent.add_argument("--image", default="nvidia/cuda:12.4.0-devel-ubuntu22.04",
                        help="Docker image")
    v_rent.add_argument("--disk", type=int, default=20,
                        help="Disk size in GB")
    v_rent.add_argument("--onstart-cmd", default="nvidia-smi",
                        help="Command to run on boot")
    v_rent.add_argument("--no-direct", action="store_true",
                        help="Disable direct SSH")

    v_dep = vast_sub.add_parser("deploy", help="Deploy miner to vast.ai instance")
    v_dep.add_argument("instance_id", help="Instance ID")

    v_kill = vast_sub.add_parser("kill", help="Destroy a vast.ai instance")
    v_kill.add_argument("instance_id", help="Instance ID")
    v_kill.add_argument("reason", nargs="?", help="Reason for killing")

    v_ssh = vast_sub.add_parser("ssh", help="Get SSH URL for an instance")
    v_ssh.add_argument("instance_id", help="Instance ID")

    v_wait = vast_sub.add_parser("wait", help="Wait for instance to be ready")
    v_wait.add_argument("instance_id", help="Instance ID")
    v_wait.add_argument("--timeout", "-t", type=int, default=300,
                        help="Timeout in seconds")

    v_auto = vast_sub.add_parser("autodeploy", help="Run full autodeploy cycle")

    v_scan = vast_sub.add_parser(
        "scan", help="Scan vast.ai for cost-effective GPU offers (by TH/$/hr)"
    )

    vast_sub.add_parser(
        "interruptible",
        help="Scan for interruptible offers with DLPerf/$ > threshold",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        ("list", None): cmd_list,
        ("dashboard", None): cmd_dashboard,
        ("host", "add"): cmd_host_add,
        ("host", "remove"): cmd_host_remove,
        ("host", "list"): cmd_host_list,
        ("host", "deploy"): cmd_host_deploy,
        ("host", "start"): cmd_host_start,
        ("host", "stop"): cmd_host_stop,
        ("host", "restart"): cmd_host_restart,
        ("host", "status"): cmd_host_status,
        ("vast", "list"): cmd_vast_list,
        ("vast", "search"): cmd_vast_search,
        ("vast", "rent"): cmd_vast_rent,
        ("vast", "deploy"): cmd_vast_deploy,
        ("vast", "kill"): cmd_vast_kill,
        ("vast", "ssh"): cmd_vast_ssh,
        ("vast", "wait"): cmd_vast_wait,
        ("vast", "autodeploy"): cmd_vast_autodeploy,
        ("vast", "scan"): cmd_vast_scan,
        ("vast", "interruptible"): cmd_vast_interruptible,
    }

    sub_cmd = getattr(args, "host_command", None) or getattr(args, "vast_command", None)
    key = (args.command, sub_cmd)
    handler = dispatch.get(key)

    if handler:
        handler(args)
    else:
        if args.command == "host":
            host_p.print_help()
        elif args.command == "vast":
            vast_p.print_help()
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
