from pypdf import PdfReader

def extract_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() for page in reader.pages)

if __name__ == "__main__":
    text = extract_text("sample_invoice.pdf")
    print(f"--- {len(text)} chars extracted ---\n")
    print(text)
