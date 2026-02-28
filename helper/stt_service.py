from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from faster_whisper import WhisperModel
import numpy as np
import time
import uvicorn
import shutil
import os
import tempfile
from pathlib import Path

app = FastAPI()

# Load model from the path we will pre-download to
model = WhisperModel(
    "small.en",  # Faster than distil-large-v3 (3-5x speedup)
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
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".wav", prefix="stt_"
    ) as temp_file:
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


@app.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    """
    Streaming transcription via WebSocket.

    Protocol:
    - Client sends binary audio chunks (int16 PCM @ 16kHz)
    - Client sends b"END" to signal end of speech and trigger transcription
    - Server returns {"text": "...", "type": "final"}
    - Server may send {"type": "buffering", "duration": X} during buffering

    No disk I/O - audio is buffered in memory as numpy array.
    """
    await websocket.accept()
    audio_buffer = np.array([], dtype=np.float32)
    SAMPLE_RATE = 16000
    END_SIGNAL = b"END"

    try:
        while True:
            data = await websocket.receive_bytes()

            if data == END_SIGNAL:
                # Transcribe the buffered audio
                audio_duration = len(audio_buffer) / SAMPLE_RATE
                transcribe_start = time.time()
                print(f"[STT] Starting transcription: {audio_duration:.2f}s audio", flush=True)
                
                if len(audio_buffer) > 0:
                    try:
                        segments, _ = model.transcribe(
                            audio_buffer,
                            beam_size=1,
                            vad_filter=False,
                            temperature=0.0,
                        )
                        text = " ".join([s.text for s in segments]).strip()
                        transcribe_time = (time.time() - transcribe_start) * 1000
                        print(f"[STT] Done in {transcribe_time:.0f}ms (RTF: {transcribe_time/1000/audio_duration:.3f})", flush=True)
                        await websocket.send_json({"type": "final", "text": text, "transcribe_ms": round(transcribe_time)})
                    except Exception as e:
                        print(f"Transcription error: {e}", flush=True)
                        await websocket.send_json({"type": "error", "message": str(e)})
                else:
                    await websocket.send_json({"type": "final", "text": ""})

                # Reset buffer for next utterance
                audio_buffer = np.array([], dtype=np.float32)
            else:
                # Convert int16 bytes to float32 and append to buffer
                chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                audio_buffer = np.concatenate([audio_buffer, chunk])

                # Optionally notify client of buffer status
                duration = len(audio_buffer) / SAMPLE_RATE
                await websocket.send_json(
                    {"type": "buffering", "duration": round(duration, 2)}
                )

    except WebSocketDisconnect:
        print("WebSocket client disconnected", flush=True)
    except Exception as e:
        print(f"WebSocket error: {e}", flush=True)
    finally:
        # Cleanup: buffer is freed when connection closes
        audio_buffer = None


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8881, log_level="info")
