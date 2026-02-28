from fastapi import FastAPI, UploadFile, File, HTTPException
from faster_whisper import WhisperModel
import uvicorn
import shutil
import os
import tempfile
from pathlib import Path

app = FastAPI()

# Load model from the path we will pre-download to
model = WhisperModel(
    "distil-large-v3",
    device="cuda",
    compute_type="float16",
    download_root="/app/models/whisper",
)


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    Transcribe audio file using Whisper.

    This endpoint uses a unique temporary file for each request to avoid
    race conditions with concurrent requests.
    """
    # Create a unique temp file for this request
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix="stt_") as temp_file:
        temp_path = Path(temp_file.name)

    try:
        # Write uploaded file to temp location
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Transcribe with reasonable parameters for speed
        segments, _ = model.transcribe(
            str(temp_path),
            beam_size=1,  # Use greedy decoding for speed
            vad_filter=False,  # Disable VAD filter as client handles it
            temperature=0.0,  # More deterministic output
        )

        # Join segments with proper spacing
        text = " ".join([s.text for s in segments]).strip()

        if not text:
            return {"text": ""}

        return {"text": text}

    except Exception as e:
        # Log the error and return a proper error response
        print(f"Transcription error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    finally:
        # Always clean up the temp file
        try:
            if temp_path.exists():
                os.unlink(temp_path)
        except Exception as e:
            print(f"Failed to delete temp file {temp_path}: {e}", flush=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8881, log_level="info")
