import os
import io
import json
import sqlite3
import tempfile
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

# -------------------------------------------------------
# FASTAPI APP
# -------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()

# -------------------------------------------------------
# DATABASE
# -------------------------------------------------------
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

# -------------------------------------------------------
# FILE → TEXT
# -------------------------------------------------------
def extract_text(file: UploadFile) -> str:
    ext = file.filename.lower()
    raw = file.file.read()

    # ---- PDF ----
    if ext.endswith(".pdf"):
        try:
            pdf = PyPDF2.PdfReader(io.BytesIO(raw))
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if text.strip():
                return text
        except:
            pass

    # ---- DOCX ----
    if ext.endswith(".docx"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            doc = Document(tmp_path)
            os.remove(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            if text.strip():
                return text
        except:
            pass

    # ---- TXT ----
    try:
        text = raw.decode("utf-8", errors="ignore")
        if text.strip():
            return text
    except:
        pass

    return ""


# -------------------------------------------------------
# NAME GUESS
# -------------------------------------------------------
def guess_name(text):
    lines = text.split("\n")[:5]
    for line in lines:
        line = line.strip()
        if 2 <= len(line.split()) <= 4:
            if all(c.isalpha() or c.isspace() for c in line):
                return line
    return "Anonymous"


# -------------------------------------------------------
# SAFE JSON
# -------------------------------------------------------
def safe_json(raw):
    try:
        return json.loads(raw)
    except:
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed JSON parsing.",
            "fun_obs": "",
            "score": 1
        }


# -------------------------------------------------------
# ROAST ENGINE
# -------------------------------------------------------
def roast_resume(text, mode):
    if not text.strip():
        return {
            "one_line": "Your file contains no readable text.",
            "overview": "Extraction failed — try uploading a cleaner PDF/DOCX.",
            "fun_obs": "",
            "score": 1
        }

    prompt = f"""
You are RoastRank — a brutal resume roasting AI.

Return ONLY JSON with exactly these keys:
one_line
overview
fun_obs
score

Rules:
- one_line: short + savage.
- overview: funny but factual (2 lines max).
- fun_obs: 1 punchline.
- score: integer 1–100.

Resume:
{text}
"""

    try:
        res = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )
        raw = res.output[0].content[0].text
        return safe_json(raw)
    except:
        return {
            "one_line": "AI roast engine crashed.",
            "overview": "Something broke during generation.",
            "fun_obs": "",
            "score": 1
        }


# -------------------------------------------------------
# ROUTES
# -------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    text = extract_text(file)
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
def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 40
    """)
    rows = cursor.fetchall()

    return templates.TemplateResponse(
        "leaderboard.html",
        {"request": request, "roasts": rows}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
