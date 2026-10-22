from pypdf import PdfReader
import re

def extract_and_sanitize(source):
    
    reader = PdfReader(source)
    text = "\n".join(page.extract_text() for page in reader.pages)   
    
    patterns = {
        'email': r'[\w.+-]+@[\w-]+\.[\w.-]+',
        'ein':   r'EIN-\d{2}-\d{7}',
        'iban':  r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b',
    }

    redactions = {}
    diff_samples = []

    for label, pattern in patterns.items():
        found = list(set(re.findall(pattern, text)))
        redactions[label] = len(found)
        for item in found:
            if len(diff_samples) < 6:
                diff_samples.append({
                    "entity_type": label.upper(),
                    "raw": item,
                    "sanitized": f"[REDACTED_{label.upper()}]"
                })
            text = text.replace(item, f"[REDACTED_{label.upper()}]")

    return text, redactions, diff_samples

if __name__=="__main__":
    text, redactions=extract_and_sanitize("output.pdf")
    print("--- Redaction Statistics ---")
    print(redactions)
    print("\n--- Sanitized Contract Preview ---")
    print(text)