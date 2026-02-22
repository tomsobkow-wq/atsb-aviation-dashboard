# ATSB Aviation Reports Dashboard

This project fetches the latest 10 ATSB aviation investigation report entries and builds:

- `data/reports.csv`
- `data/reports.json`
- `outputs/insights.md`
- `outputs/dashboard.html`

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python atsb_dashboard.py
```

Then open `outputs/dashboard.html` in a browser.

## Notes

- Data source: ATSB aviation investigations page and linked report pages.
- Latest entries may be ongoing investigations; final cause findings may not yet be published.
- Cause/severity buckets are keyword-based derived classifications from title + available narrative text.
