from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "healthy"}

@app.get("/health")
def health():
    return "OK"

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
