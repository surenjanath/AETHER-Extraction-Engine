# UI/UX Design Brief  
## Project ID: PRJ-2026-0045  

---

## 1. Design Goals
* **Density:** Data-dense layout to allow accountants to blast through reviews.
* **Theme:** Light UI with clear, outlined status icons (Check, Warning, Alert).
* **Layout:** Split-screen interface for the Human-in-the-loop review.

## 2. Key Screens

### 1. Dashboard & Upload
Provides a summary of processed documents and a dropzone for new files.
```text
+--------------------------------------------------+
|  [AI Receipt Engine]          [User] [Settings]  |
|                                                  |
|  [  Drag and Drop Receipts/Invoices Here  ]      |
|  [             (Browse Files)             ]      |
|                                                  |
|  [Queue Status]                                  |
|  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ |
|  │ Pending AI  │ │ Needs Audit │ │ Verified    │ |
|  │     4       │ │     2 ⚠️     │ │    145      │ |
|  └─────────────┘ └─────────────┘ └─────────────┘ |
+--------------------------------------------------+
```

### 2. Audit & Adjustment Queue (The "Anti-Hallucination" Screen)
This is where flagged documents land. The user sees the image side-by-side with the extracted data.
```text
+--------------------------------------------------+
|  [< Back to Queue]    Reviewing: INV-0042        |
|                                                  |
|  +--------------------+  +--------------------+  |
|  |                    |  | Vendor: Home Depot |  |
|  |    [RECEIPT        |  | Date: 2025-10-12   |  |
|  |     IMAGE          |  |                    |  |
|  |     VIEWER]        |  | Subtotal: $45.00   |  |
|  |                    |  | Tax:      $ 5.00   |  |
|  |                    |  | [⚠️] Total: $55.00  |  | < Math Error Flag
|  |                    |  |                    |  |
|  |                    |  | Category:          |  |
|  |                    |  | [Hardware       ▼] |  |
|  +--------------------+  +--------------------+  |
|                                                  |
|                   [Save & Mark Verified]         |
+--------------------------------------------------+
```

---

# Feature Breakdown & Epics

### Epic 1: Ingestion & Storage Pipeline
* **Story 1.1:** Build Django models for `InvoiceDocument` and `ExtractedData`.
* **Story 1.2:** Create the drag-and-drop UI with AJAX file chunking for large PDFs.
* **Story 1.3:** Implement local file storage and document status tracking.

### Epic 2: Ollama Extraction Integration
* **Story 2.1:** Build the Python service layer to communicate with the local Ollama API endpoint.
* **Story 2.2:** Engineer the system prompt to enforce rigid JSON outputs (e.g., "Return strictly valid JSON with the following keys...").
* **Story 2.3:** Implement a fallback text-extraction layer (like Tesseract OCR) to feed text to standard Llama 3 if multimodal/vision models are running too slow on the hardware.

### Epic 3: Deterministic Audit Engine (Guardrails)
* **Story 3.1:** Build the math-validation service (Subtotal + Tax == Total).
* **Story 3.2:** Build the dynamic categorization logic. Query existing DB categories; use cosine similarity or LLM to match. If confidence is low, create category and flag as `is_system_generated = True` for human approval.
* **Story 3.3:** Create the "Audit Queue" view where discrepant data is flagged in red for user correction.

### Epic 4: Export & Reporting
* **Story 4.1:** Build CSV export functionality mapping the verified SQLite data to standard accounting columns.
* **Story 4.2:** Build a dashboard view summarizing total expenses by category for the selected tax period.