import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print(f"API Key loaded: {bool(api_key)}")
print(f"API Key (first 10 chars): {api_key[:10] if api_key else 'None'}")

genai.configure(api_key=api_key)

# Try to list available models
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ Available model: {m.name}")
except Exception as e:
    print(f"❌ Error listing models: {e}")

# Test a simple generation
try:
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content("Say hello")
    print(f"✅ Test generation successful: {response.text}")
except Exception as e:
    print(f"❌ Test generation failed: {e}")