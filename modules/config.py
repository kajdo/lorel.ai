"""Configuration management for Lorel.ai RunPod setup."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv


@dataclass
class Config:
    """Manages configuration from .env file and environment variables."""

    api_key: str = ""
    ssh_password: str = "kokoro_runpod"
    min_vram_gb: int = 16
    max_cost_per_hour: float = 1.0
    docker_image: str = "kajdo/kokoro-fastapi:latest"
    container_disk_gb: int = 50

    # Internal paths
    env_path: Path = field(default_factory=lambda: Path.cwd() / ".env", repr=False)

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from .env file."""
        config = cls()
        config._load_dotenv()
        config._load_values()
        return config

    def _load_dotenv(self) -> None:
        """Load .env file. Values override shell environment variables."""
        load_dotenv(self.env_path, override=True)

    def _load_values(self) -> None:
        """Load configuration values from environment."""
        self.api_key = os.environ.get("RUNPOD_API_KEY", "") or ""
        self.ssh_password = os.environ.get("SSH_PASSWORD", "") or "kokoro_runpod"
        self.min_vram_gb = int(os.environ.get("MIN_VRAM_GB", "") or "16")
        self.max_cost_per_hour = float(os.environ.get("MAX_COST_PER_HOUR", "") or "1.0")
        self.docker_image = os.environ.get("DOCKER_IMAGE", "") or "kajdo/kokoro-fastapi:latest"
        self.container_disk_gb = int(os.environ.get("CONTAINER_DISK_GB", "") or "50")

    def validate(self) -> Tuple[bool, str]:
        """Validate configuration and return (is_valid, error_message)."""
        if not self.api_key:
            return False, "RUNPOD_API_KEY is required. Run 'python main.py init' to configure."
        
        if not self.api_key.startswith("rpa_"):
            return False, "RUNPOD_API_KEY should start with 'rpa_'. Check your API key."
        
        if self.min_vram_gb < 1:
            return False, "MIN_VRAM_GB must be at least 1."
        
        if self.max_cost_per_hour <= 0:
            return False, "MAX_COST_PER_HOUR must be greater than 0."
        
        if self.container_disk_gb < 10:
            return False, "CONTAINER_DISK_GB must be at least 10 GB."
        
        return True, ""

    def save(self) -> None:
        """Save current configuration to .env file."""
        lines = [
            "# Required: RunPod API Key (get from https://www.runpod.io/console/user/settings)",
            f"RUNPOD_API_KEY={self.api_key}",
            "",
            "# Optional: SSH password (defaults to container default if not set)",
            f"SSH_PASSWORD={self.ssh_password}",
            "",
            "# Optional: GPU selection defaults",
            f"MIN_VRAM_GB={self.min_vram_gb}",
            f"MAX_COST_PER_HOUR={self.max_cost_per_hour}",
            "",
            "# Optional: Image to deploy",
            f"DOCKER_IMAGE={self.docker_image}",
            "",
            "# Optional: Container disk size in GB",
            f"CONTAINER_DISK_GB={self.container_disk_gb}",
        ]
        
        with open(self.env_path, "w") as f:
            f.write("\n".join(lines) + "\n")
