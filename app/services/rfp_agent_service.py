from app.services.llm_service import llm_service
from typing import Dict, Any, Optional

class RFPAgentService:
    SUMMARIZE_PROMPT = """You are an intelligent RFP Analyst.
Task: Extract actionable intelligence from this Request for Proposal.

INSTRUCTIONS:
1. **Detect Language**: Translate content to English if necessary.
2. **Information Preservation**: Do not summarize away critical details like penalties or hard deadlines.
3. **Structure**: Output a structured HTML analysis styled with Tailwind CSS.

REQUIRED SECTIONS IN OUTPUT:
- **Snapshot**: Title, Issuer, Deadline, Budget (if visible).
- **Eligibility Check**: Valid certifications, years of experience required.
- **Scope Summary**: What exactly is being procured?
- **Submission Guidelines**: Format (PDF/Word), Portal URL, Physical submission address.
- **Key Dates**: Pre-bid meeting, Q&A deadline, Final submission.

OUTPUT FORMAT:
Return ONLY valid HTML code. Use a container div with Tailwind classes.

DOCUMENT TEXT:
{{document_text}}
"""

    async def summarize_rfp(self, document_text: str) -> Dict[str, Any]:
        prompt = self.SUMMARIZE_PROMPT.replace("{{document_text}}", document_text)
        system_prompt = "You are an expert RFP Analyst. Extract critical information and format it as structured, styled HTML."
        
        raw_response = await llm_service.unified_chat_completion(system_prompt, prompt)
        
        # Cleanup code fences if present
        clean_html = raw_response.strip()
        if clean_html.startswith("```"):
            clean_html = clean_html.replace("```html", "").replace("```", "").strip()
            
        success = "<html" in clean_html.lower() or "<div" in clean_html.lower()
        
        return {
            "raw": raw_response,
            "html": clean_html if success else None,
            "success": success,
            "error": None if success else "Failed to generate valid HTML"
        }

rfp_agent_service = RFPAgentService()
