import os
import httpx
from groq import AsyncGroq
from app.config import settings

class LLMService:
    def __init__(self):
        self.groq_client = AsyncGroq(
            api_key=settings.GROQ_API_KEY,
            http_client=httpx.AsyncClient(
                verify=False,
                timeout=60.0
            )
        )
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def unified_chat_completion(
        self,
        system: str,
        user: str,
        image_base64: str = None,
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
        model: str = None,
        usage_user_id: str = None,
        usage_service_id: str = None,
    ) -> str:
        """Run a chat completion.

        If usage_user_id is provided, token usage for this call is recorded to
        the usage ledger (attributed to usage_service_id). This is the single
        chokepoint every extraction service flows through, so token accounting
        only needs to live here.
        """
        client_type = settings.AI_CLIENT
        print(f"[unified_chat_completion] Using {client_type} client, max_tokens={max_tokens}, model={model or 'default'}")

        # Fall back to the per-request usage context if the caller didn't pass
        # an explicit user id. This lets every existing call site record usage
        # without modification — routers set the context once per request.
        if usage_user_id is None:
            try:
                from app.services.usage_service import get_usage_context
                ctx_user, ctx_service = get_usage_context()
                usage_user_id = ctx_user
                if usage_service_id is None:
                    usage_service_id = ctx_service
            except Exception:
                pass

        try:
            if client_type == "ollama":
                content = await self.ollama_chat_completion(system, user, image_base64, image_mime_type, max_tokens)
                # Ollama does not report token usage; record nothing.
                return content
            else:
                content, usage = await self.groq_chat_completion_with_usage(
                    system, user, image_base64, image_mime_type, max_tokens, model=model,
                )
                if usage_user_id and usage:
                    await self._record_usage(usage_user_id, usage_service_id, usage, model)
                return content
        except Exception as e:
            print(f"[unified_chat_completion] Error with {client_type} client: {e}")
            raise Exception(f"Failed to process chat request with {client_type} client: {str(e)}")

    async def _record_usage(self, user_id, service_id, usage, model):
        """Best-effort: never let usage logging break an extraction."""
        try:
            from app.services.usage_service import usage_service
            await usage_service.record(
                user_id=user_id,
                service_id=service_id,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                model=model,
            )
        except Exception as e:
            print(f"[llm_service] usage record skipped: {e}")

    async def unified_chat_completion_with_logprobs(
        self,
        system: str,
        user: str,
        image_base64: str = None,
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
        model: str = None,
    ):
        """Like unified_chat_completion but also returns real token logprobs.

        Returns (content, token_logprobs). Logprobs are only produced by the
        Groq backend; Ollama returns None and callers fall back gracefully.
        """
        client_type = settings.AI_CLIENT
        if client_type == "ollama":
            content = await self.ollama_chat_completion(
                system, user, image_base64, image_mime_type, max_tokens
            )
            return content, None
        return await self.groq_chat_completion_with_logprobs(
            system, user, image_base64, image_mime_type, max_tokens,
            model=model, want_logprobs=True,
        )

    async def groq_chat_completion(
        self,
        system: str,
        user: str,
        image_base64: str = None,
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
        model: str = None,
    ) -> str:
        content, _ = await self.groq_chat_completion_with_logprobs(
            system, user, image_base64, image_mime_type, max_tokens,
            model=model, want_logprobs=False,
        )
        return content

    async def groq_chat_completion_with_usage(
        self,
        system: str,
        user: str,
        image_base64: str = None,
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
        model: str = None,
    ):
        """Return (content, usage_dict). usage_dict has prompt/completion/total
        tokens from the Groq response, or {} if unavailable."""
        if not model:
            model = "meta-llama/llama-4-scout-17b-16e-instruct" if image_base64 else "llama-3.3-70b-versatile"

        messages = [{"role": "system", "content": system}]
        if image_base64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:{image_mime_type};base64,{image_base64}"}},
                ],
            })
        else:
            messages.append({"role": "user", "content": user})

        completion = await self.groq_client.chat.completions.create(
            model=model, messages=messages, temperature=0.1,
            max_tokens=max_tokens, top_p=1.0, stream=False, stop=None,
        )
        content = completion.choices[0].message.content
        usage = {}
        u = getattr(completion, "usage", None)
        if u is not None:
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
        return content, usage

    async def groq_chat_completion_with_logprobs(
        self,
        system: str,
        user: str,
        image_base64: str = None,
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
        model: str = None,
        want_logprobs: bool = True,
    ):
        """Return (content, token_logprobs).

        token_logprobs is a list of {"token": str, "logprob": float} in the
        order the model emitted them, or None when logprobs were not requested
        or not available. These are REAL per-token confidences from the model
        and are used to score how certain each extracted value is.
        """
        # Caller may override the model (e.g. register OCR uses Maverick for
        # higher accuracy on handwriting). Otherwise default: Scout for vision,
        # 3.3 for text-only.
        if not model:
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

        kwargs = dict(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            top_p=1.0,
            stream=False,
            stop=None,
        )
        if want_logprobs:
            kwargs["logprobs"] = True

        try:
            completion = await self.groq_client.chat.completions.create(**kwargs)
        except Exception as e:
            # Some models reject logprobs; degrade gracefully to a plain call.
            if want_logprobs:
                print(f"[groq_chat_completion_with_logprobs] logprobs failed ({e}); retrying without.")
                kwargs.pop("logprobs", None)
                completion = await self.groq_client.chat.completions.create(**kwargs)
            else:
                print(f"[groq_chat_completion] Error: {e}")
                raise

        choice = completion.choices[0]
        content = choice.message.content

        token_logprobs = None
        lp = getattr(choice, "logprobs", None)
        content_lp = getattr(lp, "content", None) if lp else None
        if content_lp:
            token_logprobs = [
                {"token": t.token, "logprob": t.logprob}
                for t in content_lp
            ]

        return content, token_logprobs

    async def ollama_chat_completion(
        self, 
        system: str, 
        user: str, 
        image_base64: str = None, 
        image_mime_type: str = "image/jpeg",
        max_tokens: int = 4096,
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
                "num_predict": max_tokens
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
