# Email-to-Quote Underwriting Agent (Group Medical Insurance demo)

Importable agent for AgentCore that demonstrates the full underwriting flow:

inbound broker email + PDF attachments → document intelligence → field-level
validation → underwriting decision → configurable rating → quote PDF + broker
email (draft until approved).

```
Chat Input ─► 1. Email & Attachment Intake ─► 2. Document Intelligence ─► 3. Field-Level Validation
           ─► 4. Underwriting Decision ─► 5. Rating Engine ─► 6. Quote, Email & Dispatch ─► Chat Output
                                              ▲                                     ▲
                                  Large Language Model (Model Registry) ────────────┘  (optional)
```

## Files

| File | Purpose |
|---|---|
| `Email_to_Quote_Underwriting_Agent.json` | **Import this.** Full agent with the Large Language Model node wired in. |
| `Email_to_Quote_Underwriting_Agent_no_llm.json` | Same agent without the model node; fully deterministic, runs with no provider key. |
| `components/*.py` | Source of the six custom components (embedded in the JSON). |
| `samples/case_clean/` | Consistent submission → proceeds to rating and a quote PDF. |
| `samples/case_conflicting/` | 250 vs 248 employees, 3 inconsistent dates of birth, claims ₹42 lakh vs ₹45 lakh, missing policy expiry → clarification email, case on hold. |
| `generate_sample_documents.py` | Regenerates the synthetic PDFs (`python demo/underwriting/generate_sample_documents.py`). |
| `build_agent_json.py` | Rebuilds the JSON from the component sources (needs the backend running). |

All company names, people and amounts are fictional.

## Import and run

1. Start the stack (`.\start-demo.ps1`), log in, open **Agents** and import
   `Email_to_Quote_Underwriting_Agent.json` (Upload / Import agent).
2. Click the **Large Language Model** node, choose the provider and a model you
   registered in the Model Registry (Groq, OpenAI, Anthropic, Google, Azure
   OpenAI or an OpenAI-compatible endpoint). If you have no model yet, import
   the `_no_llm` variant instead or delete the model node; everything except the
   LLM wording polish and free-form PDF extraction still works.
3. Open the **Playground**, paste the broker email text and attach the four
   PDFs from `samples/case_conflicting` (or `case_clean`), then send.
   With no attachments the intake falls back to the bundled sample selected in
   **Bundled Sample Case** on node 1, so a plain "Run" already produces the
   conflicting-case demo.
4. The response shows the decision, the field-level validation table (source
   value, result, issue type, document/page/confidence evidence), the extracted
   data model, the rating breakdown, the drafted broker email and the audit
   trail. For the clean case the quote PDF is saved to the agent's file storage
   (and to **Output folder** on node 6 if set).

Suggested demo: run `case_clean` and `case_conflicting` side by side — one ends
in a quotation, the other in a clarification request.

## What each node does

1. **Email & Attachment Intake** – reads the email body and PDFs from the chat
   message, from files uploaded on the node, from a mock inbox folder
   (`email.txt` + PDFs) or from a bundled sample. Extracts text page by page.
2. **Document Intelligence** – rule-based extraction of 20 fields with document,
   page and confidence; parses the census and detailed-claims tables; optional
   LLM pass only for fields the rules could not find; builds the standard
   underwriting data model.
3. **Field-Level Validation** – mandatory fields, ISO-date/email formats,
   application-vs-census head-count, census row count vs declared total,
   date-of-birth vs stated age, claims summary vs detailed report, sum-insured
   range, missing documents. Each finding is PASS/FAIL/WARN and typed as
   extraction error, data discrepancy, missing field or missing document;
   material failures put the case on HOLD. Produces completeness and
   validation scores.
4. **Underwriting Decision** – `PROCEED_TO_QUOTE`, `REQUEST_CLARIFICATION`
   (material issues) or `REFER_TO_UNDERWRITER` (loss ratio, group size, sum
   insured or validation score outside the configurable auto-quote authority).
5. **Rating Engine** – deterministic premium from the editable JSON rating
   table on the node (age-band rates, sum-insured factor, dependant loading,
   claims-experience adjustment, minimum premium, GST shown separately). The
   LLM never sets a price. Replace the table or the node with the insurer's
   rating API when available.
6. **Quote, Email & Dispatch** – quotation PDF (reportlab), broker email for
   the decided action, optional LLM wording polish that is rejected if any
   figure changes, and controlled dispatch: draft by default; sending requires
   **Approved by authorised underwriter** plus `SMTP_*` settings in `.env`.

## Customising

- Field patterns: `FIELD_PATTERNS` in `underwriting_document_extractor.py`.
- Validation tolerances: node 3 (employee count, claims %).
- Authority limits: node 4. Rating table: node 5. Insurer name/signature: node 6.
- After editing a component file, run `build_agent_json.py` to regenerate the
  JSON, or paste the code into the node's code editor in the UI.
