import json
import os
import sys
import traceback

from function import run_ocr, run_grouped_ocr


def _collect_paths(obj):
    paths = []

    if isinstance(obj, dict):
        for v in obj.values():
            paths.extend(_collect_paths(v))
    elif isinstance(obj, list):
        for item in obj:
            paths.extend(_collect_paths(item))
    elif isinstance(obj, str):
        paths.append(obj)

    return paths


if __name__ == "__main__":
    invoice_name = sys.argv[1]
    with_total_container = sys.argv[2].lower() == "true"
    payload = json.loads(sys.argv[3])

    try:
        # backward-compatible:
        # - kalau payload list -> flow lama
        # - kalau payload dict -> flow grouping baru
        if isinstance(payload, list):
            run_ocr(
                invoice_name=invoice_name,
                uploaded_pdf_paths=payload,
                with_total_container=with_total_container
            )
        else:
            run_grouped_ocr(
                invoice_name=invoice_name,
                uploaded_docs=payload,
                with_total_container=with_total_container
            )

    except Exception as e:
        print(f"[OCR WORKER ERROR] invoice={invoice_name} err={e}")
        traceback.print_exc()

    finally:
        for p in set(_collect_paths(payload)):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass