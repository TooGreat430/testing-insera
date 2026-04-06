import json
import os
import sys
import traceback

from function import run_ocr

if __name__ == "__main__":
    invoice_name = sys.argv[1]
    with_total_container = sys.argv[2].lower() == "true"
    pdf_paths = json.loads(sys.argv[3])

    try:
        run_ocr(
            invoice_name=invoice_name,
            uploaded_pdf_paths=pdf_paths,
            with_total_container=with_total_container
        )
    except Exception as e:
        print(f"[OCR WORKER ERROR] invoice={invoice_name} err={e}")
        traceback.print_exc()
    finally:
        for p in pdf_paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass