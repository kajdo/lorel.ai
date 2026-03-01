"""Pod lifecycle management for Lorel.ai RunPod setup."""

import time
from datetime import datetime
from typing import Optional, Tuple

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .api_client import RunPodAPIClient, Pod

console = Console()


class PodManager:
    """Manages pod lifecycle (create, wait, terminate)."""

    def __init__(self, api_client: RunPodAPIClient):
        self.api_client = api_client
        self.current_pod_id: Optional[str] = None

    def create_pod(
        self,
        docker_image: str,
        gpu_type_id: str,
        cloud_type: str = "SECURE",
        is_spot: bool = False,
        container_disk_gb: int = 50,
        public_key: Optional[str] = None
    ) -> Pod:
        """Create a new pod with the specified configuration."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"kokoro-pod-{timestamp}"

        env = {}
        if public_key:
            env["PUBLIC_KEY"] = public_key

        console.print(f"[cyan]Creating pod '{name}'...[/cyan]")
        console.print(f"  [dim]Image: {docker_image}[/dim]")
        console.print(f"  [dim]GPU: {gpu_type_id}[/dim]")
        console.print(f"  [dim]Cloud: {cloud_type}{' (Spot)' if is_spot else ''}[/dim]")
        if public_key:
            console.print(f"  [dim]SSH: Certificate authentication configured[/dim]")
        pod = self.api_client.create_pod(
            name=name,
            docker_image=docker_image,
            gpu_type_id=gpu_type_id,
            gpu_count=1,
            cloud_type=cloud_type,
            container_disk_gb=container_disk_gb,
            is_spot=is_spot,
            env=env if env else None
        )

        self.current_pod_id = pod.id
        console.print(f"[green]Pod created: {pod.id}[/green]")

        return pod

    def wait_for_running(
        self,
        pod_id: str,
        timeout: int = 600,
        poll_interval: int = 5
    ) -> Tuple[bool, Optional[Pod]]:
        """Wait for pod to reach RUNNING state with public IP.

        Returns:
            Tuple of (success, pod or error message)
        """
        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Waiting for pod to start...", total=None)

            while time.time() - start_time < timeout:
                try:
                    pod = self.api_client.get_pod(pod_id)

                    if pod.desired_status == "RUNNING" and pod.public_ip:
                        # Try to get SSH port - first from port_mappings, then GraphQL fallback
                        ssh_port = pod.ssh_port
                        if not ssh_port:
                            ssh_port = self.api_client.get_pod_ssh_port_from_graphql(pod_id)
                        
                        if ssh_port and pod.public_ip:
                            progress.update(task, description="[green]Pod is running![/green]")
                            return True, pod

                    if pod.desired_status in ["EXITED", "TERMINATED", "CREATED"]:
                        progress.update(task, description=f"[red]Pod in unexpected state: {pod.desired_status}[/red]")
                        return False, pod

                    # Update status message
                    status_msg = f"Waiting for pod... (status: {pod.desired_status})"
                    if not pod.public_ip:
                        status_msg += " [dim]waiting for IP[/dim]"
                    elif not pod.ssh_port:
                        status_msg += f" [dim]IP: {pod.public_ip}, checking SSH port...[/dim]"
                    else:
                        status_msg += f" [dim]IP: {pod.public_ip}, SSH: {pod.ssh_port}[/dim]"
                    progress.update(task, description=status_msg)
                except Exception as e:
                    progress.update(task, description=f"[yellow]Error checking pod status: {e}[/yellow]")

                time.sleep(poll_interval)

            progress.update(task, description="[red]Timeout waiting for pod to start[/red]")
            return False, None
    def terminate_pod(self, pod_id: Optional[str] = None) -> bool:
        """Terminate a pod."""
        target_id = pod_id or self.current_pod_id
        if not target_id:
            console.print("[yellow]No pod to terminate[/yellow]")
            return True

        console.print(f"[cyan]Terminating pod {target_id}...[/cyan]")
        success = self.api_client.terminate_pod(target_id)

        if success:
            console.print("[green]Pod terminated[/green]")
            if target_id == self.current_pod_id:
                self.current_pod_id = None
        else:
            console.print("[red]Failed to terminate pod[/red]")

        return success

    def get_running_pods(self) -> list:
        """Get all running pods."""
        try:
            pods = self.api_client.get_pods()
            return [p for p in pods if p.desired_status == "RUNNING"]
        except Exception as e:
            console.print(f"[red]Failed to get pods: {e}[/red]")
            return []

    def terminate_all_pods(self) -> int:
        """Terminate all running pods. Returns count of terminated pods."""
        running_pods = self.get_running_pods()
        terminated = 0

        for pod in running_pods:
            if self.api_client.terminate_pod(pod.id):
                console.print(f"[green]Terminated: {pod.id} ({pod.name})[/green]")
                terminated += 1
            else:
                console.print(f"[red]Failed to terminate: {pod.id}[/red]")

        return terminated
