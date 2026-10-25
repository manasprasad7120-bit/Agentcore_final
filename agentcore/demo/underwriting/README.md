# Email-to-Quote Underwriting Agent (Group Medical Insurance demo)

Importable agents for AgentCore built **only from the standard components that
already exist in the product UI** (Chat Input, Outlook Mail, File, Prompt
Template, Large Language Model, Chat Output). No custom components and no OCR
node: the LLM reads the email and the extracted attachment text directly and
performs extraction, field-level validation, the underwriting decision, the
rating (from the rating table in the prompt) and the broker email draft.

```
Chat Input ──────────────┐
Outlook Mail (read_mail) ─┴─► Prompt Template ─► Large Language Model ─► Chat Output
```

## Files

| File | Purpose |
|---|---|
| `Email_to_Quote_Underwriting_Agent.json` | **Live inbox version (import this).** Outlook Mail reads the newest broker email with its attachments from the mailbox linked through the Outlook connector. |
| `Email_to_Quote_Underwriting_Agent_files.json` | No-mailbox version: paste the broker email in the chat and upload the PDFs on the File node. |
| `underwriting_prompt.md` | The Prompt Template text (data model, validation rules, decision rules, rating table, email draft). Edit and rebuild to change the underwriting logic. |
| `build_llm_only_agent_json.py` | Rebuilds both JSON files from the running backend's component catalogue. |
| `samples/case_clean/`, `samples/case_conflicting/` | Synthetic broker submissions (email text + four PDFs). The conflicting case has 250 vs 248 employees, three wrong dates of birth, claims ₹42 lakh vs ₹45 lakh and a missing policy expiry. |
| `generate_sample_documents.py` | Regenerates the sample PDFs. |
| `advanced_custom_components/` | Earlier variant with deterministic custom components (not needed for the demo). |

All company names, people and amounts are fictional.

## Live demo with the Outlook connector

Prerequisites: an Outlook connector with a linked mailbox (Connectors page →
Outlook → Link Mailbox) and a model registered in the Model Registry.

1. Import `Email_to_Quote_Underwriting_Agent.json`.
2. On the **Outlook Mail** node click the refresh icon next to *Outlook
   Connector* and select your connector. *Max Results* is 1 (newest email);
   set *Filter by Subject* or *Filter by Sender* if the inbox also receives
   other mail. The advanced *Max Attachment Characters* is set to 60,000 so
   whole PDFs (including the census table) reach the LLM.
3. On the **Large Language Model** node select the provider and model.
4. From another mailbox, send the broker email with the four PDFs from a sample
   folder to the linked address.
5. Open the Playground and send any message (the default text is fine). The
   agent reads the email, and the model returns the six-section review:
   extracted data model, field-level validation table, decision, rating,
   broker email draft, audit trail.

Run `case_clean` and `case_conflicting` one after the other to show a
quotation versus a clarification request.

## Demo without a mailbox

Import `Email_to_Quote_Underwriting_Agent_files.json`, upload the four PDFs of
a sample case on the **File** node, select the model, then paste the text of
`samples/<case>/email.txt` into the Playground and send.

## Notes

- Sending the reply to the broker is a manual step in this version: copy the
  drafted email from the response, or add the **Outlook Mail** node's
  *Send Reply* output to the flow once the approval step is agreed.
- The rating table lives in `underwriting_prompt.md`; the LLM applies it and
  shows the arithmetic. Replace it with the insurer's approved table or a rating
  API when moving beyond the demo.
- The Outlook Mail component gained an advanced *Max Attachment Characters*
  setting (default 3,000, unchanged behaviour) so long attachments are not cut.
