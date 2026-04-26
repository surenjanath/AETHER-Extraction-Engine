
# System Design Document  
## Project ID: PRJ-2026-0045  

---

## 1. Context
This is a Django-based web platform utilizing a local Ollama integration to securely process financial documents. The backend manages the state, file storage, and audit logic, while Ollama serves as the cognitive extraction engine. The UI relies on AJAX for seamless, single-page-like document review queues without heavy page reloads.

## 2. Architecture & Anti-Hallucination Strategy
Because LLMs are probabilistic, "preventing hallucinations" requires wrapping the LLM in deterministic programmatic rules.

1.  **Strict JSON Prompting:** Ollama is prompted to return *only* a specific JSON schema.
2.  **Pydantic/Django Form Validation:** The backend intercepts the JSON and validates data types immediately. If it fails, the backend automatically prompts Ollama to correct the output (up to 3 retries).
3.  **Deterministic Math Checks:** The Django backend calculates the line items and tax. If the LLM's extracted `Total` does not match the backend's calculated total, the document is flagged `status='audit_required'`.
4.  **Learning Loop:** When a user corrects a hallucinated or incorrect field in the UI, the system logs the correction to an `AuditLog` table to refine future few-shot prompts sent to Ollama.

## 3. Database Schema (Django ORM)

### 1. `Category`
* `id` (PK)
* `name` (e.g., "Meals & Entertainment", "Software Subscriptions")
* `description`
* `is_system_generated` (Boolean)

### 2. `InvoiceDocument`
* `id` (PK)
* `file` (FileField/ImageField)
* `upload_date`
* `status` (`pending_extraction`, `audit_required`, `verified`)
* `confidence_score` (Float)

### 3. `ExtractedData`
* `id` (PK)
* `document` (FK to `InvoiceDocument`)
* `vendor_name` (String)
* `date_issued` (Date)
* `subtotal` (Decimal)
* `tax_amount` (Decimal)
* `total_amount` (Decimal)
* `category` (FK to `Category`)

### 4. `AuditLog` (For system adjustment)
* `id` (PK)
* `document` (FK to `InvoiceDocument`)
* `field_changed` (e.g., "total_amount")
* `original_value_from_ai`
* `corrected_value_from_user`

---