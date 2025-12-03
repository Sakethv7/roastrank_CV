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
# FASTAPI INIT
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
# FILE → TEXT EXTRACTION
# ============================================================

def extract_text_from_pdf(raw_bytes: bytes) -> str:
    """Try PyPDF2 first, then pdftotext for reliability."""
    text = ""

    # ---------- Try PyPDF2 ----------
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
        for p in reader.pages:
            chunk = p.extract_text()
            if chunk:
                text += chunk + "\n"
    except:
        pass

    # If PyPDF2 failed or returned empty → try poppler's pdftotext
    if len(text.strip()) < 20:  
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(raw_bytes)
            pdf_path = tmp.name

        try:
            text = subprocess.check_output(
                ["pdftotext", pdf_path, "-"],
                text=True,
                stderr=subprocess.DEVNULL
            )
        except:
            text = ""

        os.remove(pdf_path)

    return text.strip()


def extract_text_from_file(file: UploadFile) -> str:
    filename = file.filename.lower()
    raw = file.file.read()

    # -------- PDF --------
    if filename.endswith(".pdf"):
        return extract_text_from_pdf(raw)

    # -------- DOCX --------
    if filename.endswith(".docx"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(raw)
            path = tmp.name

        try:
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
        finally:
            os.remove(path)

        return text

    # -------- DOC (requires antiword) --------
    if filename.endswith(".doc"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".doc") as tmp:
            tmp.write(raw)
            path = tmp.name

        try:
            out = subprocess.check_output(["antiword", path], text=True)
        except:
            out = ""
        finally:
            os.remove(path)

        return out

    # -------- TXT --------
    return raw.decode(errors="ignore")


# ============================================================
# NAME DETECTION
# ============================================================
def guess_name(text: str) -> str:
    for line in text.split("\n")[:5]:
        l = line.strip()
        if 2 <= len(l.split()) <= 4 and all(c.isalpha() or c == " " for c in l):
            return l
    return "Anonymous"


# ============================================================
# JSON CLEANER
# ============================================================
def safe_json_extract(raw: str):
    try:
        return json.loads(raw)
    except:
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed JSON parsing.",
            "fun_obs": "",
            "score": 1
        }


# ============================================================
# ROAST ENGINE
# ============================================================
def roast_resume(text: str, mode: str):
    if len(text.strip()) < 30:
        return {
            "one_line": "Your PDF looks emptier than a fresher’s LinkedIn.",
            "overview": "No readable text found in your file.",
            "fun_obs": "Try exporting your resume as a real PDF.",
            "score": 1
        }

    prompt = f"""
You are RoastRank — a savage but funny resume roasting AI.
Return ONLY VALID JSON with:

one_line
overview
fun_obs
score

Rules:
- one_line: savage + short.
- overview: factual but funny (2–3 lines).
- fun_obs: one funny punchline.
- score: integer 1–100.

Resume text:
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
            "overview": "Model produced invalid output.",
            "fun_obs": "Maybe your CV scared the model.",
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
    text = extract_text_from_file(file)
    name = guess_name(text)
    roast = roast_resume(text, mode)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
