
---

# Product Requirements Document (PRD)  
## Project ID: PRJ-2026-0045  
### Title: AI-Powered Invoice & Receipt Extraction Engine  

---

## 1. Problem Statement
Manual entry of invoices and receipts for tax returns and corporate accounting is a massive pain point. It is slow, highly prone to human error, and drains administrative resources. Existing OCR solutions often fail on unstructured data or non-standard receipt formats. Furthermore, utilizing standard LLMs for data extraction introduces the risk of "hallucinations" (inventing numbers or categories). There is a critical need for an automated, intelligent system that can extract data, dynamically categorize expenses, and implement rigorous auditing checks to ensure 100% data accuracy before it hits the general ledger.

## 2. Target Users
### Primary Users:
* **Self-Employed Individuals / Freelancers:** Need a fast way to upload piles of receipts and get a clean, categorized output for tax filing.
* **Company Accountants / Bookkeepers:** Require bulk processing of vendor invoices with an audit trail and confidence scoring to review flagged items quickly.
### Secondary Users:
* **System Administrators:** Manage the local Ollama models, configure taxonomy rules, and maintain system health via the Django admin panel.

## 3. Goals & Success
### Business Goals:
* Eliminate manual data entry for financial documents.
* Leverage a local Ollama instance for secure, offline document processing to maintain strict data privacy.
* Implement a zero-hallucination architecture using deterministic validation.
### Success Criteria ("Done"):
* System successfully ingests images/PDFs and routes them to a local multimodal Llama model (e.g., LLaVA) or an OCR-to-Text-to-LLM pipeline.
* System extracts exact fields: Vendor Name, Date, Total, Subtotal, Tax, and Line Items.
* System dynamically matches or creates categories based on context (e.g., "Home Depot" -> "Hardware/Maintenance").
* System flags any document where deterministic math (`Subtotal + Tax = Total`) fails for human auditing.

## 4. Feature List
### Basic (MVP)
* **Document Ingestion:** Upload interface for images (JPG/PNG) and PDFs.
* **Ollama Extraction Engine:** API connection to local Ollama to prompt for strict JSON schema extraction.
* **Dynamic Categorization:** Logic to query existing categories; if a semantic match isn't found, the system proposes a new category for user approval.
* **Audit Engine (Anti-Hallucination):** * Type-checking (ensuring dates are valid, totals are floats).
    * Mathematical validation (Line Items sum = Subtotal, Subtotal + Tax = Total).
    * Confidence flagging (routing failed checks to a "Needs Review" queue).

### Intermediate
* **Bulk Upload:** Support for dragging and dropping multiple files or ZIP archives.
* **Human-in-the-Loop (HITL) UI:** A side-by-side verification screen showing the original document next to the extracted form fields for rapid correction.
* **Export:** CSV/Excel export formatted specifically for standard tax software or ERPs.

---
