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

# ======================================================
# 🔥 DELETE OLD DB ON STARTUP (RESET EACH DEPLOY)
# ======================================================
if os.path.exists("roasts.db"):
    print("🧹 Removing existing roasts.db to reset schema...")
    os.remove("roasts.db")

# ======================================================
# 🔥 INIT
# ======================================================
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

if api_key:
    print("✅ OpenAI API key loaded")
else:
    print("❌ ERROR: OPENAI_API_KEY missing in environment!")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ======================================================
# 🔥 DATABASE
# ======================================================
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

# Table for roasting output
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

# Table for rate-limiting (IMPORTANT)
cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
  ip TEXT,
  date TEXT,
  count INTEGER,
  PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ======================================================
# 🔥 JSON CLEANING
# ======================================================
def extract_json(raw: str):
    """Extract and clean JSON without json5."""
    raw = raw.replace("```json", "").replace("```", "")

    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if not matches:
        raise ValueError("No JSON block found")

    block = max(matches, key=len)

    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)

    return json.loads(block)

# ======================================================
# 🔥 NAME EXTRACTION
# ======================================================
def extract_name_from_text(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Extract ONLY the full name of the candidate from this resume.
Rules:
- Only return the name.
- If not sure, return "Anonymous".
- No commentary.

Resume text:
{text[:2500]}
"""
            }]
        )
        name = resp.choices[0].message.content.strip()

        # sanity check
        if len(name.split()) < 2 or len(name.split()) > 6:
            return "Anonymous"

        return name
    except Exception:
        return "Anonymous"

# ======================================================
# 🔥 ROUTES
# ======================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    rows = cursor.execute("""
        SELECT score, one_line || '\n\n' || detailed AS roast,
               created_at, name
        FROM roasts
        ORDER BY score DESC
        LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })


@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

    # ---- Rate limit ----
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    row = cursor.execute(
        "SELECT count FROM daily_limits WHERE ip=? AND date=?",
        (ip, today)
    ).fetchone()

    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily limit reached</h1>")

    # ---- Read file ----
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- Check cache ----
    cached = cursor.execute("""
        SELECT score, one_line, overview, detailed,
               strengths, improvements, fun_obs, name
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

    # ---- Extract resume text ----
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
                tmp_path = tmp.name
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(tmp_path)

        elif fn.endswith(".txt"):
            text = content.decode("utf-8")

        else:
            return HTMLResponse("<h1>Unsupported file type</h1>")

    except:
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]

    # ---- Extract candidate name ----
    name = extract_name_from_text(text)

    # ======================================================
    # 🔥 BUILD ROAST PROMPT
    # ======================================================
    if mode == "quick":
        prompt = f"""
Return ONLY JSON:
{{
 "score": int,
 "one_line": str
}}
Max 4 lines roast.

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
 "fun_observation": str
}}

Each section max 4–6 lines.

Resume:
{text}
"""

    # ======================================================
    # 🔥 CALL OPENAI
    # ======================================================
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.choices[0].message.content
        data = extract_json(raw)

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
                "fun_observation": ""
            }

    score = data.get("score", 70)

    # ======================================================
    # 🔥 SAVE TO DB
    # ======================================================
    cursor.execute("""
        INSERT INTO roasts (
            file_hash, score, one_line, overview, detailed,
            strengths, improvements, fun_obs, name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        score,
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_observation", ""),
        name
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0) + 1)
    """, (ip, today, ip, today))

    conn.commit()

    # ======================================================
    # 🔥 RETURN RESULT PAGE
    # ======================================================
    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": score,
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_observation", ""),
        "name": name
    })
