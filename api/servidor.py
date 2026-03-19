import os
import requests
from fastapi import FastAPI, Header, HTTPException
from dotenv import load_dotenv
import uvicorn

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")

app = FastAPI(title="Servidor puente valdi")

@app.get("/api/v1/proxy-report/location/{location_id}/date/{date}")
def obtener_reporte(location_id: str, date: str, x_api_key: str = Header(None)):
    if x_api_key != AITANNA_API_KEY:
        raise HTTPException(status_code=401, detail="Acceso denegado en el proxy")

    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{location_id}/date/{date}"
    headers = {"x-api-key": AITANNA_API_KEY}
    
    try:
        respuesta = requests.get(url, headers=headers)
        if respuesta.status_code == 200:
            return respuesta.json()
        raise HTTPException(status_code=respuesta.status_code, detail="Error en el origen remoto")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/get-all-locations-and-zones")
def obtener_ubicaciones(x_api_key: str = Header(None)):
    if x_api_key != AITANNA_API_KEY:
        raise HTTPException(status_code=401, detail="Acceso denegado en el proxy")
        
    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": AITANNA_API_KEY}
    
    try:
        respuesta = requests.get(url, headers=headers)
        if respuesta.status_code == 200:
            return respuesta.json()
        raise HTTPException(status_code=respuesta.status_code, detail="Error en el origen remoto")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)