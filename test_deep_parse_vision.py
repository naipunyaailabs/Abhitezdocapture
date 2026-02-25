"""Test vision extraction with correct Groq model ID."""
import asyncio, sys, os, base64
sys.path.insert(0, ".")

async def main():
    from app.services.llm_service import llm_service
    from groq import AsyncGroq
    from app.config import settings
    
    # Update model in llm_service instance directly for testing
    llm_service.groq_model_vision = "meta-llama/llama-4-scout-17b-16e-instruct"
    
    upload_dir = "app/static/uploads/deep-parse"
    files = [f for f in os.listdir(upload_dir) if f.endswith('.png')]
    if not files:
        print("No page images found")
        return

    img_path = os.path.join(upload_dir, files[0])
    with open(img_path, "rb") as f:
        img_data = f.read()
    
    img_b64 = base64.b64encode(img_data).decode("utf-8")
    print(f"Testing vision with {files[0]} ({len(img_data)} bytes)")
    
    try:
        # We need to monkeypatch the groq_chat_completion to use our test model
        # or just call it after updating the code.
        # For now, let's just make a direct call using the client.
        print(f"Calling Groq directly with model: {llm_service.groq_model_vision}")
        
        system = "Extract the supplier name from this invoice image. Return just the name."
        user = "What is the supplier/company name in this invoice?"
        
        # Manually construct messages for vision
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}"
                        }
                    }
                ]
            }
        ]
        
        completion = await llm_service.groq_client.chat.completions.create(
            model=llm_service.groq_model_vision,
            messages=messages,
            temperature=0.2
        )
        print(f"VISION SUCCESS: {completion.choices[0].message.content}")
        
    except Exception as e:
        print(f"VISION FAILED: {e}")

asyncio.run(main())
