"""Interactive setup wizard for Lorel.ai RunPod configuration."""

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .config import Config
from .api_client import RunPodAPIClient


console = Console()


def run_interactive_setup(config: Optional[Config] = None) -> bool:
    """Run interactive setup wizard to create/update .env file.

    Returns:
        True if setup completed successfully, False otherwise
    """
    console.clear()
    console.print(Panel.fit(
        "[bold cyan]Lorel.ai RunPod Setup[/bold cyan]"
    ))

    if config is None:
        config = Config.load()

    console.print("\n[bold]API Configuration[/bold]")

    # API Key (required)
    console.print("[dim]Get your API key from: https://www.runpod.io/console/user/settings[/dim]")
    config.api_key = _prompt_with_default(
        "RunPod API Key",
        config.api_key or "",
        required=True
    )

    # Strip whitespace from API key (common copy-paste issue)
    config.api_key = config.api_key.strip()

    # Validate API key
    console.print("\n[dim]Validating API key...[/dim]")
    if not _validate_api_key(config.api_key):
        console.print("[red]API key validation failed.[/red]")
        return False
    console.print("[green]✓ API key is valid[/green]")

    # GPU settings
    # GPU settings
    console.print("\n[bold]GPU Settings[/bold]")

    config.min_vram_gb = int(_prompt_with_default(
        "Minimum VRAM (GB)",
        str(config.min_vram_gb),
        required=False
    ))

    config.max_cost_per_hour = float(_prompt_with_default(
        "Max Cost/Hour (USD)",
        str(config.max_cost_per_hour),
        required=False
    ))

    # Docker settings
    console.print("\n[bold]Docker Settings[/bold]")

    config.docker_image = _prompt_with_default(
        "Docker Image",
        config.docker_image,
        required=False
    )

    config.container_disk_gb = int(_prompt_with_default(
        "Container Disk (GB)",
        str(config.container_disk_gb),
        required=False
    ))

    # Save configuration
    config.save()

    console.print(f"\n[green]✓ Configuration saved to {config.env_path}[/green]")
    console.print("\n[bold]Setup complete![/bold]")
    console.print("  [cyan]python main.py deploy[/cyan]        - Deploy on Secure Cloud")
    console.print("  [cyan]python main.py deploy --spot[/cyan] - Deploy on Spot (cheaper)")

    return True



def _prompt_with_default(
    prompt_text: str,
    default: str,
    required: bool = False
) -> str:
    """Prompt user with default value support."""
    # Ensure we have a valid default (handle empty strings)
    effective_default = default.strip() if default else ""
    
    # Build and display prompt with [default] shown in gray
    if effective_default:
        # Print prompt line with gray default using Text for proper bracket handling
        from rich.text import Text
        prompt_display = Text()
        prompt_display.append(prompt_text)
        prompt_display.append(" [")
        prompt_display.append(effective_default, style="dim")
        prompt_display.append("]: ")
        console.print(prompt_display, end="")
        value = input()
    else:
        value = Prompt.ask(prompt_text)

    # Handle empty input - use default if available
    if not value or not value.strip():
        if required and not effective_default:
            console.print("[red]This field is required[/red]")
            return _prompt_with_default(prompt_text, default, required)
        return effective_default

    return value.strip()

def _validate_api_key(api_key: str) -> bool:
    """Validate API key by testing against RunPod API."""
    if not api_key:
        console.print("[red]No API key provided[/red]")
        return False

    # Strip whitespace
    api_key = api_key.strip()
    
    if not api_key.startswith("rpa_"):
        console.print("[red]API key should start with 'rpa_'[/red]")
        return False

    try:
        client = RunPodAPIClient(api_key)
        return client.validate_api_key()
    except Exception as e:
        console.print(f"[red]Validation error: {e}[/red]")
        return False
