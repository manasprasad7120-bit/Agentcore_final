# Email-to-Quote Underwriting Review

Operator instruction (may be empty): {instruction}

## Inbound submission: broker email and the extracted text of every attachment
{email}
{documents}

## Your tasks
Work strictly from the text above. For every value you report, name the source document it came from.

### 1. Extract and normalise the data model
Fill each field (write "not found" when absent): company name; industry; broker name and email; policy type; coverage start date; total employees stated in the company application; number of employee rows in the census (count the rows yourself) and the census-declared total; total dependants; requested sum insured per employee; current insurer; policy number; policy start date; policy expiry date; current annual premium; total incurred claims in the summary; total of the detailed claim rows (add them yourself).

### 2. Field-level validation
Produce a table with the columns: Field | Source value(s) | Result (PASS / FAIL / WARN) | Issue type (missing field / missing document / invalid format / data discrepancy / extraction error) | Evidence (document and quoted text).
Checks to perform:
- all four documents are present: company application, employee census, claims experience, current policy;
- mandatory fields present: company name, total employees, requested sum insured, coverage start date, policy expiry date, claims totals, current annual premium;
- dates are in YYYY-MM-DD format and e-mail addresses are valid;
- application head-count versus census row count versus census-declared total (any difference is a material discrepancy);
- for every census row the stated age must match the date of birth as of the census date (list each inconsistent employee with ID, DOB, stated age and computed age; three or more is material);
- claims summary total versus detailed claims total (a difference above 2 percent is a material discrepancy);
- requested sum insured between 1,00,000 and 50,00,000 (outside is a WARN).
Finish with a completeness score (fields found / fields expected, as a percentage) and a validation score (checks passed / checks evaluated, as a percentage).

### 3. Underwriting decision
Choose exactly one: PROCEED_TO_QUOTE, REQUEST_CLARIFICATION, REFER_TO_UNDERWRITER.
- Any material discrepancy, missing mandatory field or missing document: REQUEST_CLARIFICATION and the case goes on hold.
- Otherwise, if the loss ratio (detailed claims total divided by current annual premium) is above 1.00, or there are more than 1,000 employees, or the requested sum insured is above 10,00,000: REFER_TO_UNDERWRITER.
- Otherwise: PROCEED_TO_QUOTE.
Give the reasons and the risk tier: loss ratio below 0.60 is LOW, 0.60 to 0.85 is MEDIUM, above 0.85 is HIGH.

### 4. Rating (only when the decision is PROCEED_TO_QUOTE; otherwise write "Rating not performed" and the reason)
Apply this insurer rating table exactly and show the arithmetic. Do not use any other rates.
- Base sum insured 5,00,000. Sum-insured factor = requested sum insured divided by 5,00,000.
- Annual rate per employee by age band: 18 to 29 = 4,000; 30 to 39 = 5,400; 40 to 49 = 7,600; 50 and above = 10,500. Multiply each rate by the sum-insured factor. Group the census rows by age band and add up the rates.
- Dependant loading = total dependants multiplied by 15 percent of the average employee rate.
- Claims experience adjustment applied to the subtotal: loss ratio below 0.60 = minus 5 percent; 0.60 to 0.85 = no change; above 0.85 up to 1.00 = plus 15 percent; above 1.00 = plus 30 percent.
- Minimum premium 2,500 per employee. GST at 18 percent is shown separately. The quotation is valid for 30 days.
Present: covered employees, dependants, sum insured per employee, age-band breakdown (employees, rate, premium per band), employee base premium, dependant loading, claims adjustment, annual premium excluding GST, GST, total payable, premium per employee.

### 5. Broker email draft
Write the reply e-mail that matches the decision: a quotation with the premium summary and terms, or a clarification request that lists each discrepancy and the exact information needed, or a referral notice. Address it to the broker and sign it "Insurance Underwriting Team". State that the quotation is subject to the insurer's underwriting guidelines and authorised approval.

### 6. Audit trail
List the processing steps taken and the documents used for each.

Format the whole answer in Markdown with these six headed sections. Express amounts in INR with Indian digit grouping (for example 18,00,000).
