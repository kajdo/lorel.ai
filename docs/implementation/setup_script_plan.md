# Lorel.ai Setup Script Implementation Plan

## Overview

This document outlines the implementation plan for a simple, automated deployment script for the lorel.ai (Kokoro-FastAPI) project on RunPod. The script will enable users to spin up disposable GPU pods without requiring manual template creation in the browser.

## Key Design Principles

1. **Zero Browser Interaction**: The script creates disposable pods programmatically without user needing to prepare templates in the RunPod web interface.
2. **Minimal User Input**: Configuration is done once via `--init`, then deployment is a single command.
3. **Automatic Cleanup**: Pods and SSH tunnels are terminated on Ctrl+C.
4. **Interactive Setup**: The `--init` command guides users through configuration with sensible defaults.

## Project Analysis

### Lorel.ai (Kokoro-FastAPI) Container

From the Dockerfile analysis:
- **Base Image**: nvcr.io/nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04
- **Exposed Ports**:
  - `22/tcp` - SSH (configured with password authentication)
  - `8880/tcp` - Kokoro FastAPI service (uvicorn on 0.0.0.0:8880)
- **Default SSH Password**: `kokoro_runpod` (can be overridden via environment)
- **GPU Requirements**: CUDA-compatible GPU with sufficient VRAM for TTS inference

### RunPod Integration Points

Based on runpod_simple implementation:
- **API Base**: `https://rest.runpod.io/v1` (REST) + `https://api.runpod.io/graphql` (GPU pricing)
- **Authentication**: Bearer token from `RUNPOD_API_KEY`
- **Pod Creation**: Uses `create_pod()` with `cloud_type` (SECURE or COMMUNITY)
- **SSH Access**: Requires public IP and port mapping for 22/tcp
- **GPU Selection**: Uses GraphQL API for pricing and availability checks

## Requirements Specification

### 1. Command-Line Interface

The script will support the following commands:

```bash
python setup.py init      # Interactive .env setup
python setup.py deploy   # Deploy pod (with optional --spot flag)
python setup.py stop      # Stop all running pods and terminate SSH tunnels
```

### 2. Flags

- `--spot`: Deploy a Spot instance (Community Cloud, interruptible, cheaper)
- `--deploy`: Main deployment command (default if no command specified)
- `--stop`: Stop all running pods and clean up

### 3. Configuration (.env)

A `.env.sample` file will define required configuration:

```bash
# Required: RunPod API Key (get from https://www.runpod.io/console/user/settings)
RUNPOD_API_KEY=your_api_key_here

# Optional: SSH password (defaults to container default if not set)
# The Kokoro container default password is "kokoro_runpod"
SSH_PASSWORD=kokoro_runpod

# Optional: GPU selection defaults
# Minimum VRAM required (default: 16GB)
MIN_VRAM_GB=16

# Maximum hourly cost in USD (default: 1.0 for Secure, 0.3 for Spot)
MAX_COST_PER_HOUR=1.0

# Optional: Image to deploy (defaults to kajdo/kokoro-fastapi:latest)
DOCKER_IMAGE=kajdo/kokoro-fastapi:latest

# Optional: Container disk size in GB (default: 50)
CONTAINER_DISK_GB=50
```

### 4. Interactive Init Workflow

The `--init` command will:

1. Parse `.env.sample` to discover required/optional configuration
2. For each configuration entry:
   - If `.env` exists and value is set → Show current value as grayed default
   - If `.env` doesn't exist → Show `.env.sample` value as default
   - Prompt user for value with accept/edit option
3. Create or update `.env` file with validated inputs
4. Validate API key connectivity

**Sample interaction**:
```
Welcome to Lorel.ai RunPod Setup!

Configuration Setup:

RunPod API Key (required)
  Default: rpa_xxxxxxxxxxxx (current value from .env)
  Enter new value (or press Enter to keep): [rpa_xxxxxxxxxxxx]

SSH Password (optional)
  Default: kokoro_runpod (container default)
  Enter new value (or press Enter to keep): [kokoro_runpod]

Minimum VRAM GB [16]: 
Maximum Cost Per Hour (USD) [1.0]: 

Configuration saved to .env
Validating API key... ✓ API key is valid
Setup complete! Run 'python setup.py deploy' to deploy a pod.
```

### 5. Pod Deployment Workflow

The `deploy` command will:

1. **Load Configuration**: Read `.env` or environment variables
2. **GPU Selection**: Query RunPod GraphQL API for available GPUs
   - Filter by minimum VRAM requirement
   - Filter by maximum cost threshold
   - Select cheapest available option
   - Prefer Secure Cloud unless `--spot` flag is used
3. **Create Pod**: Call RunPod REST API
   - Use `cloud_type`: "SECURE" (default) or "COMMUNITY" (with `--spot`)
   - Set `interruptible`: true (with `--spot`)
   - Configure `ports`: ["22/tcp", "8880/tcp"]
   - Use container disk (no network volume needed for disposable pods)
4. **Wait for Ready**: Poll pod status until "RUNNING" with public IP
5. **Establish SSH Tunnels**:
   - Port 8880 (Kokoro API) → Local port 8880
   - Port 22 (SSH) → Local port 2222 (for direct SSH access)
6. **Display Access Information**: Show URLs and connection details
7. **Keep Alive**: Wait for Ctrl+C signal

### 6. SSH Tunnel Management

Based on runpod_simple `ssh_tunnel.py`:

- **Local IP Detection**: Try to bind to `0.0.0.0` for network-wide access, fallback to `127.0.0.1`
- **Authentication**: Prefer SSH keys from `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`, fallback to password
- **Tunnel Configuration**:
  ```bash
  ssh -4 -L 0.0.0.0:8880:127.0.0.1:8880 root@<POD_IP> -p <SSH_PORT>
  ssh -4 -L 0.0.0.0:2222:127.0.0.1:22 root@<POD_IP> -p <SSH_PORT>
  ```
- **Connection Options**:
  - `ServerAliveInterval=30`, `ServerAliveCountMax=3` for keepalive
  - `StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null` for convenience
  - `ExitOnForwardFailure=yes` to fail fast if binding fails

### 7. Cleanup on Exit

On Ctrl+C:
1. Stop all SSH tunnel processes
2. Call RunPod API to terminate the pod
3. Display confirmation message

## Architecture Design

### Module Structure

```
setup.py                    # Main entry point (CLI)
├── config.py              # Configuration management (.env parsing, validation)
├── api_client.py          # RunPod API client (REST + GraphQL)
├── pod_manager.py         # Pod lifecycle (create, wait, terminate)
├── gpu_selector.py        # GPU selection logic (pricing, availability)
├── ssh_tunnel.py          # SSH tunnel management
└── init.py               # Interactive setup wizard
```

### Dependencies

Based on runpod_simple:
- `requests` - HTTP client for RunPod APIs
- `rich` - Terminal formatting (tables, progress bars, colors)
- `pexpect` - SSH password authentication (optional, for password-based auth)

### Configuration Class

```python
class Config:
    """Manages configuration from .env file and environment."""

    def __init__(self):
        self.env_path = self._find_env_file()
        self._load_dotenv()
        self.api_key = self._load_api_key()
        self.ssh_password = self._load_ssh_password()
        self.min_vram_gb = self._load_min_vram()
        self.max_cost = self._load_max_cost()
        self.docker_image = self._load_docker_image()
        self.container_disk_gb = self._load_container_disk()

    def validate(self) -> tuple[bool, str]:
        """Validate configuration and return (is_valid, error_message)."""
```

### API Client Class

```python
class RunPodAPIClient:
    """RunPod REST API client with GraphQL support."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        # Set headers...

    def create_pod(
        self,
        name: str,
        docker_image: str,
        gpu_type_id: str,
        gpu_count: int,
        cloud_type: str = "SECURE",
        ports: List[str] = None,
        container_disk_gb: int = 50,
        is_spot: bool = False
    ) -> Pod:
        """Create a new pod from Docker image (no template required)."""

    def get_gpu_types(
        self,
        cloud_type: str = "SECURE"
    ) -> tuple[List[GPUInfo], Dict[str, int]]:
        """Get available GPU types with pricing from GraphQL."""
```

### GPU Selection Logic

```python
def select_optimal_gpu(
    gpu_types: List[GPUInfo],
    availability: Dict[str, int],
    min_vram_gb: int,
    max_cost: float,
    cloud_type: str,
    is_spot: bool
) -> dict:
    """
    Select the cheapest available GPU meeting requirements.

    Returns:
        dict: {gpu_type_id, display_name, gpu_count, cost_per_hour}
    """
    # Filter by VRAM
    # Filter by cost (use secure_price or community_spot_price)
    # Sort by cost
    # Check availability
    # Return cheapest option
```

### SSH Tunnel Class

```python
class SSHTunnel:
    """Manages SSH tunnels for accessing pod services."""

    def __init__(
        self,
        pod_ip: str,
        ssh_port: int,
        username: str = "root",
        ssh_key_path: Optional[str] = None,
        password: Optional[str] = None
    ):
        # ...

    def start_tunnels(self) -> Tuple[bool, str, str]:
        """
        Start SSH tunnels.

        Returns:
            (success, message, local_ip)
        """

    def wait(self) -> None:
        """Wait for tunnel processes (blocks until Ctrl+C)."""

    def stop_all(self) -> None:
        """Terminate all tunnel processes."""
```

## Key Implementation Details

### 1. No Template Requirement

Unlike runpod_simple which uses pre-created RunPod templates, this script will:
- Deploy using the Docker image directly via RunPod's pod creation API
- Specify `imageName` instead of `templateId`
- Configure ports directly in the pod creation payload

**API Payload**:
```json
{
  "name": "kokoro-pod-20250227-12345678",
  "cloudType": "SECURE",
  "computeType": "GPU",
  "gpuTypeIds": ["NVIDIA RTX 4090"],
  "gpuCount": 1,
  "imageName": "kajdo/kokoro-fastapi:latest",
  "containerDiskInGb": 50,
  "ports": ["22/tcp", "8880/tcp"],
  "supportPublicIp": true,
  "interruptible": false
}
```

### 2. Minimal Configuration Values

From the analysis, only these values are truly required:

| Variable | Required? | Default | Description |
|----------|-----------|---------|-------------|
| `RUNPOD_API_KEY` | Yes | None | RunPod API authentication key |
| `SSH_PASSWORD` | No | `kokoro_runpod` | Container default password |
| `MIN_VRAM_GB` | No | 16 | Minimum GPU VRAM |
| `MAX_COST_PER_HOUR` | No | 1.0 (Secure) / 0.3 (Spot) | Maximum hourly cost |
| `DOCKER_IMAGE` | No | `kajdo/kokoro-fastapi:latest` | Docker image to deploy |
| `CONTAINER_DISK_GB` | No | 50 | Container disk size |

### 3. Interactive Prompt Library

For the `--init` wizard, use a prompt library for terminal interaction:

**Option A**: `prompt_toolkit` (feature-rich, but heavy)
**Option B**: `questionary` (simpler, built on prompt_toolkit)
**Option C**: Custom simple prompts using `input()` with rich formatting (lightweight)

**Recommendation**: Custom simple prompts for minimal dependencies.

### 4. Error Handling

- **API Errors**: Retry with exponential backoff (max 3 attempts)
- **GPU Unavailable**: Try next cheapest GPU option
- **SSH Connection Failures**: Fallback to alternative bind addresses
- **Configuration Errors**: Clear error messages with actionable suggestions

### 5. Signal Handling

```python
def setup_signal_handlers(pod_manager, ssh_tunnel, pod_id):
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(signum, frame):
        print("\n\nReceived interrupt signal. Cleaning up...")
        ssh_tunnel.stop_all()
        pod_manager.terminate_pod(pod_id)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
```

## Implementation Order

### Phase 1: Core Infrastructure
1. Create project structure (setup.py, modules)
2. Implement `config.py` (.env loading, validation)
3. Implement `api_client.py` (RunPod REST API client)

### Phase 2: GPU Selection
4. Implement GraphQL GPU querying in `api_client.py`
5. Implement `gpu_selector.py` (filter and select optimal GPU)

### Phase 3: Pod Management
6. Implement `pod_manager.py` (create, wait, terminate)
7. Test pod creation with Docker image (no template)

### Phase 4: SSH Tunnels
8. Implement `ssh_tunnel.py` (tunnel creation, wait, cleanup)
9. Test tunnel establishment with running pod

### Phase 5: Interactive Setup
10. Implement `init.py` (interactive .env setup wizard)
11. Create `.env.sample` file

### Phase 6: CLI Integration
12. Implement main CLI in `setup.py`
13. Wire up `deploy`, `stop`, `init` commands
14. Add signal handling for cleanup

### Phase 7: Testing & Refinement
15. End-to-end testing of deployment workflow
16. Test Spot instance deployment
17. Test cleanup on Ctrl+C
18. Documentation and user guide

## Testing Strategy

### Unit Tests
- Configuration loading and validation
- API client request/retry logic
- GPU filtering and selection algorithm
- SSH tunnel command building

### Integration Tests
- Pod creation with Docker image
- SSH tunnel establishment
- Signal handling and cleanup

### Manual Testing Checklist
- [ ] `--init` creates valid `.env` file
- [ ] `deploy` creates pod with correct Docker image
- [ ] SSH tunnels are accessible (`http://localhost:8880`)
- [ ] Kokoro API responds via tunnel
- [ ] `--spot` deploys Community Cloud instance
- [ ] `stop` terminates pod and tunnels
- [ ] Ctrl+C during deploy cleans up resources
- [ ] Invalid API key shows helpful error
- [ ] GPU unavailable shows helpful error

## Future Enhancements (Out of Scope)

1. **Multi-pod Management**: Track multiple running pods, allow selection
2. **Network Volume Support**: Allow persistent storage with network volumes
3. **GPU Type Specification**: Allow users to specify exact GPU type
4. **Background Mode**: Detach tunnels and exit, allow reattachment
5. **Health Checks**: Verify Kokoro API is responsive before returning
6. **Model Preloading**: Optionally pull TTS models during deployment
7. **Docker Hub Integration**: Auto-pull latest image version on deploy

## Comparison with runpod_simple

| Feature | runpod_simple | lorel.ai setup |
|---------|---------------|----------------|
| Template Selection | Interactive, browser-based | None (uses Docker image) |
| Config Setup | Manual `.env` copy | Interactive `--init` |
| SSH Tunnels | Multiple (11434, 8080, 8888, 11235, 2222) | Minimal (8880, 2222) |
| GPU Selection | Interactive with cheapest default | Automatic (cheapest meeting criteria) |
| Cloud Type | Secure, Community, Spot | Secure, Spot (via flag) |
| Network Volume | Yes (optional) | No (container-only) |
| Pod Reuse | Yes (interactive selection) | No (always create new) |
| Cleanup | Ctrl+C or `--no-cleanup` | Ctrl+C always cleans up |

## Security Considerations

1. **API Key Storage**: `.env` file should be in `.gitignore`
2. **SSH Authentication**: Prefer SSH keys over passwords when available
3. **Default Passwords**: Warn users that default container passwords are insecure
4. **Network Binding**: Try `0.0.0.0` for network access, but fallback to localhost
5. **StrictHostKeyChecking**: Disabled for convenience (warning in docs)

## User Documentation

### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/kajdo/lorel.ai.git
cd lorel.ai

# 2. Interactive setup
python setup.py init

# 3. Deploy pod
python setup.py deploy

# 4. Access Kokoro API
# Open http://localhost:8880/docs for API documentation

# 5. Stop pod (Ctrl+C or explicit)
python setup.py stop
```

### Deploy with Spot Instances

```bash
python setup.py deploy --spot
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "API key not found" | Run `python setup.py init` |
| "No GPUs available" | Try `--spot` flag for cheaper Community Cloud instances |
| "SSH tunnel failed" | Check SSH key in `~/.ssh/` or verify SSH_PASSWORD in `.env` |
| "Port already in use" | Kill existing processes using `lsof -i :8880` |

## Conclusion

This implementation plan provides a complete blueprint for a simplified RunPod deployment tool for the lorel.ai project. The focus on minimal configuration, zero browser interaction, and automatic cleanup makes it ideal for disposable GPU workloads.

The script will be significantly simpler than runpod_simple due to:
- No template management
- No network volume support
- No pod reuse
- Minimal SSH tunnels
- Automatic GPU selection

Estimated implementation time: 2-3 days for complete implementation and testing.
