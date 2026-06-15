from fastapi import FastAPI
import uvicorn
import os
from dotenv import load_dotenv
from app.api.feishu import router as feishu_router

load_dotenv()

app = FastAPI(title="Feishu Q&A Bot")

app.include_router(feishu_router, prefix="/feishu", tags=["feishu"])

@app.get("/")
async def root():
    return {"message": "Feishu Q&A Bot is running"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
