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

# ============================================================
# 🔥 DELETE OLD DB EACH DEPLOY (HuggingFace temp storage reset)
# ============================================================
if os.path.exists("roasts.db"):
    print("🧹 Removing existing roasts.db...")
    os.remove("roasts.db")

# ============================================================
# INIT
# ============================================================
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

if api_key:
    print("✅ OpenAI API key loaded")
else:
    print("❌ No OPENAI_API_KEY found!")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ============================================================
# DATABASE
# ============================================================
conn = sqlite3.connect("roasts.db", check_same_thread=False)
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
  ip TEXT,
  date TEXT,
  count INTEGER,
  PRIMARY KEY(ip, date)
)
""")

conn.commit()

# ============================================================
# JSON CLEANER (NO json5 REQUIRED)
# ============================================================
def extract_json(raw: str):
    raw = raw.replace("```json", "").replace("```", "")
    blocks = re.findall(r"\{[\s\S]*?\}", raw)
    if not blocks:
        raise ValueError("No JSON detected")

    block = max(blocks, key=len)
    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)

    return json.loads(block)

# ============================================================
# NAME EXTRACTION
# ============================================================
def extract_name_from_text(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Extract ONLY the real full name of the candidate from this resume.
If unsure → return "Anonymous".
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

# ============================================================
# ROUTES
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute("""
        SELECT 
            name, score, one_line, overview, detailed, strengths, improvements, fun_obs, created_at
        FROM roasts
        ORDER BY score DESC
        LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })

# ============================================================
# UPLOAD & ROAST
# ============================================================
@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # Daily 10-upload limit
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # Check previous roast
    existing = cursor.execute("""
        SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs, name
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if existing:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "score": existing[0],
            "one_line": existing[1],
            "overview": existing[2],
            "detailed": existing[3],
            "strengths": existing[4],
            "improvements": existing[5],
            "fun_obs": existing[6],
            "name": existing[7]
        })

    # ============================================================
    # READ TEXT FROM FILE
    # ============================================================
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
        else:
            return HTMLResponse("<h1>Unsupported format</h1>")
    except:
        return HTMLResponse("<h1>File read error</h1>")

    text = text[:15000]

    # ============================================================
    # EXTRACT NAME
    # ============================================================
    name = extract_name_from_text(text)

    # ============================================================
    # BUILD PROMPT
    # ============================================================
    if mode == "quick":
        prompt = f"""
Return JSON ONLY:
{{
 "score": int,
 "one_line": str
}}

Resume:
{text}
"""
    else:
        prompt = f"""
Return JSON ONLY:
{{
 "score": int,
 "one_line": str,
 "overview": str,
 "detailed": str,
 "strengths": str,
 "improvements": str,
 "fun_obs": str
}}

Resume:
{text}
"""

    # ============================================================
    # CALL OPENAI
    # ============================================================
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("❌ ERROR:", e)
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

    score = data.get("score", 70)

    # ============================================================
    # SAVE TO DB
    # ============================================================
    cursor.execute("""
        INSERT INTO roasts (
            file_hash, name, score, one_line, overview, detailed,
            strengths, improvements, fun_obs
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash, name, score,
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_obs", "")
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

    # ============================================================
    # RETURN RESULT PAGE
    # ============================================================
    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": score,
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_obs", "")
    })
