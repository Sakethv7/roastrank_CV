from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import os, io, re, json, tempfile, hashlib
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document

# ---------------- INIT ----------------
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None
if api_key:
    print("✅ OpenAI key loaded")
else:
    print("❌ No OpenAI key found")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------------- DB ----------------
if os.path.exists("roasts.db"):
    os.remove("roasts.db")  # start fresh (HF persists FS only if saved)

conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  name TEXT,
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
conn.commit()


# ---------------- UTIL: JSON parser ----------------
def extract_json(raw: str):
    raw = raw.replace("```json", "").replace("```", "")
    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if not matches:
        raise ValueError("No JSON found")
    block = max(matches, key=len)
    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)
    block = block.replace("\n", " ")
    return json.loads(block)


# ---------------- UTIL: NAME extractor ----------------
def extract_name(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Extract ONLY the candidate's real full name. If unsure return 'Anonymous'. Resume:\n{text[:2500]}"
            }]
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Anonymous"


# ---------------- ROUTES ----------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    rows = cursor.execute("""
        SELECT name, score, one_line, detailed, created_at
        FROM roasts ORDER BY score DESC LIMIT 50
    """).fetchall()
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...), mode: str = Form("quick")):

    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ----- If roasted before → return cached -----
    existing = cursor.execute("""
        SELECT name, score, one_line, overview, detailed,
               strengths, improvements, fun_obs
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

    # ----- Extract text -----
    text = ""
    name = file.filename.lower()

    try:
        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"

        elif name.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                temp_path = tmp.name
            doc = Document(temp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.remove(temp_path)

        else:
            text = content.decode()

    except:
        return HTMLResponse("<h1>Error reading file</h1>")

    text = text[:15000]
    candidate_name = extract_name(text)

    # ----- PROMPTS -----
    if mode == "quick":
        prompt = f"""
Return ONLY JSON with fields:
{{
 "score": <0-100>,
 "one_line": "<1 short savage sentence>"
}}
Resume:
{text}
"""
    else:
        prompt = f"""
Return ONLY VALID JSON with ALL of these fields:
{{
 "score": <0-100>,
 "one_line": "<1 sharp roast>",
 "overview": "<2 lines>",
 "detailed": "<3-4 brutal roast lines>",
 "strengths": "<2 strengths>",
 "improvements": "<2 improvements>",
 "fun_observation": "<1 quirky roast>"
}}
Resume:
{text}
"""

    # ----- CALL OPENAI -----
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        data = extract_json(resp.choices[0].message.content)

    except Exception as e:
        print("ERROR:", e)
        if mode == "quick":
            data = {"score": 60, "one_line": "Your CV confused the AI."}
        else:
            data = {
                "score": 65,
                "one_line": "Your CV confused the AI.",
                "overview": "Model error.",
                "detailed": "Your resume broke the AI.",
                "strengths": "You exist.",
                "improvements": "Upload again.",
                "fun_observation": "AI crashed trying to roast you."
            }

    # ----- SAVE -----
    cursor.execute("""
        INSERT INTO roasts
        (file_hash, name, score, one_line, overview,
         detailed, strengths, improvements, fun_obs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        candidate_name,
        data.get("score", 70),
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_observation", "")
    ))
    conn.commit()

    # ----- RETURN -----
    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": candidate_name,
        "score": data.get("score", 70),
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_observation", "")
    })
