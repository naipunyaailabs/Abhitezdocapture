import time
print("Testing pytesseract import...")
s = time.time()
import pytesseract
print(f"pytesseract imported in {time.time()-s:.2f}s")

print("Testing fitz import...")
s = time.time()
import fitz
print(f"fitz imported in {time.time()-s:.2f}s")
