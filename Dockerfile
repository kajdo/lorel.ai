# Use NVIDIA CUDA base for GPU acceleration (NGC registry)
FROM --platform=$BUILDPLATFORM nvcr.io/nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install Python and other dependencies
RUN apt-get update -y &&  \
    apt-get install -y \
        python3.10 \
        python3-venv \
        espeak-ng \
        espeak-ng-data \
        libsndfile1 \
        ffmpeg \
        curl \
        git \
        openssh-server \
        net-tools \
        zstd \
        psmisc \
        g++ \
        cmake && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    mkdir -p /usr/share/espeak-ng-data &&  \
    ln -s /usr/lib/*/espeak-ng-data/* /usr/share/espeak-ng-data/ && \
    # Install uv package manager
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/ && \
    mv /root/.local/bin/uvx /usr/local/bin/ && \
    # Clone Kokoro-FastAPI repository
    git clone --depth 1 https://github.com/remsky/Kokoro-FastAPI.git /tmp/kokoro && \
    # Create app user and app directory
    useradd -m -u 1001 appuser && \
    mkdir -p /app && \
    cp -r /tmp/kokoro/* /app/ && \
    rm -rf /tmp/kokoro && \
    chown -R appuser:appuser /app

USER appuser
WORKDIR /app

# Project files are already cloned
RUN chmod +x docker/scripts/*.sh

# Install Python dependencies with GPU extras
RUN uv venv --python 3.10 && \
    uv sync --extra gpu --no-cache

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/api \
    UV_LINK_MODE=copy \
    USE_GPU=true \
    PHONEMIZER_ESPEAK_PATH=/usr/bin \
    PHONEMIZER_ESPEAK_DATA=/usr/share/espeak-ng-data \
    ESPEAK_DATA_PATH=/usr/share/espeak-ng-data \
    DEVICE="gpu" \
    # SSH root password (change for production)
    ROOT_PASSWORD=kokoro_runpod

# Download model during build
RUN python docker/scripts/download_model.py --output api/src/models/v1_0

# Setup SSH configuration
USER root
RUN mkdir /var/run/sshd && \
    echo "root:${ROOT_PASSWORD}" | chpasswd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    echo "AllowTcpForwarding yes" >> /etc/ssh/sshd_config && \
    echo "GatewayPorts yes" >> /etc/ssh/sshd_config && \
    echo "UseDNS no" >> /etc/ssh/sshd_config && \
    echo "TCPKeepAlive yes" >> /etc/ssh/sshd_config

USER root

# Create startup script
RUN echo '#!/bin/bash\n\
    # Start SSH service\n\
    service ssh start\n\
    \n\
    # GPU cleanup\n\
    fuser -k /dev/nvidia0 || true\n\
    sleep 1\n\
    \n\
    # Start Kokoro FastAPI server\n\
    exec uvicorn api.src.main:app --host 0.0.0.0 --port 8880 --log-level info' > /start.sh && \
    chmod +x /start.sh

# Expose ports
EXPOSE 22 8880

# Start the service
CMD ["/start.sh"]
