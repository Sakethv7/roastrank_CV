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
import json5
import re

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

# ------------------ DATABASE ------------------
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

# ------------------ JSON EXTRACTION ------------------
def extract_json(raw):
    raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)
    matches = re.findall(r"\{.*?\}", raw, flags=re.DOTALL)
    if not matches:
        raise ValueError("No JSON found")
    candidate = max(matches, key=len)
    try:
        return json.loads(candidate)
    except:
        return json5.loads(candidate)

# ------------------ NAME EXTRACTION ------------------
def extract_name_from_text(text):
    prompt = f"""
Extract ONLY the candidate's full name from the resume text.

RULES:
- Return ONLY the name (first + last).
- No JSON.
- No commentary.
- If unsure → return "Anonymous".

Resume:
{text[:3000]}
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
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
        SELECT score, one_line || '\n\n' || detailed, created_at, name
        FROM roasts ORDER BY score DESC LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })

# ------------------ UPLOAD CV ------------------
@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- RATE LIMIT ----
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- If duplicate ----
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

    # ---------------- TEXT EXTRACTION ----------------
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
            return HTMLResponse("<h1>Unsupported file type</h1>")
    except:
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]

    # ---------------- NAME ----------------
    name = extract_name_from_text(text)

    # ---------------- PROMPT ----------------
    if mode == "quick":
        prompt = f"""
You are ROASTRANK. Give a very short roast.

Return ONLY this JSON:
{{
 "score": int,
 "one_line": str
}}

Max 4 lines. No long paragraphs.

Resume:
{text}
"""
    else:
        prompt = f"""
You are ROASTRANK — savage but concise.

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

Each field max 4–6 lines.

Resume:
{text}
"""

    # ---------------- AI CALL ----------------
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("ERROR:", e)
        if mode == "quick":
            data = {
                "score": 60,
                "one_line": "Your CV was so confusing even the AI gave up."
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

    # ---------------- SAVE ----------------
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
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

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
