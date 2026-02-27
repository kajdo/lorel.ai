#!/usr/bin/env bash
set -e

# Parse arguments
CLEAN_DOCKER=false
PUSH_DOCKER=false
for arg in "$@"; do
    case $arg in
        --clean)
            CLEAN_DOCKER=true
            ;;
        --push)
            PUSH_DOCKER=true
            ;;
    esac
done

# ===================================
# Configuration
# ===================================
DOCKER_USERNAME="kajdo" # Change this to your Docker.io username
IMAGE_NAME="kokoro-fastapi"
IMAGE_TAG="${IMAGE_TAG:-latest}"
FULL_IMAGE_NAME="${DOCKER_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"

# ===================================
# Colors for output
# ===================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ===================================
# Functions
# ===================================
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ===================================
# Step 1: Docker Cleanup
# ===================================
if [ "$CLEAN_DOCKER" = true ]; then
    log_info "Step 1: Cleaning up Docker resources..."
    yes | { docker system prune -af && docker builder prune -af && docker volume prune && docker image prune -a; }
    log_info "Docker cleanup completed."
else
    log_info "Step 1: Skipping Docker cleanup (use --clean flag to enable)"
fi

# ===================================
# Step 2: Check if Dockerfile exists
# ===================================
if [ ! -f "Dockerfile" ]; then
    log_error "Dockerfile not found in current directory!"
    exit 1
fi

# ===================================
# Step 3: Build Docker image
# ===================================
log_info "Step 2: Building Docker image..."
log_info "Image: ${FULL_IMAGE_NAME}"
log_warn "If DOCKER_USERNAME is not set, it defaults to 'your-username'"

docker build -f Dockerfile -t "${FULL_IMAGE_NAME}" .

if [ $? -eq 0 ]; then
    log_info "Docker image built successfully!"
else
    log_error "Docker image build failed!"
    exit 1
fi

# ===================================
# Step 4: Push Docker image
# ===================================
if [ "$PUSH_DOCKER" = true ]; then
    log_info "Step 3: Pushing Docker image to Docker.io..."
    log_info "Pushing: ${FULL_IMAGE_NAME}"

    docker push "${FULL_IMAGE_NAME}"

    if [ $? -eq 0 ]; then
        log_info "Docker image pushed successfully!"
        echo ""
        log_info "================================"
        log_info "Image is ready for deployment!"
        log_info "================================"
        log_info "Image: ${FULL_IMAGE_NAME}"
        log_info ""
        log_info "Use this image in your RunPod template:"
        echo "  ${FULL_IMAGE_NAME}"
        echo ""
        log_info "Expose ports:"
        echo "  - 22 (SSH)"
        echo "  - 8880 (Kokoro API)"
    else
        log_error "Docker image push failed!"
        exit 1
    fi
else
    log_info "Step 3: Skipping Docker push (use --push flag to enable)"
fi
