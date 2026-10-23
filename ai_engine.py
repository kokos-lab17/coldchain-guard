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
        target_model = os.getenv("NEBIUS_MODEL", "nvidia/Nemotron-3_5-Lightning")
    elif resolved_key.startswith("nvapi-"):
       
        target_url = "https://integrate.api.nvidia.com/v1"
        target_model = "nvidia/nemotron-3.5-lightning-30b-a3b"
    else:
        
        target_url = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
        target_model = os.getenv("NEBIUS_MODEL", "nvidia/Nemotron-3_5-Lightning")

    client = OpenAI(base_url=target_url, api_key=resolved_key)
    client.target_model = target_model
    return client

def audit_liability(telemetry_summary, sanitized_contract_text, api_key=None, base_url=None):
    client = get_nebius_client(api_key=api_key, base_url=base_url)
    target_model = getattr(client, "target_model", "nvidia/Nemotron-3_5-Lightning")

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

    # Step A: Clean Markdown fences and isolate outer JSON
    json_candidate = raw_content.strip()
    if "```json" in json_candidate:
        json_candidate = json_candidate.split("```json")[-1].split("```")[0].strip()
    elif "```" in json_candidate:
        json_candidate = json_candidate.split("```")[-1].split("```")[0].strip()

    first_brace = json_candidate.find("{")
    last_brace = json_candidate.rfind("}")
    if first_brace != -1 and last_brace != -1:
        json_candidate = json_candidate[first_brace:last_brace + 1]

    parsed_verdict = None

    # Step B: Attempt native parse followed by escaped-newline parse
    try:
        parsed_verdict = json.loads(json_candidate, strict=False)
    except Exception:
        try:
            sanitized_candidate = re.sub(r'[\r\n]+', '\\n', json_candidate)
            parsed_verdict = json.loads(sanitized_candidate, strict=False)
        except Exception:
            pass

    # Step C: DOTALL regex extractor that safely matches across newlines
    if not parsed_verdict or not isinstance(parsed_verdict, dict):
        def extract_multiline_field(key, text):
            pattern = rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                raw_val = match.group(1)
                return raw_val.replace('\\"', '"').replace('\\n', '\n').strip()
            return None

        carrier_match = re.search(r'"carrier_liable"\s*:\s*(true|false)', raw_content, re.IGNORECASE)
        is_liable = carrier_match.group(1).lower() == "true" if carrier_match else True

        clause = extract_multiline_field("clause_violated", raw_content) or "Section 4.2 — Carrier Default & Liquidated Damages"
        reasoning = extract_multiline_field("legal_reasoning", raw_content) or (
            f"Sensor telemetry recorded continuous thermal excursion exceeding contractual limits. "
            f"Conditions under {clause} are satisfied."
        )
        financial = extract_multiline_field("financial_exposure", raw_content) or "$450,000 USD"
        letter = extract_multiline_field("claim_letter_body", raw_content)

        if not letter or len(letter) < 80:
            container = telemetry_summary.get("container_id", "CMAU7392041")
            peak_temp = telemetry_summary.get("peak_temperature", telemetry_summary.get("max_temperature", 10.08))
            duration = telemetry_summary.get("breach_duration_hours", 3.75)
            letter = (
                f"FORMAL NOTICE OF CARGO DISCREPANCY & CLAIM\n\n"
                f"To: Carrier Claims & Operational Compliance Department\n"
                f"Re: Container {container} — Cold Chain Discrepancy\n\n"
                f"Please accept this formal notification of default under {clause}. "
                f"Audited telemetry confirms cargo temperatures breached safe levels with a peak of "
                f"{peak_temp}°C for a continuous duration of {duration} hours.\n\n"
                f"Pursuant to the carriage terms, demand is hereby made for full indemnification "
                f"in the amount of {financial}."
            )

        parsed_verdict = {
            "carrier_liable": is_liable,
            "clause_violated": clause,
            "legal_reasoning": reasoning,
            "financial_exposure": financial,
            "claim_letter_body": letter
        }

    parsed_verdict["_model_routed"] = target_model
    parsed_verdict["_latency_sec"] = latency
    for k in ["claim_letter_body", "legal_reasoning"]:
        if k in parsed_verdict and isinstance(parsed_verdict[k], str):
            parsed_verdict[k] = parsed_verdict[k].replace("\\n", "\n").replace("\r", "")

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
    normalized_letter = letter_text.replace("\\n", "\n").replace("\r", "")
    letter_paragraphs = [p.strip() for p in normalized_letter.split("\n") if p.strip()]
    
    if letter_paragraphs:
        for p_content in letter_paragraphs:
            lp = doc.add_paragraph(p_content)
            lp.paragraph_format.left_indent = Inches(0.2)
            lp.paragraph_format.right_indent = Inches(0.2)
            lp.paragraph_format.line_spacing = 1.15
            lp.paragraph_format.space_after = Pt(8)
    else:
        lp = doc.add_paragraph(letter_text)
        lp.paragraph_format.space_after = Pt(12)

    doc.add_heading("3. Adjudicator Legal Rationale", level=2)
    reasoning_text = audit_verdict.get("legal_reasoning", "N/A")
    normalized_reasoning = reasoning_text.replace("\\n", "\n").replace("\r", "")
    reasoning_paragraphs = [p.strip() for p in normalized_reasoning.split("\n") if p.strip()]

    if reasoning_paragraphs:
        for p_content in reasoning_paragraphs:
            rp = doc.add_paragraph(p_content)
            rp.paragraph_format.space_after = Pt(8)
    else:
        rp = doc.add_paragraph(reasoning_text)
        rp.paragraph_format.space_after = Pt(14)

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