# ADR-001: Deterministic Regex Extraction over ML-Based Parsing

**Status:** Accepted  
**Date:** 2026-05-20

---

## Context

The engine processes OCR-generated text from POS receipts and product export files in the Lima/LATAM market. These documents have consistent structural patterns (ID fields, product names, prices, stock counts) but high character-level noise from OCR engines.

Two approaches were evaluated.

---

## Options

**Option A: Deterministic regex with explicit OCR correction maps**

A compiled regex pattern captures named groups (id, name, price, stock). A translation table corrects known character confusions (O→0, l→1, I→1, B→8, S→5) before the extracted values are stored. Blacklist patterns use word-boundary anchors to filter noise tokens.

**Option B: ML-based NER (Named Entity Recognition)**

A fine-tuned spaCy or transformers model trained on labeled receipt data would identify and extract fields without explicit pattern authorship. Character corrections would be implicit in the training data.

---

## Decision

Option A. Deterministic regex.

---

## Reasoning

The input domain is narrow and structurally consistent. The OCR hallucinations are a known, enumerable set of character confusions, not open-ended semantic ambiguity. A regex pattern that covers the field structure plus a 6-entry translation table covers 95%+ of the actual failure modes without requiring a labeled training dataset, a model serving infrastructure, or a GPU.

An ML model introduces three costs that are not justified by the problem:
1. A labeled dataset of several thousand receipts to achieve reliable extraction accuracy
2. A retraining pipeline when the source document format changes
3. Non-deterministic output — two identical input lines could produce different extracted values if the model's confidence threshold is near the boundary

When the source document format changes significantly enough that the regex no longer covers it, the correct response is to update the regex pattern, not to replace the entire extraction strategy.

---

## Consequences

The regex must be maintained as source document formats evolve. This is a low-cost operation (one pattern file, versioned in git) but it is a manual one — it does not self-update.

The engine will not generalize to documents with genuinely free-form structure (e.g., handwritten notes, open-form invoices with no fixed field positions). That use case would require Option B and is out of scope for V3.
