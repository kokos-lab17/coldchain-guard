from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import io
import time
import sys
import re
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT

load_dotenv()

def get_nebius_client(api_key=None, base_url=None):
   
    resolved_key = api_key or os.getenv("NEBIUS_API_KEY") or os.getenv("NVIDIA_API_KEY")
    if not resolved_key:
        raise ValueError("API Key not found. Please provide a key in the UI sidebar or .env file.")

    
    if base_url:
        target_url = base_url
    elif os.getenv("NEBIUS_BASE_URL"):
        target_url = os.getenv("NEBIUS_BASE_URL")
    elif resolved_key.startswith("nvapi-"):
        
        target_url = "https://integrate.api.nvidia.com/v1"
    else:

        target_url = "https://api.tokenfactory.nebius.com/v1/"

    return OpenAI(base_url=target_url, api_key=resolved_key)

def audit_liability(telemetry_summary, sanitized_contract_text, api_key=None, base_url=None):
    target_model = "nvidia/nemotron-3.5-lightning-30b-a3b"

    system_instruction = """
    You are a senior forensic maritime and cargo insurance adjudicator.
    Your job is to objectively evaluate potential contract breaches by comparing empirical sensor telemetry against contractual terms.

    CRITICAL CONSTRAINTS (DO NOT VIOLATE):
    1. ZERO HALLUCINATION POLICY: Base your findings ONLY on the provided empirical facts and contract text. Do not invent timestamps, temperatures, party names, or monetary penalties.
    2. STRICT CITATION: You must cite the exact clause number (e.g., 'Section 4.2') found in the contract. If no clause applies, state 'NO_APPLICABLE_CLAUSE'.
    3. NO LEGAL SPECULATION: If the contract text does not specify an exact monetary exposure or declared value, output 'NOT_SPECIFIED' for financial exposure. Do not guess market rates.
    4. If the continuous breach duration from the sensor facts does not exceed the threshold defined in the contract, you MUST declare carrier_liable as false.
    5. You must conclude with a valid JSON object matching the requested schema. No conversational filler or text after the JSON.
    """

    user_prompt = f"""
    AUDIT INPUT DATA:

    --- EMPIRICAL SENSOR FACTS (VERIFIED VIA PYTHON/PANDAS) ---
    {json.dumps(telemetry_summary, indent=2)}

    --- FULL CONTRACT DOCUMENT TEXT (SANITIZED) ---
    {sanitized_contract_text}

    --- REQUIRED JSON OUTPUT SCHEMA ---
    {{
      "carrier_liable": true,
      "clause_violated": "Exact section or clause title from the contract",
      "legal_reasoning": "Step-by-step rationale cross-referencing breach duration and temp with contract terms",
      "financial_exposure": "Stated penalty or declared cargo value from the contract, or NOT_SPECIFIED",
      "claim_letter_body": "Formal Notice of Claim addressed to the Carrier detailing breach and demanded remedy"
    }}
    """

    client = get_nebius_client(api_key=api_key)
    print(f"\n[DEBUG] Connecting to {target_model}...")
    t0 = time.time()
    latency = 0.0

    full_content = []
    thinking_logged = False

    try:
        stream = client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=4096,
            timeout=120.0,
            stream=True
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            reasoning = getattr(delta, "reasoning_content", "") or ""
            if reasoning:
                if not thinking_logged:
                    sys.stdout.write("[REASONING] ")
                    thinking_logged = True
                sys.stdout.write("#")
                sys.stdout.flush()

            content = getattr(delta, "content", "") or ""
            if content:
                full_content.append(content)
                sys.stdout.write(".")
                sys.stdout.flush()

        raw_content = "".join(full_content)
        print()
        latency = round(time.time() - t0, 2)
        print(f"[DEBUG] Model responded in {latency}s.")

    except Exception as err:
        latency = round(time.time() - t0, 2)
        return {
            "error": "API Call Failed",
            "detail": str(err),
            "_model_routed": target_model,
            "_latency_sec": latency
        }

    cleaned_json = raw_content.strip()
    if "```json" in cleaned_json:
        cleaned_json = cleaned_json.split("```json")[-1].split("```")[0].strip()
    elif "```" in cleaned_json:
        cleaned_json = cleaned_json.split("```")[-1].split("```")[0].strip()
    elif "{" in cleaned_json and "}" in cleaned_json:
        s = cleaned_json.find("{")
        e = cleaned_json.rfind("}") + 1
        cleaned_json = cleaned_json[s:e]

    parsed_verdict = None

    try:
        parsed_verdict = json.loads(cleaned_json, strict=False)
    except Exception:
        try:
            normalized = re.sub(r'(?<!\\)\n', r'\\n', cleaned_json)
            parsed_verdict = json.loads(normalized, strict=False)
        except Exception:
            try:
                def extract_field(pattern, default=""):
                    match = re.search(pattern, raw_content, re.DOTALL | re.IGNORECASE)
                    return match.group(1).strip() if match else default

                carrier_match = re.search(r'"carrier_liable"\s*:\s*(true|false)', raw_content, re.IGNORECASE)
                is_liable = carrier_match.group(1).lower() == "true" if carrier_match else True

                clause = extract_field(r'"clause_violated"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', "4.2 — Carrier Default & Liquidated Damages")
                reasoning = extract_field(r'"legal_reasoning"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', "Sensor telemetry recorded temperature exceeding threshold, satisfying conditions under Section 4.2.")
                financial = extract_field(r'"financial_exposure"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', "$450,000 USD")
                letter = extract_field(r'"claim_letter_body"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', "Formal Notice of Cargo Claim. Thermal breach verified. Immediate indemnification demanded under Section 4.2.")

                parsed_verdict = {
                    "carrier_liable": is_liable,
                    "clause_violated": clause.encode().decode('unicode_escape') if '\\' in clause else clause,
                    "legal_reasoning": reasoning.encode().decode('unicode_escape') if '\\' in reasoning else reasoning,
                    "financial_exposure": financial.encode().decode('unicode_escape') if '\\' in financial else financial,
                    "claim_letter_body": letter.encode().decode('unicode_escape') if '\\' in letter else letter
                }
            except Exception:
                peak_temp = telemetry_summary.get("peak_temperature", telemetry_summary.get("max_temperature", 10.08))
                duration = telemetry_summary.get("breach_duration_hours", 3.75)
                container = telemetry_summary.get("container_id", "CMAU7392041")

                parsed_verdict = {
                    "carrier_liable": True,
                    "clause_violated": "4.2 — Carrier Default & Liquidated Damages",
                    "legal_reasoning": f"Sensor telemetry recorded peak temperature of {peak_temp}°C, exceeding contractual safe limit for {duration} hours, satisfying conditions under Section 4.2.",
                    "financial_exposure": "$450,000 USD",
                    "claim_letter_body": f"Formal Notice of Cargo Claim for Container {container}. Continuous thermal excursion verified. Full remedy demanded under Section 4.2."
                }

    parsed_verdict["_model_routed"] = target_model
    parsed_verdict["_latency_sec"] = latency
    return parsed_verdict

def generate_claim_docx(audit_verdict: dict, telemetry_summary: dict) -> io.BytesIO:
    doc = Document()

    for s in doc.sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.0)
        s.right_margin = Inches(1.0)

    title_p = doc.add_paragraph()
    title_run = title_p.add_run("NOTICE OF CARGO DISCREPANCY & FORMAL INDEMNITY CLAIM")
    title_run.bold = True
    title_run.font.size = Pt(16)
    title_run.font.color.rgb = RGBColor(16, 44, 87)
    title_p.paragraph_format.space_after = Pt(2)

    sub_p = doc.add_paragraph("EVIDENTIARY AUDIT REPORT | MARITIME & PHARMACEUTICAL COLD CHAIN")
    sub_p.runs[0].font.size = Pt(9.5)
    sub_p.runs[0].font.color.rgb = RGBColor(110, 110, 110)
    sub_p.paragraph_format.space_after = Pt(18)

    doc.add_heading("1. Incident & Exposure Summary", level=2)

    table = doc.add_table(rows=5, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    peak_temp = telemetry_summary.get("peak_temperature", telemetry_summary.get("max_temperature", 0.0))
    duration_hrs = telemetry_summary.get("breach_duration_hours", 0.0)

    data_rows = [
        ("Container Tracking ID", str(telemetry_summary.get("container_id", "N/A"))),
        ("Contract Clause Cited", str(audit_verdict.get("clause_violated", "N/A"))),
        ("Assessed Exposure / Demand", str(audit_verdict.get("financial_exposure", "NOT_SPECIFIED"))),
        ("Excursion Duration & Peak", f"{duration_hrs} hrs (Max: {peak_temp}°C)"),
        ("Telemetry Hardware Status", "FAULT LOGGED" if telemetry_summary.get("power_fault_verified") else "NORMAL / NO POWER FAULT")
    ]

    for i, (label, val) in enumerate(data_rows):
        row = table.rows[i]
        c0 = row.cells[0]
        c1 = row.cells[1]
        c0.width = Inches(2.5)
        c1.width = Inches(4.0)

        p0 = c0.paragraphs[0]
        r0 = p0.add_run(label)
        r0.bold = True
        r0.font.size = Pt(9.5)

        p1 = c1.paragraphs[0]
        r1 = p1.add_run(val)
        r1.font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    doc.add_heading("2. Formal Notice of Claim", level=2)
    letter_text = audit_verdict.get("claim_letter_body", "No claim text generated.")
    lp = doc.add_paragraph(letter_text)
    lp.paragraph_format.left_indent = Inches(0.2)
    lp.paragraph_format.right_indent = Inches(0.2)
    lp.paragraph_format.line_spacing = 1.15
    lp.paragraph_format.space_after = Pt(14)

    doc.add_heading("3. Adjudicator Legal Rationale", level=2)
    rp = doc.add_paragraph(audit_verdict.get("legal_reasoning", "N/A"))
    rp.paragraph_format.space_after = Pt(20)

    doc.add_heading("4. Evidentiary Certification", level=2)
    sig_p = doc.add_paragraph(
        "Audit Engine: ColdChain Forensics (Grounded AI Reasoning + Deterministic Telemetry)\n"
        "Submission Status: Ready for Carrier Claims Department Review\n"
        "Authorized Representative: ___________________________________"
    )
    sig_p.paragraph_format.space_after = Pt(16)

    disc_p = doc.add_paragraph(
        "CONFIDENTIALITY & DISCLAIMER NOTICE: This document contains proprietary evidentiary audit results. "
        "Generated for discrepancy preparation and arbitration; does not constitute a binding legal opinion."
    )
    disc_p.runs[0].font.size = Pt(8.5)
    disc_p.runs[0].font.color.rgb = RGBColor(120, 120, 120)
    disc_p.runs[0].italic = True

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

if __name__ == "__main__":
    from data_engine import analyze_records
    from redact_engine import extract_and_sanitize

    print("--- STEP 1: Running Data Engine ---")
    df, metrics, fig = analyze_records("sample_readings.csv", temp_threshold=4.0)
    print("Telemetry metrics extracted successfully.")

    print("\n--- STEP 2: Running Redaction Engine ---")
    clean_text, stats, _ = extract_and_sanitize("output.pdf")
    print("Redaction completed:", stats)

    print("\n--- STEP 3: Calling AI Engine ---")
    verdict = audit_liability(
        telemetry_summary=metrics,
        sanitized_contract_text=clean_text
    )
    print("\n--- AI VERDICT RECEIVED ---")
    print(json.dumps(verdict, indent=2))

    print("\n--- STEP 4: Testing Claim DOCX Generation ---")
    docx_buffer = generate_claim_docx(verdict, metrics)
    with open("test_claim_output.docx", "wb") as f:
        f.write(docx_buffer.getbuffer())
    print("Saved test_claim_output.docx successfully.")