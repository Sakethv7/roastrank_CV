from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import sqlite3
import hashlib
import tempfile
import os
import io
import json
import re

from datetime import datetime
from dotenv import load_dotenv

from PyPDF2 import PdfReader
from docx import Document
from openai import OpenAI

# ====================================================================================
# INIT
# ====================================================================================
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None
print("✅ OpenAI API key loaded" if api_key else "❌ Missing API Key")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ====================================================================================
# DATABASE INIT
# ====================================================================================
DB_PATH = "roasts.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  name TEXT DEFAULT 'Anonymous',
  score INTEGER,
  one_line TEXT,
  overview TEXT,
  detailed TEXT,
  strengths TEXT,
  improvements TEXT,
  fun_obs TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
  ip TEXT, date TEXT, count INTEGER,
  PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ====================================================================================
# JSON CLEANING
# ====================================================================================
def extract_json(raw):
    raw = raw.replace("```json", "").replace("```", "")

    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if not matches:
        raise ValueError("No JSON detected")

    block = max(matches, key=len)
    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)

    return json.loads(block)

# ====================================================================================
# NAME EXTRACTION
# ====================================================================================
def extract_name(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Extract ONLY the candidate's full real name. If unclear, return 'Anonymous'. Resume:\n{text[:2500]}"
            }]
        )
        name = resp.choices[0].message.content.strip()
        if len(name.split()) > 6:
            return "Anonymous"
        return name
    except:
        return "Anonymous"

# ====================================================================================
# ROUTES
# ====================================================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    rows = cursor.execute("""
        SELECT name, score, one_line, overview, detailed, strengths, improvements, fun_obs, created_at
        FROM roasts ORDER BY score DESC LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })

# ====================================================================================
# UPLOAD
# ====================================================================================
@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # --- Rate Limit ---
    row = cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today)).fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # --- Read File ---
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # --- Already roasted? ---
    existing = cursor.execute("""
        SELECT name, score, one_line, overview, detailed, strengths, improvements, fun_obs
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if existing:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "name": existing[0],
            "score": existing[1],
            "one_line": existing[2],
            "overview": existing[3],
            "detailed": existing[4],
            "strengths": existing[5],
            "improvements": existing[6],
            "fun_obs": existing[7]
        })

    # --- Extract Text ---
    text = ""
    fname = file.filename.lower()

    try:
        if fname.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"

        elif fname.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                path = tmp.name
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(path)

        elif fname.endswith(".txt"):
            text = content.decode()

        else:
            return HTMLResponse("<h1>Unsupported file format</h1>")
    except:
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]

    # --- Extract Name ---
    name = extract_name(text)

    # ====================================================================================
    # PROMPTS
    # ====================================================================================
    if mode == "quick":
        prompt = f"""
Return ONLY JSON:
{{
  "score": int,
  "one_line": str
}}

Rules:
- One-line roast must be punchy + funny.
- Max 1–2 sentences.
- Score range: 40–95.

Resume:
{text}
"""
    else:
        prompt = f"""
Return ONLY JSON:
{{
  "score": int,
  "one_line": str,
  "overview": str,
  "detailed": str,
  "strengths": str,
  "improvements": str,
  "fun_obs": str
}}

Rules:
- EACH SECTION must be ONLY 2–3 lines.
- No long paragraphs.
- One-line must be punchy and insulting in a fun way.
- Keep tone: 70% roast, 30% helpful.

Resume:
{text}
"""

    # ====================================================================================
    # LLM CALL
    # ====================================================================================
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        data = extract_json(resp.choices[0].message.content)

    except Exception as e:
        print("ERROR:", e)
        if mode == "quick":
            data = {
                "score": 60,
                "one_line": "Your CV confused the AI."
            }
        else:
            data = {
                "score": 65,
                "one_line": "Your CV confused the AI.",
                "overview": "",
                "detailed": "",
                "strengths": "",
                "improvements": "",
                "fun_obs": ""
            }

    # ====================================================================================
    # SAVE
    # ====================================================================================
    cursor.execute("""
        INSERT INTO roasts (
            file_hash, name, score, one_line, overview, detailed,
            strengths, improvements, fun_obs
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        name,
        data.get("score", 70),
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_obs", "")
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0) + 1)
    """, (ip, today, ip, today))

    conn.commit()

    # ====================================================================================
    # RENDER RESULT
    # ====================================================================================
    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": data.get("score", 70),
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_obs", "")
    })
