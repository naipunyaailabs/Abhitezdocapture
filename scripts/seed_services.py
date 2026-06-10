import asyncio
import os
from datetime import datetime
from pathlib import Path

# Load .env from the project root (parent of scripts/) so the seeder
# uses the same MongoDB URI as the running app.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "docapture")

services = [
    {
        "id": "document-summarizer",
        "slug": "document-summarizer",
        "name": "Summa AI",
        "description": "Summarize any document with customizable length and detail",
        "longDescription": "Create comprehensive, balanced, or brief summaries of your documents. Supports various formats and uses advanced AI to capture key points.",
        "endpoint": "/summarize",
        "supportedFormats": ["html", "text", "markdown"],
        "supportedFileTypes": [".pdf", ".docx", ".doc", ".txt", ".jpg", ".png"],
        "icon": "FileText",
        "category": "Summarization",
        "fileFieldName": "document",
        "isActive": True
    },
    {
        "id": "rfp-creator",
        "slug": "rfp-creator",
        "name": "RFP Genius",
        "description": "Generate professional RFP documents automatically",
        "longDescription": "Create structured, professional Request for Proposal documents based on your requirements. Includes all standard sections and elaborate content.",
        "endpoint": "/rfp/create",
        "supportedFormats": ["docx"],
        "supportedFileTypes": [],
        "icon": "FilePlus",
        "category": "Generation",
        "fileFieldName": "none",
        "isActive": True
    },
    {
        "id": "rfp-summarizer",
        "slug": "rfp-summarizer",
        "name": "RFP Analyzer",
        "description": "Extract key requirements and insights from RFPs",
        "longDescription": "Upload complex RFP documents to get a structured summary of requirements, deadlines, and key deliverables.",
        "endpoint": "/summarize-rfp",
        "supportedFormats": ["html"],
        "supportedFileTypes": [".pdf", ".docx", ".doc", ".txt"],
        "icon": "Search",
        "category": "Analysis",
        "fileFieldName": "document",
        "isActive": True
    },
    {
        "id": "quotation-compare",
        "slug": "quotation-compare",
        "name": "Quotation Comparison",
        "description": "Compare multiple vendor quotations side-by-side",
        "longDescription": "Upload 2-10 quotations to receive a comprehensive comparison analysis, highlighting pricing, technical specs, and vendor strengths.",
        "endpoint": "/compare-quotations",
        "supportedFormats": ["markdown"],
        "supportedFileTypes": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"],
        "icon": "BarChart3",
        "category": "Analysis",
        "fileFieldName": "documents",
        "isActive": True
    },
    {
        "id": "groq-extraction",
        "slug": "groq-extraction",
        "name": "Deep Context AI Extraction",
        "description": "Perform deep contextual document analysis",
        "longDescription": "Use advanced AI models to perform deep contextual extraction of complex document data.",
        "endpoint": "/extract",
        "supportedFormats": ["json"],
        "supportedFileTypes": [".pdf", ".jpg", ".jpeg", ".png", ".docx", ".txt"],
        "icon": "BrainCircuit",
        "category": "AI Power Tool",
        "fileFieldName": "document",
        "isActive": True
    },
    {
        "id": "waste-downgrade",
        "slug": "waste-downgrade",
        "name": "Waste & Downgrade",
        "description": "Extract handwritten Wastage + Downgrade register sheets",
        "longDescription": "Upload handwritten or printed Wastage + Downgrade sheets (PDF or image). The AI extracts the page DATE plus every row across IO NO, A/B/C/D-GRADE, CHINDI, POUCHA, SELVAGE, PATTI and Total — ready for Excel export.",
        "endpoint": "/api/waste-downgrade/extract",
        "supportedFormats": ["excel", "json"],
        "supportedFileTypes": [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"],
        "icon": "ClipboardList",
        "category": "Table Extraction",
        "fileFieldName": "document",
        "isActive": True
    },
    {
        "id": "lot-history-cards",
        "slug": "lot-history-cards",
        "name": "Lot History Cards Extraction",
        "description": "Extract Abhitex Lot History Card (Grey Folding) forms",
        "longDescription": "Upload handwritten or printed Lot History Card (Grey Folding) forms (PDF or image). The AI extracts the header fields (I.O. No, Dye Lot No, Shade No, Quality M.No) plus every roll across Rope 1, Rope 2 and Rope 3 (Roll No, Total Pcs, Wt kg, Code) — ready for Excel export. Built to scale to thousands of cards.",
        "endpoint": "/api/lot-history-cards/extract",
        "supportedFormats": ["excel", "json"],
        "supportedFileTypes": [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"],
        "icon": "ClipboardList",
        "category": "Table Extraction",
        "fileFieldName": "document",
        "isActive": True
    }
]

async def seed():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    
    print("Clearing services...")
    await db.services.delete_many({})
    
    for s in services:
        s["createdAt"] = datetime.now()
        s["updatedAt"] = datetime.now()
        await db.services.insert_one(s)
        print(f"Seeded: {s['name']}")
        
    print("Done!")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed())
