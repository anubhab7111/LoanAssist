# 💬 Smart Loan Chatbot – EY Techathon 6.0

> A full-stack intelligent loan application chatbot that guides users through the complete loan journey — from marketing entry to sanction letter download.  
> Built for **EY Techathon 6.0** using **FastAPI** (backend) and **Streamlit** (frontend).

---

## 🛠️ Built With
![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green?logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-Frontend-red?logo=streamlit)
![EY Techathon](https://img.shields.io/badge/EY-Techathon-yellow)

---

## 🚀 Features

| Feature | Description |
|----------|--------------|
| ✉️ **Marketing Entry** | Captures customer email or prefill data from marketing links |
| 💬 **Hero Chat** | Natural language loan conversation — calculates EMI instantly |
| 🤔 **Hesitation Recovery** | Detects “too expensive / can’t afford” messages and suggests better options |
| 🧾 **KYC Consent** | Collects PAN & income for KYC verification |
| ⚙️ **Orchestration Stepper** | Shows real-time KYC → Underwriting → PDF progress |
| 📄 **Sanction Letter** | Generates and downloads a personalized sanction-letter PDF if approved |

---

## 🧠 How It Works

1. **User enters Customer ID** → chatbot auto-fetches CRM data.  
2. **User asks for a loan** → backend calculates EMI & tenure options.  
3. **Bot handles hesitation** (“too expensive”) → suggests alternatives.  
4. **User proceeds to apply** → KYC consent form appears (PAN + income).  
5. **Orchestration stepper** runs → KYC ✅ → Underwriting ✅ → PDF ✅.  
6. **Sanction letter generated** → available for manual download.

---

## 🏗️ Architecture

Frontend (Streamlit)
│
│── chatui.py # Chat interface, EMI options, KYC modal, orchestration stepper
│
└── Backend (FastAPI)
│
├── main.py # Core API logic: NLP handler, KYC, underwriting, PDF generation
├── data/ # Sample CRM / applicants CSVs
└── pdfs/ # Auto-generated sanction letters

yaml
Copy code

**Tech Stack:**  
🧠 FastAPI · 💻 Streamlit · 🐍 Python · 🗃️ Pandas · 🧾 FPDF  

---

## ⚙️ Setup Instructions

### 1️⃣ Clone the repository
```bash
git clone https://github.com/yourusername/smart-loan-chatbot.git
cd smart-loan-chatbot
2️⃣ Create a virtual environment
bash
Copy code
python -m venv venv
# Activate the environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
3️⃣ Install dependencies
bash
Copy code
pip install -r requirements.txt
4️⃣ Run the backend (FastAPI)
bash
Copy code
cd backend
uvicorn main:app --reload --port 8001
5️⃣ Run the frontend (Streamlit)
bash
Copy code
cd frontend
streamlit run chatui.py
6️⃣ Open in browser
arduino
Copy code
http://localhost:8501
📸 Screenshots
Feature	Screenshot
Marketing Entry	
Hero Chat	
Hesitation Recovery	
KYC Consent	
Orchestration Stepper	
Sanction Letter	

📸 Replace the paths in parentheses with your actual screenshot locations.

💬 Sample Conversation Flow
vbnet
Copy code
User: I want a 5 lakh loan for 3 years
Bot: Sure! Here are your EMI options 👇
      • 12 months – ₹44,300/mo
      • 24 months – ₹23,800/mo
      • 36 months – ₹16,600/mo

User: That’s too expensive
Bot: No worries — want me to show longer tenure or lower EMI options?

User: Proceed with Formal Apply
Bot: Great! Please share your PAN and monthly income for KYC verification.
...
Bot: KYC ✅ Underwriting ✅ PDF ✅
Bot: Your loan is approved! Click below to download your sanction letter.
🧾 Folder Structure
cpp
Copy code
smart-loan-chatbot/
│
├── backend/
│   ├── main.py
│   ├── data/
│   ├── pdfs/
│   └── requirements.txt
│
├── frontend/
│   ├── chatui.py
│   └── requirements.txt
│
├── assets/ (optional screenshots)
└── README.md
📚 Future Enhancements
💳 Integration with real bank APIs

🧮 Improved underwriting model using ML

🔒 Authentication & role-based dashboards

📱 Responsive web app design

👨‍💻 Author
Manish Patra
💻 Student Developer | Creative Tech Enthusiast
🔗 LinkedIn · GitHub

⭐ Acknowledgment
Special thanks to EY Techathon 6.0 organizers for giving us this opportunity to turn ideas into impact.

🏁 If you like this project, consider giving it a ⭐ on GitHub!







