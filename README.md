---
title: RoastRank
emoji: "🔥"
colorFrom: red
colorTo: pink
sdk: docker
app_file: main.py
pinned: false
---

# 🔥 RoastRank

<div align="center">

**The Brutal AI Resume Roasting Engine**

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-blue)](https://huggingface.co/spaces/Wanderingcoder/RoastRank)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991.svg)](https://openai.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

*Upload your resume. Get roasted by AI. Cry a little. Fix it. Repeat.*

[🚀 Try it Live](https://huggingface.co/spaces/Wanderingcoder/RoastRank) • [📖 Documentation](#features) • [🐛 Report Bug](https://github.com/Wanderingcoder/RoastRank/issues)

</div>

---

## 🎭 What is RoastRank?

RoastRank is a **savage standup comedian in AI form** that roasts tech resumes with surgical precision. Think *The Tech Roast Show* meets Silicon Valley. Upload your CV and receive brutally honest, hilariously specific feedback powered by OpenAI's GPT-4o-mini.

### Why RoastRank?

- ❌ **No more generic feedback** like "good resume" or "needs work"
- ✅ **Specific, actionable roasts** that reference YOUR actual content
- 🎤 **Standup comedy style** - witty, dark humor with perfect timing
- 📊 **Fair scoring (1-100)** - uses the full range, not just 45-55
- 🏆 **Public leaderboard** - see how you stack up against others

---

## ✨ Features

### 🎯 AI Roasting Modes

**Quick Roast** - Fast, punchy one-liner + fun observation  
**Full Roast** - One-liner, overview, detailed analysis, and killer punchline

### 🎨 Star Wars-Inspired UI

- 🌟 Cinematic intro text scroll
- ✨ Animated starfield background  
- 🎨 Neon cyber-sci-fi interface
- 🎬 Smooth animations and transitions

### 📄 Supported File Types

- **PDF** - Extracts text from all pages
- **DOCX** - Parses Word documents
- **TXT** - Plain text resumes

### 🏆 Features

- 🔥 **Top 50 leaderboard** - See the best (and worst) resumes
- 🤖 **Auto name extraction** - Pulls candidate names from resumes
- 🚫 **Duplicate detection** - Prevents spam submissions
- 💾 **SQLite storage** - Persistent roast history

---

## 🛠️ Tech Stack

| Category | Technology |
|----------|------------|
| **Backend** | Python, FastAPI, SQLite |
| **AI Model** | OpenAI GPT-4o-mini |
| **Frontend** | TailwindCSS, Jinja2, Canvas API |
| **Deployment** | Docker, Hugging Face Spaces |

---

## 📁 Project Structure

```
roastrank/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container configuration
├── README.md              # You are here
├── .env                   # Environment variables (not in git)
├── static/
│   ├── starfield.js       # Canvas animation
│   └── style.css          # Custom styles
└── templates/
    ├── index.html         # Landing page
    ├── result.html        # Roast results
    ├── duplicate.html     # Duplicate detection page
    └── leaderboard.html   # Top roasts
```

---

## 🚀 Local Setup

### 1. Clone the Repository

```bash
git clone https://huggingface.co/spaces/Wanderingcoder/RoastRank
cd RoastRank
```

### 2. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

Create a `.env` file in the root directory:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

Get your API key from [OpenAI Platform](https://platform.openai.com/api-keys)

### 5. Run the Application

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 7860
```

### 6. Open in Browser

Navigate to [http://localhost:7860](http://localhost:7860)

---

## 🐳 Docker Deployment

### Build and Run Locally

```bash
docker build -t roastrank .
docker run -p 7860:7860 -e OPENAI_API_KEY=your_key_here roastrank
```

---

## ☁️ Hugging Face Spaces Deployment

### 1. Create a New Space

1. Go to [Hugging Face Spaces](https://huggingface.co/spaces)
2. Click **Create new Space**
3. Choose **Docker** as SDK
4. Name it `RoastRank`

### 2. Add Secret

1. Go to **Settings** → **Variables and secrets**
2. Add a new secret:
   - **Name:** `OPENAI_API_KEY`
   - **Value:** Your OpenAI API key

### 3. Push Code

```bash
git remote add origin https://huggingface.co/spaces/YOUR_USERNAME/RoastRank
git add .
git commit -m "Initial commit"
git push origin main
```

Hugging Face will automatically build and deploy! 🎉

---

## 📡 API Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Landing page with upload form |
| `POST` | `/upload` | Upload and process resume |
| `GET` | `/leaderboard` | View top 50 roasted resumes |
| `GET` | `/test-api` | Test OpenAI API connection |

---

## 🎨 Example Roasts

> **Score: 23/100**  
> "You listed 'Microsoft Office' as a technical skill in 2024. What's next, bragging about your ability to use a stapler?"

> **Score: 67/100**  
> "Three internships and zero full-time roles—you're basically a professional coffee fetcher with a LinkedIn premium subscription."

> **Score: 89/100**  
> "Finally, someone who knows the difference between 'led a team' and 'attended team meetings.' Hire this person before they realize they're too good for you."

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📝 To-Do / Roadmap

- [ ] Add more roasting modes (corporate, academic, startup)
- [ ] Export roast as PDF/image for sharing
- [ ] User accounts and roast history
- [ ] Compare two resumes side-by-side
- [ ] Add resume improvement suggestions
- [ ] Multi-language support

---

## 🐛 Known Issues

- Name extraction may fail on heavily formatted resumes
- Very large PDFs (50+ pages) may timeout
- Duplicate detection is name-based only (not content-based)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **OpenAI** - For GPT-4o-mini API
- **Hugging Face** - For free Spaces hosting
- **FastAPI** - For the amazing web framework
- **The Tech Community** - For having resumes worth roasting

---

<div align="center">

**Made with 🔥 by [WanderingCoder](https://huggingface.co/Wanderingcoder)**

If this roasted your resume (in a good way), give it a ⭐ on GitHub!

</div>