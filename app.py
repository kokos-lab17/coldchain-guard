import streamlit as st
from data_engine import analyze_records
from redact_engine import extract_and_sanitize
from ai_engine import audit_liability, generate_claim_docx

st.set_page_config(
    page_title="ColdChain Guard",
    layout="wide"
)


@st.cache_data(show_spinner=False)
def cached_audit_liability(telemetry_summary, sanitized_contract_text, api_key):
    return audit_liability(
        telemetry_summary=telemetry_summary,
        sanitized_contract_text=sanitized_contract_text,
        api_key=api_key
    )

st.title("ColdChain Guard")
st.subheader("Automated audit for temperature-sensitive cargo disputes")

with st.sidebar:
    st.markdown("### Settings")
    api_key_input = st.text_input("Nebius API Key (optional)", type="password", help="Leave blank to use .env key")
    safe_temp_limit = st.number_input("Max Safe Temperature (°C)", value=4.0, step=0.5)
    
    st.markdown("---")
    use_sample_data = st.checkbox("Use sample shipment files", value=True, help="Test the app instantly without uploading your own files")

col_upload, col_results = st.columns([1, 1.3], gap="large")

with col_upload:
    st.markdown("### 1. Upload Shipment Files")
    
    if use_sample_data:
        st.info("Loaded sample files for Container CMAU7392041 and its carriage agreement.")
        csv_file = "sample_readings.csv"
        pdf_file = "output.pdf"
    else:
        csv_file = st.file_uploader("Container sensor log (CSV)", type=["csv"])
        pdf_file = st.file_uploader("Shipping contract (PDF)", type=["pdf"])

    audit_button = st.button("Run Audit", type="primary", use_container_width=True)

if audit_button:
    if not csv_file or not pdf_file:
        st.warning("Please provide both the sensor CSV and the contract PDF to run the audit.")
    else:
        with st.spinner("Crunching sensor logs and checking contract terms with Nemotron..."):
            try:
                df, telemetry_data, chart = analyze_records(csv_file, temp_threshold=safe_temp_limit)
                clean_text, privacy_summary, diff_samples = extract_and_sanitize(pdf_file)

                verdict = cached_audit_liability(
                    telemetry_summary=telemetry_data,
                    sanitized_contract_text=clean_text,
                    api_key=api_key_input if api_key_input else None
                )

               
                st.session_state["audit_results"] = {
                    "chart": chart,
                    "telemetry_data": telemetry_data,
                    "clean_text": clean_text,
                    "privacy_summary": privacy_summary,
                    "diff_samples": diff_samples,
                    "verdict": verdict
                }
            except Exception as err:
                st.error(f"Couldn't finish the audit: {err}")

with col_results:
    st.markdown("### 2. Audit Findings")

    
    if "audit_results" in st.session_state:
        res = st.session_state["audit_results"]
        chart = res["chart"]
        telemetry_data = res["telemetry_data"]
        clean_text = res["clean_text"]
        privacy_summary = res["privacy_summary"]
        diff_samples = res["diff_samples"]
        verdict = res["verdict"]

        st.plotly_chart(chart, use_container_width=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Highest Temp", f"{telemetry_data.get('peak_temperature', 0.0)}°C")
        m2.metric("Time Above Safe Limit", f"{telemetry_data.get('breach_duration_hours', 0.0)} hrs")
        m3.metric("Flagged Readings", telemetry_data.get('breach_count', 0))
        fault_status = "Detected" if telemetry_data.get('power_fault_verified') else "None"
        m4.metric("Hardware Fault", fault_status)

        with st.expander("Privacy details: What was scrubbed locally"):
            st.write("These details were masked on your device before sending text to the cloud:")
            if diff_samples:
                st.dataframe(diff_samples, hide_index=True)
            else:
                st.json(privacy_summary)
            st.text_area("Sanitized contract text preview", clean_text[:1200] + "...", height=130)

        if verdict.get("error"):
            st.error("Something went wrong while running the audit model.")
            st.caption(verdict.get("detail", "Unknown error"))
        else:
            routed_model = verdict.get("_model_routed", "nvidia/nemotron-3.5-lightning-30b-a3b")
            st.success(" **Inference Stack:** `nvidia/nemotron-3.5-lightning-30b-a3b` running via **Nebius Token Factory**")

            is_carrier_at_fault = verdict.get("carrier_liable", False)
            broken_clause = verdict.get("clause_violated", "N/A")
            claim_amount = verdict.get("financial_exposure", "Not specified")

            if is_carrier_at_fault:
                st.error(f"Carrier at Fault — Violated {broken_clause}")
            else:
                st.success("Cargo Maintained Safely — No contract breach found.")

            st.metric("Estimated Compensation Due", claim_amount)

            st.markdown("#### Why this verdict was reached")
            st.write(verdict.get("legal_reasoning", "No explanation provided."))

            st.markdown("#### Generated Claim Letter")
            st.text_area("Ready-to-send draft", verdict.get("claim_letter_body", ""), height=180)

            docx_file = generate_claim_docx(verdict, telemetry_data)
            st.download_button(
                label="Download Claim Letter (.docx)",
                data=docx_file,
                file_name=f"Claim_Notice_{telemetry_data.get('container_id', 'Cargo')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
    else:
        st.info("Upload your shipment records or check 'Use sample shipment files', then click 'Run Audit'.")

st.markdown("---")
st.caption("Preliminary check only. Always consult a legal professional before filing formal claims.")