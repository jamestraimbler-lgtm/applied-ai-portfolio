# FinanZen CRM and document review

Personal project built with substantial AI assistance. This local Python/Flask
prototype connects client dossiers, document checklists, tasks and audit records
to a document-review workflow. It is evidence of custom CRM development;
it does not establish Salesforce or commercial CRM administration experience.

The [application](source/app.py) encrypts uploaded documents, extracts PDF text,
checks that the configured AI endpoint is local, and stores extracted fields as
a draft. A person reviews or changes the fields before confirming the document
and updating its checklist. [Database functions](source/database.py) preserve
the case relationships and audit entries. [Security code](source/security.py)
handles password hashing, the in-memory encryption key and inactivity locking.

## Reproduce the synthetic checks

From this directory, using Python 3.11+ and Node.js:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r source/requirements.txt
.venv/bin/python check_synthetic.py
.venv/bin/python -m unittest discover -s source -p test_rekenkern.py
```

The walkthrough overrides all data/config/document paths before importing the
app. It uses only a temporary database and fabricated data. It verifies upload,
encrypted storage and download, remote-endpoint refusal, draft extraction,
human correction/confirmation, checklist changes, tasks, audit and inactivity
lock. PDF extraction and AI replies are mocked; no actual inference or outbound
AI request is exercised. `NODE_BIN` can select the Node executable.

The same script compares the existing Python and browser JavaScript calculation
cores across 314 recorded numerical scenarios, within one cent, with matching
limit and interest-band decisions. The separate calculation suite has 17 tests.
This checks consistency of archived model inputs, not current mortgage rules,
financial advice or correctness against an independent regulatory authority.

## Limits

This is a local prototype, not a production deployment or security review.
Selected sensitive fields and documents are encrypted; the whole SQLite
database is not encrypted, and basic customer fields remain plaintext.
Multi-user isolation, CSRF coverage and a deployment security review are still
needed before real shared use. No customer records, password configuration,
documents or original runtime database are included. Real extraction quality
and user acceptance remain unverified.

Verified on 13 October 2026. [Portfolio](../../README.md).
