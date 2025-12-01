import os
import json
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

app = FastAPI()
client = OpenAI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# DB Setup
DB = "roasts.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    score INTEGER,
    one_line TEXT,
    overview TEXT,
    detailed TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()


# --- Extract text ---
def extract(file: UploadFile):
    fn = file.filename.lower()

    if fn.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file.file)
        return "\n".join(p.extract_text() or "" for p in reader.pages)

    if fn.endswith(".docx"):
        doc = Document(file.file)
        return "\n".join(p.text for p in doc.paragraphs)

    return file.file.read().decode("utf-8", "ignore")


# --- Guess name ---
def guess_name(text: str):
    first = text.split("\n")[0].strip()
    if len(first.split()) <= 5:
        return first
    return "Anonymous"


# --- Roast engine ---
def roast(text: str, mode: str):

    QUICK = f"""
Return ONLY JSON:
{{
  "one_line": "",
  "overview": "",
  "fun_obs": "",
  "score": 0
}}
Rules:
- 1 line per field
- Overview = factual + funny
- Score 1–100

Resume:
{text}
"""

    FULL = f"""
Return ONLY JSON:
{{
  "one_line": "",
  "overview": "",
  "detailed": "",
  "fun_obs": "",
  "score": 0
}}
Rules:
- Compact but savage
- Each field 2–4 lines max
- Overview = factual + funny
- No markdown
Resume:
{text}
"""

    prompt = FULL if mode == "full" else QUICK

    res = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    raw = res.output[0].content[0].text
    raw = raw.replace("```json", "").replace("```", "")
    raw = raw.replace(",}", "}").replace(",]", "]")

    try:
        return json.loads(raw)
    except:
        print("JSON FAIL:", raw)
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed parsing JSON.",
            "detailed": "",
            "fun_obs": "",
            "score": 1
        }


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):

    text = extract(file)
    name = guess_name(text)
    r = roast(text, mode)

    cursor.execute("""
        INSERT INTO roasts (name, score, one_line, overview, detailed, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        r["score"],
        r["one_line"],
        r.get("overview", ""),
        r.get("detailed", ""),
        r.get("fun_obs", ""),
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": r["score"],
        "one_line": r["one_line"],
        "overview": r.get("overview", ""),
        "detailed": r.get("detailed", ""),
        "fun_obs": r.get("fun_obs", "")
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
