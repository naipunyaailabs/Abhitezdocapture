import fitz  # PyMuPDF
from typing import List
import io

class PDFParser:
    async def extract_text(self, buffer: bytes) -> str:
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""

    async def get_page_count(self, buffer: bytes) -> int:
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            count = doc.page_count
            doc.close()
            return count
        except Exception as e:
            return 0

    async def pdf_to_images(self, buffer: bytes) -> List[bytes]:
        images = []
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            for page in doc:
                pix = page.get_pixmap()
                img_data = pix.tobytes("png")
                images.append(img_data)
            doc.close()
        except Exception as e:
            print(f"Error converting PDF to images: {e}")
        return images

pdf_parser = PDFParser()
