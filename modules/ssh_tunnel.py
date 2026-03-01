"""SSH tunnel management for Lorel.ai RunPod setup."""

import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

console = Console()


class SSHTunnel:
    """Manages SSH tunnels for accessing pod services."""

    def __init__(
        self,
        pod_ip: str,
        ssh_port: int,
        username: str = "root",
        ssh_key_path: Optional[str] = None
    ):
        self.pod_ip = pod_ip
        self.ssh_port = ssh_port
        self.username = username
        self.ssh_key_path = ssh_key_path or self.find_ssh_key()
        self.processes: List[Any] = []

        # Tunnel configuration
        self.tunnels = [
            {"local": 8880, "remote": 8880, "name": "Kokoro API"},
            {"local": 8881, "remote": 8881, "name": "Whisper Service"},
            {"local": 2222, "remote": 22, "name": "SSH"}
        ]

    @staticmethod
    def detect_local_ip() -> str:
        """Detect best local IP for binding. Try 0.0.0.0, fallback to 127.0.0.1."""
        # Try to bind to 0.0.0.0 for network-wide access
        try:
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_socket.bind(("0.0.0.0", 9999))
            test_socket.close()
            return "0.0.0.0"
        except Exception:
            return "127.0.0.1"

    @staticmethod
    def find_ssh_key() -> Optional[str]:
        """Find available SSH key."""
        key_paths = [
            os.path.expanduser("~/.ssh/id_ed25519"),
            os.path.expanduser("~/.ssh/id_rsa"),
            os.path.expanduser("~/.ssh/id_ecdsa"),
        ]

        for path in key_paths:
            if os.path.exists(path):
                return path

        return None

    def _build_ssh_command(self, tunnels: List[Dict], bind_addr: str) -> List[str]:
        """Build SSH command for tunnel creation - matches reference implementation."""
        ssh_cmd = [
            "ssh",
            "-4",
        ]

        # Add tunnel options
        for tunnel in tunnels:
            ssh_cmd.extend([
                "-L", f"{bind_addr}:{tunnel['local']}:127.0.0.1:{tunnel['remote']}"
            ])

        # Add SSH options (same order as reference)
        ssh_cmd.extend([
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "TCPKeepAlive=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectionAttempts=60",
            "-N",
            "-T",
            f"{self.username}@{self.pod_ip}",
            "-p", str(self.ssh_port)
        ])

        # Add key at the END (matches reference)
        if self.ssh_key_path:
            ssh_cmd.extend(["-i", self.ssh_key_path])

        return ssh_cmd
    def _create_tunnel_with_key(self, ssh_cmd: List[str]) -> subprocess.Popen:
        """Create SSH tunnel using key authentication."""
        console.print("[dim]Starting tunnel with SSH key...[/dim]")
        console.print(f"[dim]Command: {' '.join(ssh_cmd)}[/dim]")

        try:
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
            )

            # Give it a moment to start
            time.sleep(3)

            # Check if process exited immediately
            if process.poll() is not None:
                _, stderr = process.communicate()
                stderr_text = stderr.decode('utf-8', errors='ignore')
                console.print(f"[red]SSH stderr: {stderr_text}[/red]")
                raise RuntimeError(f"SSH process exited immediately (code {process.poll()}): {stderr_text}")

            console.print(f"[green]SSH tunnel process started (PID: {process.pid})[/green]")
            return process

        except Exception as e:
            raise RuntimeError(f"Failed to create SSH tunnel: {e}")

    def start_tunnels(self) -> Tuple[bool, str, str]:
        """Start SSH tunnels.

        Returns:
            Tuple of (success, message, local_ip)
        """
        local_ip = self.detect_local_ip()
        
        if not self.ssh_key_path:
            return False, "SSH key not found. Please set up SSH keys for authentication.", local_ip

        console.print(f"[dim]Connecting to {self.username}@{self.pod_ip}:{self.ssh_port}[/dim]")
        console.print(f"[dim]Auth: SSH key: {self.ssh_key_path}[/dim]")

        for bind_addr in [local_ip, "127.0.0.1"]:
            try:
                console.print(f"[dim]Trying to bind to {bind_addr}...[/dim]")
                ssh_cmd = self._build_ssh_command(self.tunnels, bind_addr)

                process = self._create_tunnel_with_key(ssh_cmd)
                self.processes.append(process)

                # Verify process is still alive
                time.sleep(2)
                is_alive = True
                
                if hasattr(process, 'poll'):  # subprocess.Popen
                    if process.poll() is not None:
                        is_alive = False
                elif callable(getattr(process, 'isalive', None)):  # pexpect.spawn
                    if not process.isalive():  # type: ignore
                        is_alive = False
                
                if not is_alive:
                    self.stop_all()
                    continue
                
                # Verify ports are actually listening
                import socket
                ports_ready = True
                for tunnel in self.tunnels:
                    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        test_socket.settimeout(1)
                        result = test_socket.connect_ex(('127.0.0.1', tunnel['local']))
                        if result == 0:
                            console.print(f"[green]Port {tunnel['local']} is listening ✓[/green]")
                        else:
                            console.print(f"[yellow]Port {tunnel['local']} not yet ready...[/yellow]")
                            ports_ready = False
                    finally:
                        test_socket.close()
                
                if not ports_ready:
                    self.stop_all()
                    continue

                return True, "Tunnels created successfully", bind_addr

            except Exception as e:
                self.stop_all()
                console.print(f"[yellow]Binding {bind_addr} failed: {e}[/yellow]")
                continue

        return False, "Failed to create SSH tunnels", local_ip

    def display_connection_info(self, local_ip: str) -> None:
        """Display connection information - matches reference table format."""
        from rich.table import Table
        from rich import box
        
        table = Table(title=f"SSH Tunnels to {self.pod_ip}", box=box.ROUNDED)
        table.add_column("Service", style="cyan", no_wrap=True)
        table.add_column("Local Address", style="green")
        table.add_column("Remote Endpoint (Pod)", style="yellow")
        table.add_column("Access URL", style="bold blue")

        # Add SSH Tunnel entry
        table.add_row(
            "SSH Tunnel",
            "-",
            f"{self.pod_ip}:{self.ssh_port}",
            "-"
        )

        for tunnel in self.tunnels:
            local_bind = f"127.0.0.1:{tunnel['local']}"
            remote_target = f"{self.pod_ip}:{tunnel['remote']}"
            
            if tunnel['remote'] == 22:
                url = f"ssh -p {tunnel['local']} root@localhost"
            else:
                url = f"http://localhost:{tunnel['local']}"
            
            table.add_row(
                tunnel['name'],
                local_bind,
                remote_target,
                url
            )
        
        console.print()
        console.print(table)
        console.print("[dim]Press Ctrl+C to stop tunnels and terminate pod[/dim]\n")

    def wait(self) -> None:
        """Wait for tunnel processes (blocks until Ctrl+C)."""
        if not self.processes:
            return

        console.print("[dim]Tunnels active. Press Ctrl+C to stop.[/dim]")

        try:
            for process in self.processes:
                if hasattr(process, 'wait'):
                    process.wait()
                elif hasattr(process, 'expect'):
                    import pexpect
                    try:
                        process.expect(pexpect.EOF, timeout=None)
                    except (pexpect.EOF, pexpect.TIMEOUT):
                        pass
        except KeyboardInterrupt:
            console.print("\n[dim]Received interrupt signal...[/dim]")
            raise

    def stop_all(self) -> None:
        """Stop all tunnel processes."""
        if not self.processes:
            return

        console.print("[cyan]Stopping SSH tunnels...[/cyan]")

        for process in self.processes:
            try:
                if hasattr(process, 'terminate'):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                elif hasattr(process, 'close'):
                    process.close()
            except Exception:
                try:
                    if hasattr(process, 'kill'):
                        process.kill()
                except Exception:
                    pass

        self.processes.clear()
        console.print("[green]Tunnels stopped[/green]")
