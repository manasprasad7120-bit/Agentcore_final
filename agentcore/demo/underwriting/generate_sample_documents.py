"""Generate the synthetic broker submissions used by the Email-to-Quote Underwriting Agent demo.

Creates two cases under ./samples:
  case_clean        - consistent documents -> the agent proceeds to rating and quotation
  case_conflicting  - 248 vs 250 employees, 3 inconsistent dates of birth, claims summary
                      42 lakh vs detailed 45 lakh, missing policy expiry -> clarification email

All company names, people and figures are fictional. Run from anywhere:
    python demo/underwriting/generate_sample_documents.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent / "samples"
CENSUS_DATE = date(2026, 10, 1)
CITIES = ["Bengaluru", "Pune", "Chennai", "Hyderabad", "Gurugram", "Noida"]
FIRST = ["Aarav", "Vivaan", "Aditya", "Diya", "Ananya", "Ishaan", "Kavya", "Rohan", "Sneha", "Arjun", "Meera", "Karan", "Priya", "Nikhil", "Riya"]
LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Nair", "Gupta", "Singh", "Kulkarni", "Das", "Menon", "Bose", "Verma"]
CLAIM_TYPES = ["Hospitalisation", "Day-care procedure", "Maternity", "Accident", "Pre/post hospitalisation"]


class Doc:
    def __init__(self, path: Path, title: str):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.w, self.h = A4
        self.title = title
        self.page = 1
        self.y = 0
        self._header()

    def _header(self):
        self.c.setFont("Helvetica-Bold", 14)
        self.c.drawString(20 * mm, self.h - 20 * mm, self.title)
        self.c.setFont("Helvetica", 8)
        self.c.drawRightString(self.w - 20 * mm, self.h - 20 * mm, f"Page {self.page}")
        self.y = self.h - 32 * mm

    def line(self, text: str, size: int = 10, bold: bool = False):
        if self.y < 20 * mm:
            self.c.showPage()
            self.page += 1
            self._header()
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(20 * mm, self.y, text)
        self.y -= 5.5 * mm

    def blank(self):
        self.y -= 4 * mm

    def save(self):
        self.c.showPage()
        self.c.save()


def inr(n: int) -> str:
    s = str(n)
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "INR " + (",".join(parts) + "," if parts else "") + tail


def build_census(rows: int, inconsistent: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    out = []
    for i in range(1, rows + 1):
        band = rnd.choices([(22, 29), (30, 39), (40, 49), (50, 58)], weights=[30, 40, 20, 10])[0]
        age = rnd.randint(*band)
        dob = CENSUS_DATE.replace(year=CENSUS_DATE.year - age) - timedelta(days=rnd.randint(0, 364))
        # recompute exact age on census date
        exact = CENSUS_DATE.year - dob.year - ((CENSUS_DATE.month, CENSUS_DATE.day) < (dob.month, dob.day))
        out.append({
            "id": f"EMP{i:04d}", "name": f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", "dob": dob.isoformat(),
            "age": exact, "city": rnd.choice(CITIES), "dependants": rnd.choices([0, 1, 2, 3], weights=[25, 30, 35, 10])[0],
        })
    for row in rnd.sample(out, inconsistent):  # deliberately wrong stated ages
        row["age"] += rnd.choice([-7, -5, 6, 8])
    return out


def build_claims(total: int, count: int, employees: list[dict], seed: int) -> list[dict]:
    rnd = random.Random(seed)
    weights = [rnd.uniform(0.5, 2.0) for _ in range(count)]
    scale = total / sum(weights)
    amounts = [int(round(w * scale / 1000)) * 1000 for w in weights]
    amounts[-1] += total - sum(amounts)
    start = date(2025, 10, 1)
    return [{
        "id": f"CLM-{i + 1:03d}", "date": (start + timedelta(days=rnd.randint(0, 360))).isoformat(),
        "emp": rnd.choice(employees)["id"], "type": rnd.choice(CLAIM_TYPES), "amount": amt,
    } for i, amt in enumerate(amounts)]


def write_case(folder: Path, *, census_rows: int, inconsistent_dob: int, claims_summary: int, claims_detailed: int,
               policy_expiry: str | None, seed: int):
    folder.mkdir(parents=True, exist_ok=True)
    employees = build_census(census_rows, inconsistent_dob, seed)
    claims = build_claims(claims_detailed, 18, employees, seed + 1)

    (folder / "email.txt").write_text(
        "From: broker@corporate-insurance-brokers.example\n"
        "To: underwriting@demo-general-insurance.example\n"
        "Subject: Group Medical Insurance — Renewal Quote Request — ABC Technologies\n\n"
        "Dear Underwriting Team,\n\n"
        "Please find attached the employee census, current policy details, claims experience report and company "
        "information for our client's group medical insurance renewal.\n\n"
        "Kindly review the information and share your proposed premium quotation and coverage terms.\n\n"
        "Regards,\nCorporate Insurance Broker\n",
        encoding="utf-8",
    )

    d = Doc(folder / "01_Employee_Census.pdf", "ABC Technologies Pvt. Ltd. — Employee Census")
    d.line(f"Census Date: {CENSUS_DATE.isoformat()}")
    d.line(f"Prepared by: Corporate Insurance Broker    Client: ABC Technologies Pvt. Ltd.")
    d.blank()
    d.line("Employee ID | Name | Date of Birth | Age | Location | Dependants", bold=True)
    for e in employees:
        d.line(f"{e['id']} | {e['name']} | DOB {e['dob']} | Age {e['age']} | {e['city']} | Dependants {e['dependants']}", 9)
    d.blank()
    d.line(f"Total Employees in Census: {len(employees)}", bold=True)
    d.line(f"Total Dependants: {sum(e['dependants'] for e in employees)}")
    d.save()

    d = Doc(folder / "02_Claims_Experience.pdf", "ABC Technologies Pvt. Ltd. — Claims Experience Report")
    d.line("Policy Period: 2025-10-01 to 2026-09-30")
    d.line(f"Total Incurred Claims (Summary): {inr(claims_summary)}", bold=True)
    d.line(f"Number of Claims: {len(claims)}")
    d.blank()
    d.line("Claim ID | Date | Employee | Type | Incurred Amount", bold=True)
    for cl in claims:
        d.line(f"{cl['id']} | {cl['date']} | {cl['emp']} | {cl['type']} | {inr(cl['amount'])}", 9)
    d.blank()
    d.line(f"Total of Detailed Claims: {inr(claims_detailed)}", bold=True)
    d.save()

    d = Doc(folder / "03_Current_Policy.pdf", "Current Group Medical Policy — Schedule")
    d.line("Insurer: Prior Health Assurance Co. (fictional)")
    d.line("Policy Number: GMC-2025-778341")
    d.line("Policyholder: ABC Technologies Pvt. Ltd.")
    d.line("Policy Start Date: 2025-10-01")
    if policy_expiry:
        d.line(f"Policy Expiry Date: {policy_expiry}")
    d.line("Sum Insured per Employee: INR 5,00,000")
    d.line("Annual Premium (Current): INR 56,00,000")
    d.blank()
    d.line("Benefits:", bold=True)
    for b in ("Family floater covering employee, spouse and up to 2 children", "Room rent up to 2% of sum insured per day",
              "Maternity cover INR 50,000 (normal) / INR 75,000 (caesarean)", "Pre-existing diseases covered from day one",
              "Pre-hospitalisation 30 days and post-hospitalisation 60 days"):
        d.line(f"- {b}", 9)
    d.blank()
    d.line("Exclusions:", bold=True)
    for x in ("Cosmetic and aesthetic treatment", "Self-inflicted injuries", "Treatment outside India"):
        d.line(f"- {x}", 9)
    d.save()

    d = Doc(folder / "04_Company_Application.pdf", "Group Medical Insurance — Company Application Form")
    d.line("Company Name: ABC Technologies Pvt. Ltd.")
    d.line("Industry: Information Technology Services")
    d.line("Registered Address: 14 Outer Ring Road, Bengaluru 560103, Karnataka")
    d.line("Total Employees: 250")
    d.line("Requested Sum Insured per Employee: INR 5,00,000")
    d.line("Policy Type: Group Medical Insurance (Renewal)")
    d.line("Coverage Start Date: 2026-10-01")
    d.line("Broker: Corporate Insurance Broker")
    d.line("Contact Email: broker@corporate-insurance-brokers.example")
    d.blank()
    d.line("Requested Coverage:", bold=True)
    for r in ("Family floater for employee + spouse + 2 children", "Maternity benefit and new-born cover",
              "Corporate buffer INR 10,00,000", "Cashless network across India"):
        d.line(f"- {r}", 9)
    d.blank()
    d.line("Declaration: The information provided is true to the best of our knowledge. (Fictional demo data.)", 8)
    d.save()


if __name__ == "__main__":
    write_case(ROOT / "case_clean", census_rows=250, inconsistent_dob=0, claims_summary=4200000, claims_detailed=4200000,
               policy_expiry="2026-09-30", seed=7)
    write_case(ROOT / "case_conflicting", census_rows=248, inconsistent_dob=3, claims_summary=4200000, claims_detailed=4500000,
               policy_expiry=None, seed=11)
    print(f"Sample cases written to {ROOT}")
