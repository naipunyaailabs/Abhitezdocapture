import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = "docapture"

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
