"""Verification test for DeepParseService with updated vision model."""
import asyncio
import sys
import os
import base64

sys.path.insert(0, ".")

async def test():
    from app.services.deep_parse.deep_parse_service import deep_parse_service

    upload_dir = "app/static/uploads/deep-parse"
    files = [f for f in os.listdir(upload_dir) if f.endswith('.png')]
    if not files:
        print("No page images found")
        return

    # Sort files to get a consistent one
    files.sort()
    img_path = os.path.join(upload_dir, files[0])
    with open(img_path, "rb") as f:
        img_data = f.read()

    img_base64 = base64.b64encode(img_data).decode("utf-8")
    print(f"Testing with: {files[0]} ({len(img_data)} bytes)")

    page_info = {
        "page_number": 1,
        "image_url": f"/static/uploads/deep-parse/{files[0]}",
        "text": "",  # Trigger vision
        "img_base64": img_base64,
    }

    print("\nStarting extraction...")
    try:
        result = await deep_parse_service.process_page(page_info)
        print("\n=== Extraction Result ===")
        fields = result.get("fields", {})
        count = 0
        for key, val in fields.items():
            v = val.get("value", "")
            if v:
                print(f"  {key}: {v}")
                count += 1
        
        print(f"\nTotal fields extracted: {count}/20")
        
        if count > 0:
            print("\nSUCCESS: Data extraction is working!")
        else:
            print("\nFAILURE: No data extracted.")
            if "error" in result:
                print(f"Error: {result['error']}")

    except Exception as e:
        print(f"Exception during test: {e}")

asyncio.run(test())
