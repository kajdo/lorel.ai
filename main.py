#!/usr/bin/env python3
"""Lorel.ai RunPod Setup - Main entry point.

Usage:
    python main.py init      # Interactive .env setup
    python main.py deploy    # Deploy pod (with optional --spot flag)
    python main.py stop      # Stop all running pods
"""

import argparse
import signal
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from modules.config import Config
from modules.api_client import RunPodAPIClient, NoInstancesAvailableError
from modules.pod_manager import PodManager
from modules.gpu_selector import select_all_candidate_gpus, display_gpu_options
from modules.ssh_tunnel import SSHTunnel
from modules.init import run_interactive_setup

console = Console()

# Global references for cleanup
_pod_manager: Optional[PodManager] = None
_ssh_tunnel: Optional[SSHTunnel] = None
_current_pod_id: Optional[str] = None


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        console.print("\n\n[yellow]Received interrupt signal. Cleaning up...[/yellow]")
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def cleanup():
    """Clean up resources."""
    global _ssh_tunnel, _pod_manager, _current_pod_id

    if _ssh_tunnel:
        _ssh_tunnel.stop_all()
        _ssh_tunnel = None

    if _pod_manager and _current_pod_id:
        _pod_manager.terminate_pod(_current_pod_id)
        _current_pod_id = None


def cmd_init(args):
    """Run interactive setup wizard."""
    run_interactive_setup()


def cmd_deploy(args):
    """Deploy a new pod."""
    global _pod_manager, _ssh_tunnel, _current_pod_id

    # Load configuration
    config = Config.load()

    # Validate configuration
    is_valid, error = config.validate()
    if not is_valid:
        console.print(f"[red]Configuration error: {error}[/red]")
        console.print("Run [cyan]python main.py init[/cyan] to configure.")
        return 1

    # Determine cloud type and cost
    is_spot = args.spot
    cloud_type = "COMMUNITY" if is_spot else "SECURE"
    max_cost = config.max_cost_per_hour

    # Adjust default cost for spot
    if is_spot and config.max_cost_per_hour > 0.5:
        console.print("[dim]Note: Using lower max cost for spot instances ($0.30/hr)[/dim]")
        max_cost = min(config.max_cost_per_hour, 0.3)

    # Initialize API client
    api_client = RunPodAPIClient(config.api_key)
    _pod_manager = PodManager(api_client)

    # Get available GPUs
    console.print("[cyan]Fetching available GPUs...[/cyan]")
    try:
        gpu_types = api_client.get_gpu_types()
    except Exception as e:
        console.print(f"[red]Failed to fetch GPU types: {e}[/red]")
        return 1

    # Display options
    display_gpu_options(
        gpu_types,
        min_vram_gb=config.min_vram_gb,
        max_cost=max_cost,
        cloud_type=cloud_type,
        is_spot=is_spot
    )

    # Get all candidate GPUs (sorted by price)
    candidates = select_all_candidate_gpus(
        gpu_types,
        min_vram_gb=config.min_vram_gb,
        max_cost=max_cost,
        cloud_type=cloud_type,
        is_spot=is_spot
    )
    
    if not candidates:
        console.print("[red]No GPUs match the criteria[/red]")
        return 1
    
    console.print(f"[dim]Found {len(candidates)} candidate GPU(s), will try in price order...[/dim]")

    # Try each GPU in order until one succeeds
    pod = None
    for i, selection in enumerate(candidates):
        console.print(f"\n[green]Trying GPU {i+1}/{len(candidates)}: {selection.display_name} @ ${selection.cost_per_hour:.3f}/hr[/green]")
        
        try:
            pod = _pod_manager.create_pod(
                docker_image=config.docker_image,
                gpu_type_id=selection.gpu_type_id,
                cloud_type=cloud_type,
                is_spot=is_spot,
                container_disk_gb=config.container_disk_gb,
                ssh_password=config.ssh_password
            )
            _current_pod_id = pod.id
            break  # Success!
            
        except NoInstancesAvailableError as e:
            console.print(f"[yellow]No instances available for {selection.display_name}, trying next GPU...[/yellow]")
            continue
        
        except Exception as e:
            console.print(f"[red]Failed to create pod: {e}[/red]")
            return 1
    
    if pod is None:
        console.print("[red]Failed to create pod: No instances available for any GPU type[/red]")
        return 1

    # Wait for pod to be running
    console.print(f"\n[cyan]Waiting for pod to start (this may take a few minutes)...[/cyan]")
    success, result = _pod_manager.wait_for_running(pod.id)

    if not success:
        console.print("[red]Pod failed to start[/red]")
        cleanup()
        return 1

    if result is None:
        console.print("[red]Pod status unavailable[/red]")
        cleanup()
        return 1

    pod = result
    console.print(f"[green]Pod is running![/green]")
    console.print(f"  [dim]IP: {pod.public_ip}[/dim]")
    console.print(f"  [dim]SSH Port: {pod.ssh_port}[/dim]")

    # Setup SSH tunnel
    if not pod.public_ip or not pod.ssh_port:
        console.print("[red]Pod missing IP or SSH port[/red]")
        cleanup()
        return 1

    # RunPod uses password auth, not SSH keys (key must be registered in RunPod UI)
    _ssh_tunnel = SSHTunnel(
        pod_ip=pod.public_ip,
        ssh_port=pod.ssh_port,
        ssh_key_path=None,  # Don't use local SSH key - RunPod requires password
        password=config.ssh_password
    )

    success, message, local_ip = _ssh_tunnel.start_tunnels()
    if not success:
        console.print(f"[red]Failed to create SSH tunnels: {message}[/red]")
        cleanup()
        return 1

    _ssh_tunnel.display_connection_info(local_ip)

    # Setup signal handlers
    setup_signal_handlers()

    # Keep tunnels alive
    try:
        _ssh_tunnel.wait()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

    return 0


def cmd_stop(args):
    """Stop all running pods."""
    config = Config.load()

    if not config.api_key:
        console.print("[red]No API key configured. Run 'python main.py init' first.[/red]")
        return 1

    api_client = RunPodAPIClient(config.api_key)
    pod_manager = PodManager(api_client)

    running_pods = pod_manager.get_running_pods()

    if not running_pods:
        console.print("[green]No running pods found.[/green]")
        return 0

    console.print(f"[cyan]Found {len(running_pods)} running pod(s)[/cyan]")

    terminated = pod_manager.terminate_all_pods()
    console.print(f"[green]Terminated {terminated} pod(s)[/green]")

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Lorel.ai RunPod Setup - Deploy Kokoro TTS on RunPod GPUs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py init              # Interactive setup
    python main.py deploy            # Deploy on Secure Cloud
    python main.py deploy --spot     # Deploy on Spot (cheaper)
    python main.py stop              # Stop all running pods
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    subparsers.add_parser("init", help="Interactive .env setup")

    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy a new pod")
    deploy_parser.add_argument(
        "--spot",
        action="store_true",
        help="Deploy as Spot instance (Community Cloud, cheaper)"
    )

    # Stop command
    subparsers.add_parser("stop", help="Stop all running pods")

    args = parser.parse_args()

    # Default to deploy if no command specified
    if args.command is None:
        console.print(Panel.fit(
            "[bold cyan]Lorel.ai RunPod Setup[/bold cyan]\n\n"
            "[dim]Commands:[/dim]\n"
            "  init     Interactive configuration setup\n"
            "  deploy   Deploy a new GPU pod\n"
            "  stop     Stop all running pods\n\n"
            "[dim]Run 'python main.py <command> --help' for details[/dim]"
        ))
        return 0

    # Execute command
    commands = {
        "init": cmd_init,
        "deploy": cmd_deploy,
        "stop": cmd_stop
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
