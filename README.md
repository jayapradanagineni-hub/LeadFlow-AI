# LeadFlow — AI Lead Qualification & Follow-up Automation

A beginner-friendly proof of concept in Python. The core app uses only the Python standard library, so no third-party packages are required.

## What it does

1. Validates required fields and checks for a valid email or phone number.
2. Detects duplicates by normalized email, or phone + company.
3. Scores leads from 0–100 using transparent rules.
4. Produces a pain point, service recommendation, and follow-up message. It uses a safe template by default; optional Claude API integration is available.
5. Stores leads, events, and alert state in SQLite.
6. Creates alerts for Hot leads; writes an outbox entry and optionally sends to Slack.
7. Supports inspecting, listing, exporting, and retrying pending alerts.

## Requirements

- Windows 10/11
- Python 3.10+ recommended
- No package installation needed for the default workflow

## Setup on Windows

1. Extract `leadflow_submission.zip` into a folder.
2. Open that folder in File Explorer.
3. Click the address bar, type `cmd`, and press Enter.
4. Check Python:

   ```bat
   python --version
   ```

   If needed, try `py --version`.

## Run tests

```bat
python -m unittest -v test_leadflow.py
```

Expected: `Ran 12 tests` and `OK`.

## Run the sample workflow

```bat
python leadflow.py process sample_leads.json
```

The sample file has seven input records, including a duplicate and an invalid lead. First run should show qualification, duplicate/rejection messages, follow-up drafts, and a summary. Re-running the file is safe from duplicate record creation for already-qualified contacts, but previously rejected sample records are retained again.

## Other commands

```bat
python leadflow.py --help
python leadflow.py list
python leadflow.py inspect 1
python leadflow.py inspect ananya@example.com
python leadflow.py export leadflow_export.csv
python leadflow.py retry-alerts
```

The inspect ID is an example; use an ID shown by `list` or the processing output.

## Files created while running

- `leadflow.db` — SQLite database (created automatically)
- `outbox.jsonl` — local alert outbox (created when Hot leads are processed)
- `leadflow_export.csv` — created by the export command

By default, the database and outbox are created beside `leadflow.py`. You can override their paths with `LEADFLOW_DB` and `LEADFLOW_OUTBOX`.

## Scoring model

| Signal | Points |
|---|---:|
| Budget ≥ ₹100,000 | 30 |
| Budget ₹50,000–₹99,999 | 20 |
| Budget ₹20,000–₹49,999 | 10 |
| Intent words | 5 per matched word, capped at 30 |
| Target industry | 15 |
| Referral / website demo / sales enquiry | 10 |
| Other known source | 5 |
| Valid email | 5 |
| Valid phone | 5 |
| Company present | 5 |

Priority thresholds: Hot ≥70, Warm 40–69, Cold <40. The scoring is rule-based and explainable; it is not a trained machine-learning model. Intent points use simple word matching, so it can be improved for more sophisticated language understanding.

## Optional Claude API

The default run uses templates and requires no key. To try the live API in Windows Command Prompt (for the current terminal session only):

```bat
set ANTHROPIC_API_KEY=your_actual_key
python leadflow.py process sample_leads.json
```

Keep API keys private. Live API usage may cost money and requires internet access. If the call fails or returns invalid content, the program falls back to a template. The live Claude call has not been verified as part of the packaged tests.

Optional model override:

```bat
set ANTHROPIC_MODEL=claude-3-5-haiku-latest
```

## Optional Slack alerts

Set a Slack incoming webhook URL in the current Command Prompt session:

```bat
set SLACK_WEBHOOK_URL=your_slack_webhook_url
python leadflow.py process sample_leads.json
```

Only do this with a webhook you control. Failed Slack alerts remain pending and can be retried with `python leadflow.py retry-alerts`. Without a webhook, Hot-lead alerts are printed and written to the local outbox.

## Workflow

Receive JSON lead → validate → deduplicate → score → Claude or template fallback → SQLite storage → Hot-lead alert → inspect/export.

See `architecture.png`.

## Assumptions and limitations

- Phone validation is a lightweight format check, not verification that a number is active.
- The sample and scoring budget use INR.
- Lead scoring is deterministic rules, not a trained predictive model.
- The sample data is fictional.
- No web form, authentication, production CRM, or access control is included.
- A local SQLite file is suitable for a demo, not a multi-user production deployment.
- Tests mock/avoid live external API calls; they do not prove Claude or Slack connectivity.
- Alert state is stored in SQLite; the outbox is a local audit file.

## Challenge demo script

1. Run the unit tests.
2. Process the sample leads.
3. Show the Hot lead and the reasons for its score.
4. Inspect the lead by ID.
5. Show the duplicate being ignored and invalid lead being rejected.
6. Run `list` and `export`.
7. Explain that Claude and Slack are optional integrations and need valid credentials.
