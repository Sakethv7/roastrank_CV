import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

# ----------------------------------------------------
# FASTAPI SETUP
# ----------------------------------------------------
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()

# ----------------------------------------------------
# DATABASE
# ----------------------------------------------------
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

# ----------------------------------------------------
# FILE HANDLERS
# ----------------------------------------------------
def extract_text_from_file(file: UploadFile) -> str:
    ext = file.filename.lower()

    if ext.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file.file)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        return text

    elif ext.endswith(".docx"):
        doc = Document(file.file)
        text = "\n".join(p.text for p in doc.paragraphs)
        return text

    else:
        return file.file.read().decode("utf-8", errors="ignore")


# ----------------------------------------------------
# NAME DETECTION
# ----------------------------------------------------
def guess_name(text: str) -> str:
    lines = text.split("\n")
    for line in lines[:5]:
        clean = line.strip()
        if 2 <= len(clean.split()) <= 4:
            return clean
    return "Anonymous"


# ----------------------------------------------------
# ROASTING ENGINE
# ----------------------------------------------------
def roast_resume(text: str, mode: str):
    if mode == "quick":
        PROMPT = f"""
You are RoastRank — a savage and funny résumé roasting AI.

Return ONLY JSON with:
one_line
overview
fun_obs
score

Keep it short, sharp, and funny.

Resume:
{text}
"""
    else:
        PROMPT = f"""
You are RoastRank — the meanest resume critic in the galaxy.

Return ONLY JSON with:
one_line
overview
fun_obs
score

Rules:
- Make the roast tight and mean (NOT paragraphs)
- Overview should be factual BUT funny
- Fun observation must be sharp and witty
- Score between 1 and 100

Resume:
{text}
"""

    res = client.responses.create(
        model="gpt-4.1-mini",
        input=PROMPT
    )

    try:
        import json
        raw = res.output[0].content[0].text
        return json.loads(raw)
    except Exception:
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed to understand your resume.",
            "fun_obs": "Even robots have limits.",
            "score": 1
        }


# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------
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

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })


# ----------------------------------------------------
# LOCAL RUN MODE
# ----------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
