import os
import io
import json
import sqlite3
import tempfile
import subprocess
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

# ============================================================
# FASTAPI APP INIT
# ============================================================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()

# ============================================================
# DATABASE INIT
# ============================================================
DB_PATH = "roasts.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    score INTEGER,
    one_line TEXT,
    overview TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()

# ============================================================
# TEXT EXTRACTION (PDF / DOCX / DOC / TXT)
# ============================================================

def extract_text_from_file(file: UploadFile) -> str:
    ext = file.filename.lower()
    raw_bytes = file.file.read()

    # --- PDF ---
    if ext.endswith(".pdf"):
        reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    # --- DOCX (must write to real file) ---
    if ext.endswith(".docx"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        try:
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
        finally:
            os.remove(tmp_path)

        return text

    # --- DOC (requires antiword, optional) ---
    if ext.endswith(".doc"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".doc") as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        try:
            output = subprocess.check_output(["antiword", tmp_path], text=True)
        except:
            output = "Document format not supported."
        finally:
            os.remove(tmp_path)

        return output

    # --- TXT ---
    return raw_bytes.decode(errors="ignore")


# ============================================================
# NAME DETECTION (simple but effective)
# ============================================================
def guess_name(text: str) -> str:
    candidates = text.split("\n")[:5]

    for line in candidates:
        cleaned = line.strip()
        if 2 <= len(cleaned.split()) <= 4:
            # ensure mostly letters + spaces
            if all(c.isalpha() or c == " " for c in cleaned):
                return cleaned

    return "Anonymous"


# ============================================================
# JSON CLEANING
# ============================================================
def safe_json_extract(model_output: str):
    try:
        return json.loads(model_output)
    except:
        # fallback
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed JSON parsing.",
            "fun_obs": "",
            "score": 1
        }


# ============================================================
# ROAST GENERATION
# ============================================================
def roast_resume(text: str, mode: str):
    if mode == "quick":
        prompt = f"""
You are RoastRank — a short and punchy roast generator.

Return ONLY JSON with keys:
one_line
overview
fun_obs
score

Rules:
- one_line: must be a roast.
- overview: factual but funny (2 lines max)
- fun_obs: 1 funny observation.
- score: integer between 1–100.

Resume:
{text}
"""
    else:
        prompt = f"""
You are RoastRank — the galactic lord of resume roasting.

Return ONLY JSON with keys:
one_line
overview
fun_obs
score

Rules:
- one_line: must be savage & short.
- overview: 2–3 lines max. Funny but true.
- fun_obs: 1 punchline.
- score: integer between 1–100.

Resume:
{text}
"""

    res = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    try:
        raw = res.output[0].content[0].text
        return safe_json_extract(raw)
    except:
        return {
            "one_line": "AI malfunction: roast overload.",
            "overview": "",
            "fun_obs": "",
            "score": 1
        }


# ============================================================
# ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    # Extract text
    text = extract_text_from_file(file)

    # Extract name
    name = guess_name(text)

    # Generate roast
    roast = roast_resume(text, mode)

    # Save
    cursor.execute("""
        INSERT INTO roasts (name, score, one_line, overview, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        name,
        roast["score"],
        roast["one_line"],
        roast["overview"],
        roast["fun_obs"],
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": roast["score"],
        "one_line": roast["one_line"],
        "overview": roast["overview"],
        "fun_obs": roast["fun_obs"]
    })


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()

    return templates.TemplateResponse(
        "leaderboard.html",
        {"request": request, "roasts": rows}
    )


# ============================================================
# RUN LOCALLY
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
