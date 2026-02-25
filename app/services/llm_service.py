import os
import httpx
from groq import AsyncGroq
from app.config import settings

class LLMService:
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def unified_chat_completion(
        self, 
        system: str, 
        user: str, 
        image_base64: str = None, 
        image_mime_type: str = "image/jpeg"
    ) -> str:
        client_type = settings.AI_CLIENT
        print(f"[unified_chat_completion] Using {client_type} client")

        try:
            if client_type == "ollama":
                return await self.ollama_chat_completion(system, user, image_base64, image_mime_type)
            else:
                return await self.groq_chat_completion(system, user, image_base64, image_mime_type)
        except Exception as e:
            print(f"[unified_chat_completion] Error with {client_type} client: {e}")
            raise Exception(f"Failed to process chat request with {client_type} client: {str(e)}")

    async def groq_chat_completion(
        self, 
        system: str, 
        user: str, 
        image_base64: str = None, 
        image_mime_type: str = "image/jpeg"
    ) -> str:
        # Use Llama 4 Scout for vision (multimodal), Llama 3.3 for text-only
        model = "meta-llama/llama-4-scout-17b-16e-instruct" if image_base64 else "llama-3.3-70b-versatile" 
        
        messages = [{"role": "system", "content": system}]
        
        if image_base64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_mime_type};base64,{image_base64}"
                        }
                    }
                ]
            })
        else:
            messages.append({"role": "user", "content": user})

        try:
            completion = await self.groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                top_p=0.95,
                stream=False,
                stop=None
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[groq_chat_completion] Error: {e}")
            raise

    async def ollama_chat_completion(
        self, 
        system: str, 
        user: str, 
        image_base64: str = None, 
        image_mime_type: str = "image/jpeg"
    ) -> str:
        model = "granite3.2-vision:latest" # Based on TS code
        
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]

        if image_base64:
            messages[1]["images"] = [image_base64]

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 4096
            }
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(f"{self.ollama_base_url}/api/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                content = result.get("message", {}).get("content", "")
                if not content:
                    raise Exception("No content in response")
                return content.strip()
            except Exception as e:
                print(f"[ollama_chat_completion] Error: {e}")
                raise

llm_service = LLMService()
