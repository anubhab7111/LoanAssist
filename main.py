# backend/main.py
from fastapi import FastAPI, Body, HTTPException,Query
from fastapi.responses import JSONResponse, FileResponse
import pandas as pd
import os
import datetime
from pydantic import BaseModel
import re
import json
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
import traceback
from typing import Optional
from difflib import get_close_matches

app = FastAPI()

# --- enable CORS for demo (paste after app = FastAPI()) ---
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change to your domain in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- simple frontend event logger (paste with other endpoints) ---
from fastapi import Body

@app.post("/log_event")
def log_event(evt: dict = Body(...)):
    """
    Expected evt = {
      "event": "marketing_prefill_click",
      "prefill": "...",
      "utm_source": "...",
      "utm_medium": "...",
      "utm_campaign": "...",
      "ts": "..."
    }
    Appends to audit_log (or create a small events file).
    """
    try:
        # use audit_log helper to store events consistently
        audit_log({
            "ts": evt.get("ts") or datetime.datetime.utcnow().isoformat(),
            "customer_id": evt.get("customer_id") or "UNKNOWN",
            "action": evt.get("event", "frontend_event"),
            "data": json.dumps({k: v for k, v in evt.items() if k not in ("ts", "customer_id")})
        })
    except Exception:
        # swallow errors (don't crash)
        pass
    return {"status": "ok"}


# --- paths (repo structure: backend/ and data/ at repo root) ---
DATA_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "applicants.csv")
AUDIT_FILE = os.path.join(os.path.dirname(__file__), "audit_log.csv")
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")

os.makedirs(PDF_DIR, exist_ok=True)

# --- helper functions ---
def load_applicants_df():
    """Load applicants CSV. Returns empty DataFrame if file missing."""
    if not os.path.exists(DATA_CSV):
        return pd.DataFrame()
    return pd.read_csv(DATA_CSV, dtype=str)

def audit_log(entry: dict):
    """Append one audit row (ts, customer_id, action, data) to AUDIT_FILE."""
    header = ["ts", "customer_id", "action", "data"]
    exists = os.path.exists(AUDIT_FILE)
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        if not exists:
            f.write(",".join(header) + "\n")
        data_field = '"' + str(entry.get("data", "")).replace('"', '""') + '"'
        line = ",".join([
            str(entry.get("ts", "")),
            str(entry.get("customer_id", "")),
            str(entry.get("action", "")),
            data_field
        ])
        f.write(line + "\n")

class NLPPayload(BaseModel):
    customer_id: str | None = None
    loan_amount: float | None = None
    tenure_months: int | None = None
    existing_monthly_debt: float | None = 0.0
    income_monthly: float | None = None

# ------------------------
# Local/simple NLP parser
# ------------------------
def parse_number_with_units(text: str) -> float | None:
    if not text:
        return None
    # try to find numeric token
    t = text.lower().replace(" ", "")
    # remove commas for parsing
    no_commas = text.replace(",", "")
    m = re.search(r"([0-9]+(?:\.\d+)?)", no_commas)
    if not m:
        return None
    raw = m.group(1)
    try:
        val = float(raw)
    except:
        return None

    idx = no_commas.find(raw)
    tail = no_commas[idx + len(raw): idx + len(raw) + 8].lower()
    head = no_commas[max(0, idx - 8): idx].lower()

    if "lakh" in tail or "lakh" in head or "lac" in tail or "lacs" in tail or "lac" in head:
        return val * 100000.0
    if tail.startswith("k") or head.endswith("k") or "thousand" in tail or "thousand" in head:
        return val * 1000.0
    return val

def parse_tenure_months(text: str) -> int | None:
    if not text:
        return None
    text = text.lower()
    m_months = re.search(r"(\d+)\s*(months|month|mos|m\b)", text)
    if m_months:
        return int(m_months.group(1))
    m_years = re.search(r"(\d+(\.\d+)?)\s*(years|year|yrs|yr|y\b)", text)
    if m_years:
        try:
            years = float(m_years.group(1))
            return int(round(years * 12))
        except:
            return None
    m_num = re.search(r"\b(\d{1,3})\b", text)
    if m_num:
        return int(m_num.group(1))
    return None

def extract_fields_from_text_local(user_text: str) -> dict:
    text = (user_text or "").strip()
    result = {
        "customer_id": None,
        "loan_amount": None,
        "tenure_months": None,
        "existing_monthly_debt": 0.0,
        "income_monthly": None
    }

    m_id = re.search(r"(customer[_\s]?id|id)[:\s]*([A-Za-z0-9\-_]+)", text, flags=re.IGNORECASE)
    if m_id:
        result["customer_id"] = m_id.group(2)

    loan_ctx = None
    m_loan = re.search(r"(?:loan|want|need|applyfor|applyfora)\s*[^\d]{0,3}([0-9][\d,\.]*\s*(?:lakh|lacs|lac|k|thousand|)?)", text, flags=re.IGNORECASE)
    if m_loan:
        loan_ctx = m_loan.group(1)
    else:
        m_loan2 = re.search(r"([0-9][\d,\.]*)\s*(lakh|lac|lacs|k|thousand)?\s*(?:loan)", text, flags=re.IGNORECASE)
        if m_loan2:
            loan_ctx = (m_loan2.group(1) or "") + (m_loan2.group(2) or "")
    if loan_ctx:
        parsed = parse_number_with_units(loan_ctx)
        if parsed is not None:
            result["loan_amount"] = parsed

    if result["loan_amount"] is None:
        m_any = re.search(r"([0-9][\d,\.]*(?:\s*(?:lakh|lac|lacs|k|thousand))?)", text, flags=re.IGNORECASE)
        if m_any:
            maybe = parse_number_with_units(m_any.group(1))
            if maybe is not None and maybe >= 1000:
                result["loan_amount"] = maybe

    t = parse_tenure_months(text)
    if t is not None:
        result["tenure_months"] = t

    m_income = re.search(r"(salary|income|earn)\s*(?:is|:|=)?\s*([0-9][\d,\.]*\s*(?:lakh|lac|lacs|k|thousand)?)", text, flags=re.IGNORECASE)
    if m_income:
        parsed = parse_number_with_units(m_income.group(2))
        if parsed is not None:
            result["income_monthly"] = parsed
    else:
        m_inc2 = re.search(r"([0-9][\d,\.]*\s*(?:lakh|lac|lacs|k|thousand)?)\s*(?:/month|permonth|per month|monthly)", text, flags=re.IGNORECASE)
        if m_inc2:
            parsed = parse_number_with_units(m_inc2.group(1))
            if parsed is not None:
                result["income_monthly"] = parsed

    m_debt = re.search(r"(existing|current)?\s*(debt|emi|payment|payments)\s*(?:is|:|=)?\s*([0-9][\d,\.]*\s*(?:lakh|lac|lacs|k|thousand)?)", text, flags=re.IGNORECASE)
    if m_debt:
        parsed = parse_number_with_units(m_debt.group(3))
        if parsed is not None:
            result["existing_monthly_debt"] = parsed

    # normalization
    try:
        if result["loan_amount"] is not None:
            result["loan_amount"] = float(result["loan_amount"])
    except:
        result["loan_amount"] = None
    try:
        if result["income_monthly"] is not None:
            result["income_monthly"] = float(result["income_monthly"])
    except:
        result["income_monthly"] = None
    try:
        if result["existing_monthly_debt"] is not None:
            result["existing_monthly_debt"] = float(result["existing_monthly_debt"])
    except:
        result["existing_monthly_debt"] = 0.0
    try:
        if result["tenure_months"] is not None:
            result["tenure_months"] = int(result["tenure_months"])
    except:
        result["tenure_months"] = None

    return result

# --- basic endpoints ---
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db")
def db_list():
    df = load_applicants_df()
    if df.empty:
        return {"error": "applicants CSV not found"}
    ids = df["id"].tolist() if "id" in df.columns else df.iloc[:, 0].tolist()
    return {"count": len(ids), "ids": ids}

@app.get("/crm/{customer_id}")
def get_crm(customer_id: str):
    df = load_applicants_df()
    if df.empty:
        return JSONResponse(status_code=500, content={"error": "applicants CSV not found"})
    row = df[(df.get("crm_customer_id", pd.Series(dtype=str)) == customer_id) |
             (df.get("id", pd.Series(dtype=str)) == customer_id)]
    if row.empty:
        return JSONResponse(status_code=404, content={"error": "customer not found"})
    rec = row.iloc[0].to_dict()
    return {
        "customer_id": rec.get("crm_customer_id") or rec.get("id"),
        "name": rec.get("name"),
        "phone": rec.get("phone"),
        "email": rec.get("email"),
        "income_monthly": rec.get("income_monthly"),
        "pre_approved_limit": rec.get("pre_approved_limit", "")
    }

@app.post("/crm/update")
def update_crm(update: dict = Body(...)):
    """
    update = {"customer_id": "CUST_001", "phone": "9876543210", "name": "Manish Patra"}
    Updates data/applicants.csv in-place (simple). Requires server to have write access.
    """
    cid = update.get("customer_id")
    if not cid:
        return JSONResponse(status_code=400, content={"error":"customer_id required"})

    df = load_applicants_df()
    if df.empty:
        return JSONResponse(status_code=500, content={"error":"applicants CSV not found"})

    # find row by crm_customer_id or id
    mask = (df.get("crm_customer_id", pd.Series(dtype=str)) == cid) | (df.get("id", pd.Series(dtype=str)) == cid)
    if not mask.any():
        return JSONResponse(status_code=404, content={"error":"customer not found"})

    idx = df[mask].index[0]
    # update allowed columns (skip customer_id)
    for k, v in update.items():
        if k in ("customer_id", "crm_customer_id"):
            continue
        # create column if missing
        if k not in df.columns:
            df[k] = ""
        df.at[idx, k] = v

    # save back
    try:
        df.to_csv(DATA_CSV, index=False)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error":"failed to save CSV", "detail": str(e)})

    return {"status":"ok", "updated": update}

@app.get("/credit/{customer_id}")
def get_credit(customer_id: str):
    df = load_applicants_df()
    if df.empty:
        return JSONResponse(status_code=500, content={"error": "applicants CSV not found"})
    row = df[(df.get("crm_customer_id", pd.Series(dtype=str)) == customer_id) |
             (df.get("id", pd.Series(dtype=str)) == customer_id)]
    if row.empty:
        return JSONResponse(status_code=404, content={"error": "customer not found"})
    rec = row.iloc[0].to_dict()
    credit = rec.get("credit_score")
    if not credit or str(credit).strip() == "":
        try:
            inc = float(rec.get("income_monthly") or 30000)
            credit = int(min(900, max(300, (inc / 1000) * 40)))
        except:
            credit = 650
    return {"customer_id": rec.get("crm_customer_id") or rec.get("id"), "credit_score": int(float(credit))}

@app.get("/status/{customer_id}")
def get_status(customer_id: str):
    if not os.path.exists(AUDIT_FILE):
        return {"error": "no audit file yet"}
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    header, rows = lines[0], lines[1:]
    for line in reversed(rows):
        parts = line.strip().split(",")
        if len(parts) >= 3 and parts[1] == customer_id:
            return {
                "customer_id": customer_id,
                "ts": parts[0],
                "action": parts[2],
                "data": parts[3] if len(parts) > 3 else ""
            }
    return {"customer_id": customer_id, "status": "no record found"}

# ------------------------
# PDF generation
# ------------------------
def generate_sanction_pdf(decision_result: dict) -> str:
    """
    Generates a PDF sanction letter and returns the filename (not full path).
    Stores in backend/pdfs/.
    This version is defensive and raises RuntimeError with details on failure.
    """
    try:
        # ensure we have a dict
        if not isinstance(decision_result, dict):
            raise RuntimeError("generate_sanction_pdf expected dict, got: " + str(type(decision_result)))

        cust_id = str(decision_result.get("customer_id") or (decision_result.get("crm") or {}).get("customer_id") or "UNKNOWN")
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"sanction_{cust_id}_{ts}.pdf"
        filepath = os.path.join(PDF_DIR, filename)

        # safety: ensure pdf dir exists and is writable
        os.makedirs(PDF_DIR, exist_ok=True)
        if not os.access(PDF_DIR, os.W_OK):
            raise RuntimeError(f"PDF_DIR not writable: {PDF_DIR}")

        # PDF layout using reportlab
        c = canvas.Canvas(filepath, pagesize=A4)
        width, height = A4
        margin = 20 * mm
        x = margin
        y = height - margin

        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, y, "Sanction Letter")
        y -= 12 * mm

        c.setFont("Helvetica", 10)
        c.drawString(x, y, f"Issue Date (UTC): {datetime.datetime.utcnow().isoformat()}")
        y -= 8 * mm

        crm = decision_result.get("crm") if isinstance(decision_result.get("crm"), dict) else {}
        name = crm.get("name") or ""
        phone = crm.get("phone") or ""
        email = crm.get("email") or ""

        lines = [
            f"Customer ID: {cust_id}",
            f"Name: {name}",
            f"Phone: {phone}",
            f"Email: {email}",
            "",
            "Loan Details:",
            f"  - Loan Amount: {decision_result.get('loan_request', {}).get('loan_amount')}",
            f"  - Tenure (months): {decision_result.get('loan_request', {}).get('tenure_months')}",
            f"  - EMI: {decision_result.get('emi')}",
            f"  - Decision: {decision_result.get('decision')}",
            "",
            "Notes:",
        ]
        reasons = decision_result.get("reasons") or []
        if isinstance(reasons, list):
            for r in reasons:
                lines.append(f"  - {r}")
        else:
            lines.append(f"  - {str(reasons)}")

        # Draw lines
        c.setFont("Helvetica", 11)
        for ln in lines:
            if y < margin + 40:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica", 11)
            # ensure line is a str
            c.drawString(x, y, str(ln))
            y -= 7 * mm

        # Signature block
        if y < margin + 40:
            c.showPage()
            y = height - margin
        y -= 10 * mm
        c.drawString(x, y, "Authorized Signatory")
        y -= 5 * mm
        c.drawString(x, y, "________________________")

        c.showPage()
        c.save()

        return filename

    except Exception as e:
        # include traceback for dev debugging
        tb = traceback.format_exc()
        # write to audit (so we can inspect later)
        try:
            audit_log({
                "ts": datetime.datetime.utcnow().isoformat(),
                "customer_id": (decision_result.get("customer_id") if isinstance(decision_result, dict) else "UNKNOWN"),
                "action": "pdf_generation_error",
                "data": f"{str(e)} | TRACE: {tb[:2000]}"
            })
        except:
            pass
        # raise a clear RuntimeError so caller can return formatted error
        raise RuntimeError(f"PDF generation failed: {str(e)}\nTRACE:\n{tb}")


@app.get("/pdf/{filename}")
def serve_pdf(filename: str):
    """
    Serve a generated PDF by filename. filename must exactly match file in backend/pdfs/.
    """
    safe_name = os.path.basename(filename)  # prevent path traversal
    fullpath = os.path.join(PDF_DIR, safe_name)
    if not os.path.exists(fullpath):
        return JSONResponse(status_code=404, content={"error": "file not found"})
    return FileResponse(fullpath, media_type="application/pdf", filename=safe_name)

# ------------------------
# Simple KYC check (local)
# ------------------------
def kyc_check(customer_id: str) -> dict:
    """
    Lightweight KYC: checks presence of name, phone format, and simple PAN/Aadhaar patterns.
    Returns dict: {"status": "PASS"/"FAIL", "missing": [...], "issues": [...]}
    """
    res = {"status": "PASS", "missing": [], "issues": []}
    crm_resp = get_crm(customer_id)
    if isinstance(crm_resp, JSONResponse):
        res["status"] = "FAIL"
        res["issues"].append("CRM record not found")
        return res
    crm = crm_resp if isinstance(crm_resp, dict) else dict(crm_resp)

    name = crm.get("name") or ""
    phone = crm.get("phone") or ""
    pan = crm.get("pan") or crm.get("PAN") or ""
    aadhaar = crm.get("aadhaar") or crm.get("Aadhaar") or ""

    if not name.strip():
        res["missing"].append("name")
    # phone: simple 10-digit check
    if phone:
        phone_digits = re.sub(r"\D", "", str(phone))
        if len(phone_digits) != 10:
            res["issues"].append("phone format invalid")
    else:
        res["missing"].append("phone")

    # PAN simple regex (5 letters, 4 digits, 1 letter) - optional
    if pan:
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan, flags=re.IGNORECASE):
            res["issues"].append("pan format suspicious")
    # Aadhaar: 12 digits
    if aadhaar:
        if not re.match(r"^\d{12}$", aadhaar):
            res["issues"].append("aadhaar format suspicious")

    if res["missing"] or res["issues"]:
        res["status"] = "FAIL"
    return res

# ------------------------
# /apply endpoint (same logic as before)
# ------------------------
@app.post("/apply")
def apply(payload: dict = Body(...)):
    """
    Defensive /apply: validates inputs and handles missing/invalid CSV fields without raising.
    """
    # 1) get id
    customer_id = payload.get("customer_id") or payload.get("applicant_id") or payload.get("id")
    if not customer_id:
        return JSONResponse(status_code=400, content={"error": "missing customer_id/applicant_id/id in payload"})

    # 2) parse numeric inputs safely
    try:
        loan_amount = float(payload.get("loan_amount", 0) or 0)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid loan_amount; must be numeric"})
    try:
        tenure_months = int(payload.get("tenure_months", 0) or 0)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid tenure_months; must be integer"})
    try:
        existing_monthly_debt = float(payload.get("existing_monthly_debt", 0) or 0)
    except Exception:
        existing_monthly_debt = 0.0

    if loan_amount <= 0 or tenure_months <= 0:
        return JSONResponse(status_code=400, content={"error": "loan_amount and tenure_months must be > 0"})

    # 3) fetch crm and credit (these functions may return JSONResponse on error)
    crm_resp = get_crm(customer_id)
    if isinstance(crm_resp, JSONResponse):
        # pass-through CRM errors (404 or 500)
        return crm_resp

    credit_resp = get_credit(customer_id)
    if isinstance(credit_resp, JSONResponse):
        return credit_resp

    # 4) normalize crm and credit into dicts (defensive)
    if not isinstance(crm_resp, dict):
        try:
            crm = dict(crm_resp)
        except Exception:
            return JSONResponse(status_code=500, content={"error": "unexpected crm response type"})
    else:
        crm = crm_resp

    if not isinstance(credit_resp, dict):
        try:
            credit = dict(credit_resp)
        except Exception:
            return JSONResponse(status_code=500, content={"error": "unexpected credit response type"})
    else:
        credit = credit_resp

    # 5) parse numeric fields from CRM/credit safely
    def safe_float(x, default=0.0):
        try:
            if x is None or str(x).strip() == "":
                return default
            return float(str(x).replace(",", "").strip())
        except:
            return default

    def safe_int(x, default=0):
        try:
            if x is None or str(x).strip() == "":
                return default
            return int(float(str(x).replace(",", "").strip()))
        except:
            return default

    income_monthly = safe_float(crm.get("income_monthly") or crm.get("income") or 0, 0.0)
    credit_score = safe_int(credit.get("credit_score") or credit.get("score") or credit.get("credit") or 0, 0)

    # 6) EMI calculation (avoid division by zero)
    ANNUAL_RATE = 0.12
    r = ANNUAL_RATE / 12.0 #Monthly_rate
    n = tenure_months
    P = loan_amount
    try:
        if r == 0:
            emi = round(P / n, 2)
        else:
            numerator = P * r * (1 + r) ** n
            denominator = (1 + r) ** n - 1
            emi = round(numerator / denominator, 2)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"emi calculation failed: {str(e)}"})

    # 7) DTI (safe)
    if income_monthly <= 0:
        dti = None
    else:
        dti = round((existing_monthly_debt + emi) / income_monthly, 3)

    # 8) underwriting decision (same rules)
    reasons = []
    decision = "REJECT"
    if credit_score >= 700 and (dti is not None and dti <= 0.50):
        decision = "APPROVE"
        reasons.append("Good credit score and acceptable DTI")
    elif (credit_score >= 650 and (dti is not None and dti <= 0.65)) or (credit_score >= 600 and (dti is not None and dti <= 0.60)):
        decision = "REFER"
        if credit_score < 700:
            reasons.append("Credit score below ideal threshold")
        if dti is not None and dti > 0.50:
            reasons.append("DTI slightly high — manual review")
    else:
        decision = "REJECT"
        if credit_score < 600:
            reasons.append("Low credit score")
        if dti is None:
            reasons.append("Missing or zero income")
        elif dti > 0.65:
            reasons.append("High DTI")
    if not reasons:
        reasons.append("No specific reasons (default)")

    # 9) audit (best effort; ignore errors)
    try:
        audit_log({
            "ts": datetime.datetime.utcnow().isoformat(),
            "customer_id": customer_id,
            "action": f"apply_{decision.lower()}",
            "data": f"credit:{credit_score};emi:{emi};dti:{dti}"
        })
    except:
        pass

    # 10) return result
    return {
        "customer_id": customer_id,
        "crm": crm,
        "credit": credit,
        "loan_request": {"loan_amount": loan_amount, "tenure_months": tenure_months, "existing_monthly_debt": existing_monthly_debt},
        "emi": emi,
        "dti": dti,
        "credit_score": credit_score,
        "decision": decision,
        "reasons": reasons
    }

# ------------------------
# nlp_apply (local parser)
# ------------------------
# nlp_apply: detect simple intent, extract amount & purpose, compute EMI, and return quick replies
class NLPApplyReq(BaseModel):
    msg: str
    cust_id: Optional[str] = None

@app.post("/nlp_apply")
# >>> CHANGED / ADDED: updated nlp_apply to return EMI options for multiple tenures

async def nlp_apply(body: dict = Body(...)):
    """
    Expects body to contain:
      - message (str)
      - cust_id (optional str)
    Returns JSON with keys:
      - reply (str)
      - quick_replies (list)
      - decision (dict)
      - emi_options (list of {tenure_months, emi})
    """
    # read inputs (support both pydantic model or raw dict)
    try:
        msg = body.get("message") if isinstance(body, dict) else getattr(body, "message", "") or ""
        cust_id = body.get("cust_id") if isinstance(body, dict) else getattr(body, "cust_id", None)
    except Exception:
        # defensive fallback
        msg = ""
        cust_id = None

    msg = (msg or "").strip()
    quick_replies = ["Check pre-approval", "Show EMI options", "Ask another question"]
    decision_result = {}

    # small helper to compute EMI options (keeps this function self-contained)
    def emi_options_for_amount(principal: float, annual_rate: float):
        tenures = [12, 24, 36, 48, 60]
        opts = []
        for n in tenures:
            try:
                e = int(round(emi_calc(principal, annual_rate, n)))
            except Exception:
                # fallback if emi_calc isn't available/valid
                r = annual_rate / 12 / 100
                if r == 0:
                    e = int(round(principal / n))
                else:
                    e = int(round(principal * r * (1 + r) ** n / ((1 + r) ** n - 1)))
            opts.append({"tenure_months": n, "emi": e})
        return opts

    # Try to load CRM if cust_id provided (non-blocking)
    crm = None
    try:
        if cust_id:
            # get_crm should be in your file; keep call but don't crash if absent
            try:
                crm = get_crm(cust_id)
            except Exception:
                crm = None
    except Exception:
        crm = None

    # Simple hesitation recovery (keeps UX friendly)
    if any(w in (msg or "").lower() for w in ["too high", "too expensive", "expensive", "can't afford", "cant afford", "costly"]):
        friendly = "No worries — we can try a longer tenure or a lower amount to reduce EMI. Want me to show options?"
        return {"reply": friendly, "quick_replies": ["Show lower EMI", "Show longer tenure options", "Keep same plan"]}

        # --- improved amount parsing (supports 'lakh', 'k', commas, ₹ symbol etc.) ---
        # --- Robust amount + tenure parsing (replace older token-based parser) ---
        # --- FINAL robust amount + tenure parsing ---
    import re

    amount = None
    tenure_months = None
    purpose = None

    s = (msg or "").strip()
    s_lower = s.lower()
    s_clean = s_lower.replace('₹', ' ').replace(',', ' ')
    s_clean = re.sub(r'\s+', ' ', s_clean).strip()

    # Pattern 1: "4 lakh", "4 lakhs", "4lakh", "4lakhs"
    match = re.search(r'(\d+(?:\.\d+)?)\s*(lakh|lakhs|lac|lacs|l)\b', s_clean)
    if match:
        try:
            amount = float(match.group(1)) * 100000
        except:
            amount = None

    # Pattern 2: "4,00,000" or "400000" or "4 00 000"
    if amount is None:
        m = re.search(r'(\d{1,3}(?:[ ,]?\d{2,3}){1,3})', s_clean)
        if m:
            try:
                cleaned = re.sub(r'[ ,]', '', m.group(1))
                amount = float(cleaned)
            except:
                amount = None

    # Pattern 3: "50k" or "50 k" or "50K"
    if amount is None:
        m = re.search(r'(\d+(?:\.\d+)?)\s*[kK]\b', s_clean)
        if m:
            try:
                amount = float(m.group(1)) * 1000
            except:
                amount = None

    # Pattern 4: any number >= 1000 (fallback)
    if amount is None:
        m = re.search(r'\b(\d{4,})\b', s_clean)
        if m:
            try:
                amount = float(m.group(1))
            except:
                pass

    # tenure (years / months)
    m = re.search(r'(\d+(?:\.\d+)?)\s*(year|years|yr|yrs)\b', s_clean)
    if m:
        try:
            tenure_months = int(float(m.group(1)) * 12)
        except:
            tenure_months = None
    else:
        m2 = re.search(r'(\d+(?:\.\d+)?)\s*(month|months|mo|mos)\b', s_clean)
        if m2:
            try:
                tenure_months = int(float(m2.group(1)))
            except:
                tenure_months = None

    # Purpose keywords
    for word in ["wedding", "marriage", "medical", "education", "business", "home", "car", "travel"]:
        if word in s_clean:
            purpose = word
            break


    # default demo rate and tenure if not provided
    demo_rate = 12.0
    default_tenure = 36

    # If no amount found, ask user to provide it (but mention CRM if available)
    if not amount:
        if crm and isinstance(crm, dict) and crm.get("income_monthly"):
            friendly = f"I can see your income in CRM: ₹{int(crm.get('income_monthly')):,}. Tell me how much loan you need (e.g., 400000) and I will show EMI options."
        else:
            friendly = "Tell me how much you need (for example: 400000 or 5 lakh) and why, and I'll show EMI options."
        return {"reply": friendly, "quick_replies": quick_replies}

    # At this point we have an amount; compute an estimate and EMI options
    tenure_used = tenure_months or default_tenure
    try:
        est_emi = int(round(emi_calc(amount, demo_rate, tenure_used)))
    except Exception:
        # fallback local calculation if emi_calc missing
        r = demo_rate / 12 / 100
        if r == 0:
            est_emi = int(round(amount / tenure_used))
        else:
            est_emi = int(round(amount * r * (1 + r) ** tenure_used / ((1 + r) ** tenure_used - 1)))

    # Build decision result (keeps existing keys similar to your original structure)
    decision_result["loan_request"] = {
        "loan_amount": amount,
        "tenure_months": tenure_used,
        "rate": demo_rate,
        "est_emi": est_emi
    }
    decision_result["intent"] = "loan_interest"
    decision_result["purpose"] = purpose or "general"

    # Compose friendly reply (short)
    friendly = f"I estimate an EMI of ₹{est_emi:,}/month for a loan of ₹{int(amount):,} over {tenure_used} months at {demo_rate}% p.a."

    if crm and isinstance(crm, dict):
        try:
            inc = int(crm.get("income_monthly") or 0)
            if inc:
                friendly += f" I see monthly income on file: ₹{inc:,} — I can use that for pre-approval if you want."
        except:
            pass

    # quick replies: keep Check pre-approval convenient
    quick_replies = ["Check pre-approval", "Show EMI options", "Change tenure"]

    # compute emi options for a set of common tenures
    emi_opts = []
    try:
        emi_opts = emi_options_for_amount(amount, demo_rate)
    except Exception:
        # fallback basic options if something fails
        emi_opts = []
        for n in [12, 24, 36, 48, 60]:
            try:
                e = int(round(emi_calc(amount, demo_rate, n)))
            except:
                # local fallback
                r = demo_rate / 12 / 100
                if r == 0:
                    e = int(round(amount / n))
                else:
                    e = int(round(amount * r * (1 + r) ** n / ((1 + r) ** n - 1)))
            emi_opts.append({"tenure_months": n, "emi": e})

    # return payload (frontend expects these keys)
    return {
        "decision": decision_result,
        "reply": friendly,
        "quick_replies": quick_replies,
        "emi_options": emi_opts
    }
# <<< END CHANGED

# Orchestrator endpoint
# ------------------------
@app.post("/orchestrate_apply")
def orchestrate_apply(payload: dict = Body(...)):
    """
    Runs: KYC -> Underwriting (/apply) -> PDF gen if approved -> audit -> metrics.
    Returns structured response:
      {
        "decision": { ... },   # underwriting result (dict)
        "kyc": { ... },        # kyc result
        "pdf_url": "/pdf/...." or None
      }
    Defensive: catches errors, writes audit entries, and returns JSONResponse on failures.
    """
    try:
        customer_id = payload.get("customer_id") or payload.get("applicant_id") or payload.get("id")
        if not customer_id:
            return JSONResponse(status_code=400, content={"error": "missing customer_id in payload"})

        # 1) Run local KYC
        try:
            kyc_res = kyc_check(customer_id)
        except Exception as e:
            # KYC check itself failed unexpectedly
            tb = traceback.format_exc()
            audit_log({
                "ts": datetime.datetime.utcnow().isoformat(),
                "customer_id": customer_id,
                "action": "orchestrate_kyc_error",
                "data": f"{str(e)} | TRACE: {tb[:2000]}"
            })
            return JSONResponse(status_code=500, content={"error": "kyc_check_failed", "detail": str(e), "trace": tb})

        if kyc_res.get("status") == "FAIL":
            # Log and return a REFER result (no underwriting / pdf)
            audit_log({
                "ts": datetime.datetime.utcnow().isoformat(),
                "customer_id": customer_id,
                "action": "orchestrate_kyc_fail",
                "data": json.dumps(kyc_res)
            })
            decision_result = {
                "customer_id": customer_id,
                "decision": "REFER",
                "reasons": ["KYC checks failed or missing information"]
            }
            # append metrics best-effort
            try:
                append_metrics_row(decision_result)
            except Exception:
                pass
            return {
                "customer_id": customer_id,
                "kyc": kyc_res,
                "decision": "REFER",
                "reasons": ["KYC checks failed or missing information"],
                "pdf_url": None
            }

        # 2) Call underwriting (internal apply)
        apply_req = {
            "customer_id": customer_id,
            "loan_amount": payload.get("loan_amount", 0),
            "tenure_months": payload.get("tenure_months", 0),
            "existing_monthly_debt": payload.get("existing_monthly_debt", 0)
        }
        try:
            decision_result = apply(apply_req)
            # if apply returned a JSONResponse (error), try to parse
            if isinstance(decision_result, JSONResponse):
                try:
                    body = decision_result.body
                    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
                    decision_result = json.loads(text)
                except Exception:
                    # pass through the JSONResponse (likely an error)
                    return decision_result
        except Exception as e:
            tb = traceback.format_exc()
            audit_log({
                "ts": datetime.datetime.utcnow().isoformat(),
                "customer_id": customer_id,
                "action": "orchestrate_underwriting_error",
                "data": f"{str(e)} | TRACE: {tb[:2000]}"
            })
            return JSONResponse(status_code=502, content={"error": "underwriting_failed", "detail": str(e), "trace": tb})

        # Safety: ensure we have a dict
        if not isinstance(decision_result, dict):
            # try to coerce to dict if possible
            try:
                decision_result = dict(decision_result)
            except Exception:
                audit_log({
                    "ts": datetime.datetime.utcnow().isoformat(),
                    "customer_id": customer_id,
                    "action": "orchestrate_bad_underwriting_type",
                    "data": str(type(decision_result))
                })
                return JSONResponse(status_code=500, content={"error": "unexpected_underwriting_result_type", "type": str(type(decision_result))})

        # 3) If approved -> generate PDF and return link
        pdf_url = None
        if decision_result.get("decision") == "APPROVE":
            try:
                filename = generate_sanction_pdf(decision_result)
                pdf_url = f"/pdf/{filename}"
                audit_log({
                    "ts": datetime.datetime.utcnow().isoformat(),
                    "customer_id": customer_id,
                    "action": "sanction_pdf_generated",
                    "data": filename
                })
            except Exception as e:
                tb = traceback.format_exc()
                audit_log({
                    "ts": datetime.datetime.utcnow().isoformat(),
                    "customer_id": customer_id,
                    "action": "sanction_pdf_failed",
                    "data": f"{str(e)} | TRACE: {tb[:2000]}"
                })
                # return error but include the decision result so frontend can show it
                return JSONResponse(status_code=500, content={"error": "pdf_generation_failed", "detail": str(e), "trace": tb, "decision": decision_result})

        # 4) append metrics (best-effort)
        try:
            append_metrics_row(decision_result)
        except Exception:
            # don't fail the request if metrics write fails
            pass

        # 5) final response
        return {
            "decision": decision_result,
            "kyc": kyc_res,
            "pdf_url": pdf_url
        }

    except Exception as e:
        # catch-all unexpected error
        tb = traceback.format_exc()
        try:
            audit_log({
                "ts": datetime.datetime.utcnow().isoformat(),
                "customer_id": payload.get("customer_id") or "UNKNOWN",
                "action": "orchestrate_internal_error",
                "data": f"{str(e)} | TRACE: {tb[:2000]}"
            })
        except:
            pass
        return JSONResponse(status_code=500, content={"error": "orchestrate_internal_error", "detail": str(e), "trace": tb})

# --- metrics setup ---
METRICS_FILE = os.path.join(os.path.dirname(__file__), "metrics.csv")

def ensure_metrics_file():
    if not os.path.exists(METRICS_FILE):
        # write header
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            f.write("ts,customer_id,decision,emi,dti,credit_score,loan_amount,tenure_months\n")

def append_metrics_row(decision_result: dict):
    """
    Append one row to metrics CSV with key fields for dashboards/slides.
    """
    try:
        ensure_metrics_file()
        ts = datetime.datetime.utcnow().isoformat()
        cust = decision_result.get("customer_id") if isinstance(decision_result, dict) else "UNKNOWN"
        decision = decision_result.get("decision") if isinstance(decision_result, dict) else "UNKNOWN"
        emi = decision_result.get("emi") if isinstance(decision_result, dict) else ""
        dti = decision_result.get("dti") if isinstance(decision_result, dict) else ""
        credit = (decision_result.get("credit_score") if isinstance(decision_result, dict) else "") or (decision_result.get("credit",{}).get("credit_score") if isinstance(decision_result.get("credit",{}), dict) else "")
        loan_amount = (decision_result.get("loan_request", {}) or {}).get("loan_amount", "")
        tenure = (decision_result.get("loan_request", {}) or {}).get("tenure_months", "")

        # safe formatting: replace commas to avoid CSV break
        def clean(x):
            if x is None:
                return ""
            s = str(x)
            return s.replace(",", "")
        row = ",".join([clean(ts), clean(cust), clean(decision), clean(emi), clean(dti), clean(credit), clean(loan_amount), clean(tenure)])
        with open(METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except Exception as e:
        # don't crash the app for metrics errors — write to audit if possible
        try:
            audit_log({"ts": datetime.datetime.utcnow().isoformat(), "customer_id": decision_result.get("customer_id") if isinstance(decision_result, dict) else "UNKNOWN", "action": "metrics_append_failed", "data": str(e)})
        except:
            pass

# ------------------------
# KYC public endpoint
# ------------------------
@app.get("/kyc/{customer_id}")
def get_kyc(customer_id: str):
    """
    Public endpoint to run the lightweight KYC check for a customer.
    Returns {"status":"PASS"/"FAIL", "missing": [...], "issues":[...]}
    """
    try:
        res = kyc_check(customer_id)
        return {"customer_id": customer_id, "kyc": res}
    except Exception as e:
        tb = traceback.format_exc()
        return JSONResponse(status_code=500, content={"error":"kyc_internal_error", "detail": str(e), "trace": tb})

# ------------------------
# Metrics endpoints
# ------------------------
@app.get("/metrics")
def get_metrics(limit: int = Query(100, ge=1, le=1000)):
    """
    Return simple aggregated metrics and the most recent `limit` metric rows.
    """
    ensure_metrics_file()
    # read lines
    with open(METRICS_FILE, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip()]
    if len(lines) <= 1:
        return {"count": 0, "summary": {}, "rows": []}

    header = lines[0].split(",")
    rows = []
    for ln in lines[1:]:
        parts = ln.split(",")
        row = dict(zip(header, parts + [""] * max(0, len(header)-len(parts))))
        rows.append(row)
    # reverse for newest first
    rows = list(reversed(rows))
    limited = rows[:limit]

    # aggregate counts by decision
    summary = {}
    for r in rows:
        d = r.get("decision", "").upper()
        if not d:
            d = "UNKNOWN"
        summary[d] = summary.get(d, 0) + 1

    return {"count": len(rows), "summary": summary, "rows": limited}

@app.get("/metrics/download")
def download_metrics():
    """
    Download raw metrics CSV.
    """
    ensure_metrics_file()
    if not os.path.exists(METRICS_FILE):
        return JSONResponse(status_code=404, content={"error":"no metrics file yet"})
    return FileResponse(METRICS_FILE, media_type="text/csv", filename=os.path.basename(METRICS_FILE))


from fastapi import Query
from typing import Optional

def read_audit_rows():
    """Return list of audit rows as dicts (ts, customer_id, action, data)."""
    if not os.path.exists(AUDIT_FILE):
        return []
    rows = []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) <= 1:
        return []
    # skip header
    for line in lines[1:]:
        # split only first 3 commas, as data may contain commas inside quotes
        parts = []
        cur = ""
        in_quotes = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"' and (i == 0 or line[i-1] != "\\"):
                in_quotes = not in_quotes
                cur += ch
            elif ch == "," and not in_quotes and len(parts) < 3:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
            i += 1
        # append remainder
        if cur:
            parts.append(cur)
        # strip newline and quotes from data column
        if len(parts) >= 4:
            ts = parts[0].strip()
            cid = parts[1].strip()
            action = parts[2].strip()
            data = parts[3].strip()
            # remove surrounding quotes if present
            if data.startswith('"') and data.endswith('"'):
                data = data[1:-1].replace('""', '"')
            rows.append({"ts": ts, "customer_id": cid, "action": action, "data": data})
    return rows

@app.get("/audit")
def get_audit(limit: int = Query(50, ge=1, le=1000), action: Optional[str] = None):
    """
    Return recent audit rows and simple summary counts.
    Query params:
      - limit: how many recent rows to return (default 50)
      - action: optional filter (e.g. apply_approve, orchestrate_kyc_fail)
    """
    rows = read_audit_rows()
    # reverse so newest first
    rows = list(reversed(rows))
    if action:
        rows = [r for r in rows if r.get("action") == action]
    limited = rows[:limit]

    # summary counts by action and by decision if present in action text
    counts = {}
    decision_counts = {"APPROVE": 0, "REFER": 0, "REJECT": 0}
    for r in rows:
        a = r.get("action")
        counts[a] = counts.get(a, 0) + 1
        # also examine action names like apply_approve / apply_reject / apply_refer
        if isinstance(a, str):
            la = a.lower()
            if "approve" in la:
                decision_counts["APPROVE"] += 1
            elif "refer" in la:
                decision_counts["REFER"] += 1
            elif "reject" in la:
                decision_counts["REJECT"] += 1

    return {"count": len(rows), "summary_by_action": counts, "decision_counts": decision_counts, "rows": limited}

@app.get("/audit/download")
def download_audit():
    """
    Download raw audit_log.csv file (if exists).
    """
    if not os.path.exists(AUDIT_FILE):
        return JSONResponse(status_code=404, content={"error":"no audit file yet"})
    return FileResponse(AUDIT_FILE, media_type="text/csv", filename=os.path.basename(AUDIT_FILE))
