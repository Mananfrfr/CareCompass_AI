"""Build a silent, captioned 3:12 walkthrough from genuine captured demo screens.

Optional authoring dependencies: pip install pillow imageio-ffmpeg
Screenshots live in docs/demo/screens; generated intermediates stay in data/runtime/demo.
This is an edited screenshot walkthrough, not a continuous screen recording.
"""
from pathlib import Path
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/runtime/demo"
FONT = Path("C:/Windows/Fonts/segoeui.ttf")
BOLD = Path("C:/Windows/Fonts/segoeuib.ttf")
SCENES = [
    ("CareCompass AI", "From a health concern to a saved, sourced hospital shortlist.",
     "For patients and families in India. The full workflow runs inside ASI:One. This captioned walkthrough uses actual demo screenshots. Hospital and insurer records shown are fictional.", "shortlist.png"),
    ("ASI1 adds understanding", "Rules: no specialty. ASI1: orthopaedics.",
     'Synthetic input: "My doctor wrote lateral epicondylitis. I live in Jaipur and have Demo Shield insurance." A real API call added the service category. The stored conversation extraction is rules+asi1. This is navigation, not diagnosis.', "understanding.png"),
    ("Two specialist agents", "Independent tasks, one coordinated result.",
     "For this ASI:One case, the database records hospital-agent: succeeded, one attempt; insurer-agent: succeeded, one attempt. They return structured evidence. The model does not supply invented insurer network records.", "shortlist.png"),
    ("Conflicts stay visible", "Uncertainty is part of the answer.",
     "The fictional Amber Sports Injury Centre has conflicting insurer sources. CareCompass shows the disagreement and lowers confidence. A network listing never guarantees an individual claim or cashless approval.", "conflict.png"),
    ("Inspect the evidence", "Sources and limitations travel with each result.",
     "The detail view exposes source references and retrieval dates. Fixture URLs clearly identify synthetic evidence. The user can inspect the shortlist before deciding whether to save it.", "evidence.png"),
    ("Explicit approval", "The action is a verified save.",
     "The review card names the selected hospital, shortlist and action. It says no report text is stored or shared. Approval saves the shortlist and evidence; it does not book an appointment or contact a hospital.", "review.png"),
    ("Save once, verify it", "Reference CC-MWBAFGVE",
     "The saved action was read back and verified in SQLite with 16 evidence records. Repeating approve returned the same reference. Exactly one shortlist exists for this demonstration case.", "duplicate.png"),
    ("Ready to evaluate", "Working orchestration. Clear remaining limits.",
     "121 automated tests passed, plus a separate live OpenStreetMap test. Real ASI1 and the full card journey are verified. The shared invite works after sign-in, confirmed by the user. Free care briefs are available. Payments are a disabled test-mode prototype; real insurer data and always-on hosting remain future work. github.com/Mananfrfr/CareCompass_AI", "shortlist.png"),
]


def paragraph(draw, text, xy, font, width=42, fill="#cbd5e1", spacing=9):
    x, y = xy
    for line in textwrap.wrap(text, width):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + spacing
    return y


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for i, (title, subtitle, body, screenshot) in enumerate(SCENES):
        canvas = Image.new("RGB", (1280, 720), "#0b1423")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, 1280, 7), fill="#39d6ae")
        draw.text((38, 30), "CARECOMPASS AI  /  FETCH-A-THON 3.0", font=ImageFont.truetype(BOLD, 18), fill="#39d6ae")
        paragraph(draw, title, (38, 95), ImageFont.truetype(BOLD, 40), width=25, fill="white")
        paragraph(draw, subtitle, (38, 200), ImageFont.truetype(BOLD, 26), width=35, fill="#7ce6ce")
        paragraph(draw, body, (38, 298), ImageFont.truetype(FONT, 23), width=46)
        shot = Image.open(ROOT / "docs/demo/screens" / screenshot).convert("RGB")
        shot = ImageOps.contain(shot, (550, 650))
        canvas.paste(shot, (710 + (550-shot.width)//2, 34))
        draw.text((38, 661), f"{i+1:02d} / 08   |   Actual screenshots + measured evidence", font=ImageFont.truetype(FONT, 17), fill="#94a3b8")
        frame = OUT / f"scene-{i:02d}.png"
        canvas.save(frame)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(frame), "-t", "24", "-r", "12", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", str(OUT / f"scene-{i:02d}.mp4")], check=True)
    concat = OUT / "concat.txt"
    concat.write_text("\n".join(f"file 'scene-{i:02d}.mp4'" for i in range(len(SCENES))), encoding="utf-8")
    result = OUT / "CareCompass-demo.mp4"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(result)], check=True)
    print(result)


if __name__ == "__main__":
    main()
