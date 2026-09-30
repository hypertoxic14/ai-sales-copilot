from faster_whisper import WhisperModel
import os

model = WhisperModel("base", device="cpu", compute_type="int8")

def transcribe_audio(file_path: str) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    segments, info = model.transcribe(file_path, beam_size=5)

    transcript = ""
    segs       = []
    for seg in segments:
        transcript += seg.text + " "
        segs.append({
            "start": round(seg.start, 2),
            "end":   round(seg.end, 2),
            "text":  seg.text.strip()
        })

    return {
        "transcript": transcript.strip(),
        "language":   info.language,
        "duration":   round(info.duration, 2),
        "segments":   segs
    }