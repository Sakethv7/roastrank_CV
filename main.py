from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import os
import io
import hashlib
from datetime import datetime
from dotenv import load_dotenv

from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json
import re

# ------------------ RESET DB ON DEPLOY (HF fix) ------------------
if os.getenv("HF_SPACE") is not None:
    if os.path.exists("roasts.db"):
        print("🧹 Removing roasts.db to auto-recreate schema...")
        os.remove("roasts.db")

# ------------------ INIT ------------------
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None
if api_key:
    print("✅ OpenAI API key loaded")
else:
    print("❌ No OpenAI API key found!")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------ DATABASE SETUP ------------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  score INTEGER,
  one_line TEXT,
  overview TEXT,
  detailed TEXT,
  strengths TEXT,
  improvements TEXT,
  fun_obs TEXT,
  name TEXT DEFAULT 'Anonymous',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ------------------ JSON CLEANER ------------------
def extract_json(raw: str):
    raw = raw.replace("```json", "").replace("```", "")
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("No JSON found")
    block = match.group()
    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)
    return json.loads(block)

# ------------------ NAME EXTRACTION ------------------
def extract_name_from_text(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Extract ONLY the candidate's real full name from this resume.
If unsure, return "Anonymous". No commentary.

Resume:
{text[:3000]}
"""
            }]
        )
        name = resp.choices[0].message.content.strip()
        if len(name.split()) > 6:
            return "Anonymous"
        return name
    except:
        return "Anonymous"

# ------------------ ROUTES ------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute("""
        SELECT score, name, one_line, created_at
        FROM roasts ORDER BY score DESC LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })

@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ----- Check cache -----
    cached = cursor.execute("""
        SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs, name
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if cached:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "score": cached[0],
            "one_line": cached[1],
            "overview": cached[2],
            "detailed": cached[3],
            "strengths": cached[4],
            "improvements": cached[5],
            "fun_obs": cached[6],
            "name": cached[7]
        })

    # ----- Extract text -----
    text = ""
    fn = file.filename.lower()

    try:
        if fn.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"
        elif fn.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                path = tmp.name
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(path)
        elif fn.endswith(".txt"):
            text = content.decode()
    except:
        return HTMLResponse("<h1>Error reading file</h1>")

    text = text[:15000]

    # ----- Extract name -----
    name = extract_name_from_text(text)

    # ----- Build prompt -----
    if mode == "quick":
        prompt = f"""
Return ONLY JSON:
{{
 "score": 50,
 "one_line": "string"
}}

ONE-LINE roast only.

Resume:
{text}
"""
    else:
        prompt = f"""
Return ONLY JSON:
{{
 "score": 50,
 "one_line": "string",
 "overview": "string",
 "detailed": "string",
 "strengths": "string",
 "improvements": "string",
 "fun_obs": "string"
}}

Each field must be max 3–5 lines.

Resume:
{text}
"""

    # ----- Generate roast -----
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("LLM ERROR:", e)
        data = {
            "score": 60,
            "one_line": "Your CV confused the AI.",
            "overview": "",
            "detailed": "",
            "strengths": "",
            "improvements": "",
            "fun_obs": ""
        }

    # ------------------ APPLY OPTION C SCORE ------------------
    orig = data.get("score", 60)
    roast_score = 70 + int((orig % 25))  # always 70–95

    # ------------------ SAVE TO DB ------------------
    cursor.execute("""
        INSERT INTO roasts (
            file_hash, score, one_line, overview, detailed,
            strengths, improvements, fun_obs, name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        roast_score,
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_obs", ""),
        name
    ))

    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": roast_score,
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_obs", ""),
        "name": name
    })
