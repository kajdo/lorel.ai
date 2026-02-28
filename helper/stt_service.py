from fastapi import FastAPI, UploadFile, File
from faster_whisper import WhisperModel
import uvicorn
import shutil
import os


app = FastAPI()
# Load model from the path we will pre-download to
model = WhisperModel("/app/models/whisper", device="cuda", compute_type="float16")


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    with open("temp.wav", "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    segments, _ = model.transcribe("temp.wav", beam_size=1)
    text = " ".join([s.text for s in segments]).strip()
    return {"text": text}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8881)
