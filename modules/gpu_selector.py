"""GPU selection logic for Lorel.ai RunPod setup."""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class GPUSelection:
    """Result of GPU selection."""
    gpu_type_id: str
    display_name: str
    gpu_count: int
    cost_per_hour: float
    memory_gb: int


def select_optimal_gpu(
    gpu_types: List,  # List[GPUInfo] from api_client
    min_vram_gb: int,
    max_cost: float,
    cloud_type: str = "SECURE",
    is_spot: bool = False
) -> Tuple[Optional[GPUSelection], Optional[str]]:
    """Select the cheapest available GPU meeting requirements.

    Args:
        gpu_types: List of GPUInfo objects from API
        min_vram_gb: Minimum VRAM requirement in GB
        max_cost: Maximum cost per hour in USD
        cloud_type: "SECURE" or "COMMUNITY"
        is_spot: Whether to use spot pricing

    Returns:
        Tuple of (GPUSelection or None, error_message or None)
    """
    candidates = []

    for gpu in gpu_types:
        # Check cloud availability
        if cloud_type == "SECURE" and not gpu.secure_cloud:
            continue
        if cloud_type == "COMMUNITY" and not gpu.community_cloud:
            continue

        # Check VRAM requirement
        if gpu.memory_in_gb < min_vram_gb:
            continue

        # Get price based on cloud type and spot flag
        if cloud_type == "SECURE":
            price = gpu.secure_spot_price if is_spot else gpu.secure_price
        else:
            price = gpu.community_spot_price if is_spot else gpu.community_price

        # Skip if no price available
        if price is None:
            continue

        # Check cost constraint
        if price > max_cost:
            continue

        candidates.append(GPUSelection(
            gpu_type_id=gpu.id,
            display_name=gpu.display_name,
            gpu_count=1,
            cost_per_hour=price,
            memory_gb=gpu.memory_in_gb
        ))

    if not candidates:
        # Generate helpful error message
        available_gpus = [
            g for g in gpu_types
            if (cloud_type == "SECURE" and g.secure_cloud) or
               (cloud_type == "COMMUNITY" and g.community_cloud)
        ]

        if not available_gpus:
            return None, f"No GPUs available in {cloud_type} cloud."

        vram_filtered = [g for g in available_gpus if g.memory_in_gb >= min_vram_gb]
        if not vram_filtered:
            max_vram = max(g.memory_in_gb for g in available_gpus)
            return None, f"No GPUs with {min_vram_gb}GB VRAM. Max available: {max_vram}GB."

        return None, f"No GPUs under ${max_cost}/hour. Try increasing MAX_COST_PER_HOUR."

    # Sort by cost (cheapest first)
    candidates.sort(key=lambda x: x.cost_per_hour)

    return candidates[0], None


def select_all_candidate_gpus(
    gpu_types: List,  # List[GPUInfo] from api_client
    min_vram_gb: int,
    max_cost: float,
    cloud_type: str = "SECURE",
    is_spot: bool = False
) -> List[GPUSelection]:
    """Get ALL candidate GPUs sorted by price (cheapest first).

    Unlike select_optimal_gpu which returns only the cheapest,
    this returns all candidates for fallback when instances are unavailable.

    Args:
        gpu_types: List of GPUInfo objects from API
        min_vram_gb: Minimum VRAM requirement in GB
        max_cost: Maximum cost per hour in USD
        cloud_type: "SECURE" or "COMMUNITY"
        is_spot: Whether to use spot pricing

    Returns:
        List of GPUSelection objects sorted by cost (cheapest first)
    """
    candidates = []

    for gpu in gpu_types:
        # Check cloud availability
        if cloud_type == "SECURE" and not gpu.secure_cloud:
            continue
        if cloud_type == "COMMUNITY" and not gpu.community_cloud:
            continue

        # Check VRAM requirement
        if gpu.memory_in_gb < min_vram_gb:
            continue

        # Get price based on cloud type and spot flag
        if cloud_type == "SECURE":
            price = gpu.secure_spot_price if is_spot else gpu.secure_price
        else:
            price = gpu.community_spot_price if is_spot else gpu.community_price

        # Skip if no price available
        if price is None:
            continue

        # Check cost constraint
        if price > max_cost:
            continue

        candidates.append(GPUSelection(
            gpu_type_id=gpu.id,
            display_name=gpu.display_name,
            gpu_count=1,
            cost_per_hour=price,
            memory_gb=gpu.memory_in_gb
        ))

    # Sort by cost (cheapest first)
    candidates.sort(key=lambda x: x.cost_per_hour)

    return candidates


def display_gpu_options(
    gpu_types: List,  # List[GPUInfo]
    min_vram_gb: int,
    max_cost: float,
    cloud_type: str = "SECURE",
    is_spot: bool = False,
    limit: int = 10
) -> None:
    """Display available GPU options in a table."""
    table = Table(title="Available GPUs")
    table.add_column("GPU", style="cyan")
    table.add_column("VRAM", justify="right")
    table.add_column("Price/hr", justify="right")
    table.add_column("Cloud", style="dim")

    candidates = []

    for gpu in gpu_types:
        # Check cloud availability
        if cloud_type == "SECURE" and not gpu.secure_cloud:
            continue
        if cloud_type == "COMMUNITY" and not gpu.community_cloud:
            continue

        # Check VRAM requirement
        if gpu.memory_in_gb < min_vram_gb:
            continue

        # Get price
        if cloud_type == "SECURE":
            price = gpu.secure_spot_price if is_spot else gpu.secure_price
        else:
            price = gpu.community_spot_price if is_spot else gpu.community_price

        if price is None or price > max_cost:
            continue

        candidates.append((gpu, price))

    # Sort by price
    candidates.sort(key=lambda x: x[1])

    for gpu, price in candidates[:limit]:
        table.add_row(
            gpu.display_name,
            f"{gpu.memory_in_gb}GB",
            f"${price:.3f}",
            cloud_type
        )

    if not candidates:
        console.print("[yellow]No GPUs match the current criteria[/yellow]")
    else:
        console.print(table)
