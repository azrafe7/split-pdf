from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import fitz  # PyMuPDF
import io
import zipfile
import json
import os

app = FastAPI()

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

class Rule(BaseModel):
    type: str  # "contains" or "not_contains"
    text: str

class SplitRequest(BaseModel):
    rules: List[Rule]

# Global variable to store the zip file in memory
zip_buffer = None

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), rules: str = Form(...)):
    global zip_buffer
    # Parse the rules
    rules = json.loads(rules)

    # Read the PDF file into memory
    pdf_content = await file.read()
    
    # Open the PDF from memory
    doc = fitz.open(stream=pdf_content, filetype="pdf")

    # Get the input file name without extension
    input_filename = os.path.splitext(file.filename)[0]

    # Initialize variables
    split_points = [0]  # Always start with the first page

    MAX_PAGES = 1000
    num_pages = min(doc.page_count, MAX_PAGES)

    # Find split points
    for page_num in range(num_pages):
        page = doc[page_num]
        text = page.get_text().lower()
        for rule in rules:
            if (rule['type'] == 'contains' and rule['text'].lower() in text) or \
               (rule['type'] == 'not_contains' and rule['text'].lower() not in text):
                split_points.append(page_num)
                break

    # Add the last page as a split point if it's not already included
    if doc.page_count - 1 not in split_points:
        split_points.append(num_pages - 1)
    split_points.append(num_pages)

    # Remove duplicates and sort
    split_points = sorted(list(set(split_points)))

    # Create split PDFs in memory
    output_pdfs = []
    total_output_pages = 0
    for i in range(len(split_points) - 1):
        start_page = split_points[i]
        end_page = split_points[i + 1]
        output_pdf = fitz.open()
        output_pdf.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)
        
        total_output_pages += output_pdf.page_count
        
        pdf_bytes = io.BytesIO()
        output_pdf.save(pdf_bytes)
        pdf_bytes.seek(0)
        output_pdfs.append((f"{input_filename}_part{i + 1}.pdf", pdf_bytes.getvalue()))

    # Verify page count
    #if total_output_pages != doc.page_count:
    #  raise HTTPException(status_code=500, detail="Page count mismatch: input and output PDFs have different number of pages")

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        for filename, content in output_pdfs:
            zip_file.writestr(filename, content)

    zip_buffer.seek(0)

    message = "PDF split successfully"
    if doc.page_count > MAX_PAGES:
        message += f' (only first {MAX_PAGES} pages processed)'
    
    # Return the zip file and the number of output PDFs
    return JSONResponse({
        "message": message,
        "num_pdfs": len(output_pdfs),
        "total_pages": total_output_pages,
        "download_url": "/download-zip"
    })

@app.get("/download-zip")
async def download_zip():
    global zip_buffer
    if zip_buffer is None:
        return JSONResponse({"error": "No zip file available"}, status_code=404)
    
    zip_buffer.seek(0)
    return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=split_pdfs.zip"})

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)