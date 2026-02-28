"""RunPod API client with REST and GraphQL support."""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from rich.console import Console

console = Console()

# API endpoints
REST_BASE_URL = "https://rest.runpod.io/v1"
GRAPHQL_URL = "https://api.runpod.io/graphql"


class NoInstancesAvailableError(Exception):
    """Raised when no instances are available for the requested GPU type."""
    pass



@dataclass
class GPUInfo:
    """Information about a GPU type."""
    id: str
    display_name: str
    memory_in_gb: int
    secure_price: Optional[float]
    community_price: Optional[float]
    secure_spot_price: Optional[float]
    community_spot_price: Optional[float]
    secure_cloud: bool
    community_cloud: bool


@dataclass
class Pod:
    """RunPod pod representation."""
    id: str
    name: str
    status: str
    desired_status: str
    public_ip: Optional[str] = None
    port_mappings: Optional[Dict[str, int]] = None  # {"22": 12345, "8880": 23456}
    gpu: Optional[Dict[str, Any]] = None

    @property
    def ssh_port(self) -> Optional[int]:
        """Get SSH port from port mappings."""
        if not self.port_mappings:
            return None
        port = self.port_mappings.get("22")
        return int(port) if port else None

    @property
    def api_port(self) -> Optional[int]:
        """Get API port (8880) from port mappings."""
        if not self.port_mappings:
            return None
        port = self.port_mappings.get("8880")
        return int(port) if port else None

class RunPodAPIClient:
    """RunPod REST API client with GraphQL support."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry_count: int = 3
    ) -> Any:
        """Make API request with retry logic."""
        url = f"{REST_BASE_URL}{endpoint}"

        for attempt in range(retry_count):
            try:
                response = self.session.request(
                    method, url, json=data, params=params, timeout=30
                )

                # Handle rate limiting
                if response.status_code == 429:
                    wait_time = 2 ** attempt
                    console.print(f"[yellow]Rate limited, waiting {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                # Handle empty responses
                if response.status_code == 204:
                    return None

                return response.json()

            except requests.exceptions.RequestException as e:
                # Check for "no instances available" error - don't retry, raise immediately
                if hasattr(e, 'response') and e.response is not None:
                    error_body = e.response.text or ""
                    if "no longer any instances available" in error_body.lower():
                        raise NoInstancesAvailableError(
                            f"No instances available: {error_body[:100]}"
                        )
                
                # Show more details on final attempt
                if attempt < retry_count - 1:
                    console.print(f"[yellow]Request failed, retrying... ({attempt + 1}/{retry_count})[/yellow]")
                    time.sleep(1)
                    continue
                
                # Show detailed error on final failure
                if hasattr(e, 'response') and e.response is not None:
                    status = e.response.status_code
                    try:
                        error_body = e.response.text[:200]
                    except:
                        error_body = "Unable to read response"
                    raise RuntimeError(f"API request failed ({status}): {error_body}")
                raise RuntimeError(f"API request failed after {retry_count} attempts: {e}")

    def _query_graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute GraphQL query."""
        # RunPod GraphQL expects api_key as a query parameter
        params = {"api_key": self.api_key}
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self.session.post(GRAPHQL_URL, params=params, json=payload, timeout=30)

        if response.status_code != 200:
            error_body = response.text[:200] if response.text else "No error body"
            raise RuntimeError(f"GraphQL request failed ({response.status_code}): {error_body}")

        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

        return data


    def validate_api_key(self) -> bool:
        """Validate API key by making a test request."""
        try:
            # Try to list pods - this is a simple validation
            self._request("GET", "/pods", params={"limit": 1})
            return True
        except Exception as e:
            console.print(f"[dim]API error: {e}[/dim]")
            return False

    def get_gpu_types(self) -> List[GPUInfo]:
        """Get available GPU types with pricing from GraphQL."""
        query = """
        query {
            gpuTypes {
                id
                displayName
                memoryInGb
                secureCloud
                communityCloud
                securePrice
                communityPrice
                secureSpotPrice
                communitySpotPrice
            }
        }
        """

        data = self._query_graphql(query)
        gpu_types = data.get("data", {}).get("gpuTypes", [])

        return [
            GPUInfo(
                id=gpu["id"],
                display_name=gpu.get("displayName", gpu["id"]),
                memory_in_gb=gpu.get("memoryInGb", 0),
                secure_price=gpu.get("securePrice"),
                community_price=gpu.get("communityPrice"),
                secure_spot_price=gpu.get("secureSpotPrice"),
                community_spot_price=gpu.get("communitySpotPrice"),
                secure_cloud=gpu.get("secureCloud", False),
                community_cloud=gpu.get("communityCloud", False)
            )
            for gpu in gpu_types
        ]

    def create_pod(
        self,
        name: str,
        docker_image: str,
        gpu_type_id: str,
        gpu_count: int = 1,
        cloud_type: str = "SECURE",
        ports: Optional[List[str]] = None,
        container_disk_gb: int = 50,
        is_spot: bool = False,
        env: Optional[Dict[str, str]] = None
    ) -> Pod:
        """Create a new pod from Docker image (no template required)."""
        if ports is None:
            ports = ["22/tcp", "8880/tcp"]

        data = {
            "name": name,
            "imageName": docker_image,
            "cloudType": cloud_type,
            "computeType": "GPU",
            "gpuTypeIds": [gpu_type_id],
            "gpuCount": gpu_count,
            "containerDiskInGb": container_disk_gb,
            "ports": ports,
            "supportPublicIp": True,
            "interruptible": is_spot
        }

        if env:
            data["env"] = env

        response = self._request("POST", "/pods", data=data)
        return self._parse_pod(response)

    def _parse_pod(self, data: Dict) -> Pod:
        """Parse pod data from API response - matches reference implementation."""
        return Pod(
            id=data.get("id", ""),
            name=data.get("name", ""),
            status=data.get("status", ""),
            desired_status=data.get("desiredStatus", ""),
            public_ip=data.get("publicIp"),
            port_mappings=data.get("portMappings", {}),
            gpu=data.get("gpu")
        )

    def get_pod(self, pod_id: str) -> Pod:
        """Get pod by ID."""
        response = self._request("GET", f"/pods/{pod_id}")
        return self._parse_pod(response)

    def get_pods(self) -> List[Pod]:
        """Get all pods."""
        response = self._request("GET", "/pods")
        return [self._parse_pod(p) for p in response]

    def terminate_pod(self, pod_id: str) -> bool:
        """Terminate a pod."""
        try:
            self._request("DELETE", f"/pods/{pod_id}")
            return True
        except Exception as e:
            console.print(f"[red]Failed to terminate pod: {e}[/red]")
            return False

    def stop_pod(self, pod_id: str) -> bool:
        """Stop a pod."""
        try:
            self._request("POST", f"/pods/{pod_id}/stop")
            return True
        except Exception as e:
            console.print(f"[red]Failed to stop pod: {e}[/red]")
            return False

    def start_pod(self, pod_id: str) -> bool:
        """Start a pod."""
        try:
            self._request("POST", f"/pods/{pod_id}/start")
            return True
        except Exception as e:
            console.print(f"[red]Failed to start pod: {e}[/red]")
            return False

    def get_pod_ssh_port_from_graphql(self, pod_id: str) -> Optional[int]:
        """Fetch the correct TCP SSH port for a pod using GraphQL.
        
        This resolves issues where REST API returns UDP port or has stale data.
        """
        query = """
        query MyPods {
          myself {
            pods {
              id
              runtime {
                ports {
                  privatePort
                  publicPort
                  type
                }
              }
            }
          }
        }
        """
        
        try:
            data = self._query_graphql(query)
            pods = data.get("data", {}).get("myself", {}).get("pods", [])
            
            target_pod = next((p for p in pods if p.get("id") == pod_id), None)
            if not target_pod:
                return None
                
            runtime = target_pod.get("runtime", {})
            if not runtime:
                return None
                
            ports = runtime.get("ports", [])
            for p in ports:
                if p.get("privatePort") == 22 and p.get("type") == "tcp":
                    return p.get("publicPort")
            
            return None
            
        except Exception:
            return None