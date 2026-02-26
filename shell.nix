{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    uv
  ];

  # LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
  #   pkgs.portaudio
  #   pkgs.zlib
  #   pkgs.ffmpeg
  # ];

  shellHook = ''

    # Create venv if it doesn't exist
    if [ ! -d .venv ]; then
      echo "Creating virtual environment with uv..."
      uv venv
    fi

    # Activate venv
    source .venv/bin/activate

    # Install dependencies if requirements.txt changed or venv is new
    if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
      echo "Installing dependencies from requirements.txt..."
      uv pip install -r requirements.txt
      touch .venv/.installed
    fi

    echo "✓ Virtual environment activated"
    echo "✓ Python: $(python --version)"
    echo "✓ Pip packages: $(uv pip list | grep -c "^\\w") installed"

    echo "Setting aliases ..."
    # Get the current directory and evaluate it immediately
    PROJECT_DIR=$(pwd)
    export PROJECT_DIR
    alias kk="cd $PROJECT_DIR && clear && glow ./README.md"

  '';
}
