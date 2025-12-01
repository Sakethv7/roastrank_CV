import os
import sqlite3
import json
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

# -------------------------------------------------------
# INIT
# -------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()

# -------------------------------------------------------
# DB INIT
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
    detailed TEXT,
    strengths TEXT,
    improvements TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()

# -------------------------------------------------------
# FILE → TEXT EXTRACTION
# -------------------------------------------------------
def extract_text(file: UploadFile):
    name = file.filename.lower()

    if name.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file.file)
        return "\n".join([p.extract_text() or "" for p in reader.pages])

    if name.endswith(".docx"):
        doc = Document(file.file)
        return "\n".join([p.text for p in doc.paragraphs])

    return file.file.read().decode("utf-8", errors="ignore")


# -------------------------------------------------------
# BASIC NAME DETECTOR
# -------------------------------------------------------
def extract_name(text: str) -> str:
    lines = text.split("\n")
    for l in lines[:4]:
        l = l.strip()
        if 2 <= len(l.split()) <= 4:
            if all(x.isalpha() or x.isspace() for x in l):
                return l
    return "Anonymous"


# -------------------------------------------------------
# ROAST GENERATION
# -------------------------------------------------------
def roast(text: str, mode: str):

    QUICK_PROMPT = f"""
You are RoastRank. Produce a SHORT savage roast.

Return ONLY JSON with EXACTLY these keys:
- one_line
- overview
- fun_obs
- score

Rules:
- Overview must be factual but funny.
- 1–2 lines max per field.
- DO NOT include strengths, improvements or detailed content.

Resume:
{text}
"""

    FULL_PROMPT = f"""
You are RoastRank — strongest CV critic in the galaxy.

Return ONLY JSON with EXACTLY these keys:
- one_line
- overview
- detailed
- strengths
- improvements
- fun_obs
- score

Rules:
- Overview must be factual but funny.
- Keep every section SHORT (3–5 lines max).
- JSON only.

Resume:
{text}
"""

    prompt = FULL_PROMPT if mode == "full" else QUICK_PROMPT

    res = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    raw = res.output[0].content[0].text

    try:
        return json.loads(raw)
    except:
        # fallback
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed parsing JSON.",
            "detailed": "",
            "strengths": "",
            "improvements": "",
            "fun_obs": "",
            "score": 1
        }


# -------------------------------------------------------
# ROUTES
# -------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    text = extract_text(file)
    name = extract_name(text)
    data = roast(text, mode)

    cursor.execute("""
        INSERT INTO roasts(name, score, one_line, overview, detailed, strengths, improvements, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        data.get("score", 1),
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_obs", ""),
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": data.get("score", 1),
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_obs", "")
    })


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, overview, fun_obs, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })
