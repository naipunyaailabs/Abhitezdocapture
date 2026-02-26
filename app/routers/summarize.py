from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.services.extract_service import extract_service
from app.services.llm_service import llm_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
from typing import Optional

router = APIRouter()

@router.post("")
async def summarize_document(
    document: UploadFile = File(...),
    prompt: str = Form(""),
    length: str = Form("medium"),
    current_user: UserResponse = Depends(get_current_user)
):
    import time
    start_time = time.time()
    try:
        # Check if user can process
        can_process, sub, message = await subscription_service.can_process(current_user.userId)
        if not can_process:
            raise HTTPException(
                status_code=403,
                detail=f"Processing limit reached. {message}. Please upgrade your plan."
            )
        
        buffer = await document.read()
        print(f"[summarize] Received file: {document.filename}, size: {len(buffer)}")
        text = await extract_service.extract_doc(buffer, document.filename, document.content_type)
        print(f"[summarize] Extracted text length: {len(text)}")
        
        # TOON format logic from TS
        clean_text = text.replace('\n', ' ').replace(',', ';')
        document_toon = f"document{{filename,content}}:\n{document.filename},{clean_text}"
        
        # Enhanced Prompts
        system_message = """You are an expert Document Analyst and Executive Summarizer. 
Your goal is to extract critical intelligence from documents and present it in a highly structured, professional HTML format.
Use Tailwind CSS classes for styling. Focus on clarity, strategic insights, and actionable takeaways.
Do not include any conversational preamble. Return ONLY the HTML content."""

        base_html_structure = """
<div class="bg-card rounded-xl border border-glass p-6 space-y-6">
    <div class="flex items-center gap-4 mb-4 border-b border-glass pb-4">
        <div class="p-3 bg-primary/10 rounded-lg text-primary">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
        </div>
        <div>
            <h2 class="text-xl font-bold text-main">Executive Summary</h2>
            <p class="text-sm text-muted">AI-Generated Analysis</p>
        </div>
    </div>
    
    <div class="prose prose-invert max-w-none text-main">
        {{CONTENT}}
    </div>
</div>
"""

        if length.lower() == "detailed":
            summarization_prompt = f"""
Analyze the following document in extreme detail. Focus: {prompt or 'General Analysis'}.

Required Sections:
1. **Executive Overview**: High-level summary of the document's purpose and key findings.
2. **Key Themes & Insights**: detailed breakdown of major topics.
3. **Critical Data Points**: Extract specific numbers, dates, and metrics.
4. **Strategic Implications**: What this means for the stakeholder.
5. **Recommendations/Next Steps**: Actionable advice based on the content.

Format as semantic HTML (h3, ul, p, strong) inside the content area. Use Tailwind classes like 'text-primary' for key terms.

Document Context:
{document_toon}
"""
        elif length.lower() == "short":
             summarization_prompt = f"""
Provide a concise, high-impact summary. Focus: {prompt or 'Key Points'}.

Required Sections:
1. **The Bottom Line**: One paragraph summary.
2. **Top 3 Takeaways**: Bullet points.

Format as semantic HTML inside the content area.

Document Context:
{document_toon}
"""
        else: # Medium/Standard
             summarization_prompt = f"""
Provide a balanced professional summary. Focus: {prompt or 'General Overview'}.

Required Sections:
1. **Overview**: Context and purpose.
2. **Key Findings**: Structured bullet points of main ideas.
3. **Important Details**: Any specific clauses, terms, or data.
4. **Conclusion**: Wrap up.

Format as semantic HTML inside the content area.

Document Context:
{document_toon}
"""
        
        # Get raw content
        raw_summary = await llm_service.unified_chat_completion(system_message, summarization_prompt)
        
        # Clean up and wrap
        clean_content = raw_summary.replace("```html", "").replace("```", "").strip()
        summary = base_html_structure.replace("{{CONTENT}}", clean_content)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "document-summarizer",
            "serviceName": "Document Summarization",
            "fileName": document.filename,
            "fileSize": len(buffer),
            "format": "html",
            "status": "success",
            "result": summary,
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": {
                    "summary": summary.strip()
                },
                "logs": []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
