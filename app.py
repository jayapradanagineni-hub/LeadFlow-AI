from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import leadflow

app = FastAPI(title="LeadFlow AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Lead(BaseModel):
    name: str
    requirement: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    budget_inr: Optional[float] = 0
    industry: Optional[str] = None
    source: Optional[str] = None

@app.get("/")
def home():
    return {"message": "LeadFlow AI is running"}

@app.get("/api/leads")
def get_leads():
    conn = leadflow.connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

@app.post("/api/leads")
def create_lead(lead: Lead):
    conn = leadflow.connect_db()
    try:
        result = leadflow.process_one(conn, lead.model_dump())
        return result
    finally:
        conn.close()