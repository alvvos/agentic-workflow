import os
import google.generativeai as genai
from dotenv import load_dotenv

# Cargamos tu clave
load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

print("Modelos disponibles para tu API Key:")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print(f"Error al conectar: {e}")