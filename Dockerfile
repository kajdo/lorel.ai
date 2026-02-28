# Use NVIDIA CUDA base for GPU acceleration (NGC registry)
FROM --platform=$BUILDPLATFORM nvcr.io/nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install Python and other dependencies
RUN apt-get update -y && \
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
    mkdir -p /usr/share/espeak-ng-data && \
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

# Install Python dependencies
# Using uv pip install for faster-whisper avoids the 'No module named pip' error
RUN uv venv --python 3.10 && \
    uv sync --extra gpu --no-cache && \
    uv pip install --no-cache-dir faster-whisper && \
    uv pip install --no-cache-dir python-multipart

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
    ROOT_PASSWORD=kokoro_runpod \
    LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}"

# Download Kokoro model
RUN /app/.venv/bin/python docker/scripts/download_model.py --output api/src/models/v1_0

# Download STT service script from GitHub
RUN curl -L https://raw.githubusercontent.com/kajdo/lorel.ai/main/helper/stt_service.py -o /app/stt_service.py

# Pre-download the Whisper model
RUN mkdir -p /app/models/whisper && \
    /app/.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('distil-large-v3', device='cpu', download_root='/app/models/whisper')"

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

# Create startup script
RUN echo '#!/bin/bash\n\
    service ssh start\n\
    /app/.venv/bin/python /app/stt_service.py &\n\
    fuser -k /dev/nvidia0 || true\n\
    sleep 1\n\
    exec /app/.venv/bin/uvicorn api.src.main:app --host 0.0.0.0 --port 8880 --log-level info' > /start.sh && \
    chmod +x /start.sh

# Expose ports -- should not be necessary if everything is done via ssh-tunnels
# EXPOSE 22 8880 8881

# Start the service
CMD ["/start.sh"]
