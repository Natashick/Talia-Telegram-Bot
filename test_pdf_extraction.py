from pdf_parser import extract_paragraphs_from_pdf
import sys

if len(sys.argv) < 2:
    print("Usage: python test_pdf_extraction.py <PDF_FILE>")
    sys.exit(1)

pdf_file = sys.argv[1]
paragraphs = extract_paragraphs_from_pdf(pdf_file)

for i, para in enumerate(paragraphs):
    print(f"--- Paragraph {i+1} ---\n{para}\n") 