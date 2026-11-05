import csv
import io
import json
import sqlite3

import streamlit as st

APP_ERRORS = (OSError, ValueError, RuntimeError, sqlite3.Error)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def safe_csv(rows):
    if not rows:
        return ""
    fields = list(dict.fromkeys(k for r in rows for k in r))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        cleaned = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            cleaned[key] = value
        writer.writerow(cleaned)
    return output.getvalue()


def download(rows, prefix="saker"):
    a, b = st.columns(2)
    a.download_button(
        "Last ned JSON", json_text(rows), f"{prefix}.json", "application/json", key=f"{prefix}_json"
    )
    b.download_button(
        "Last ned CSV",
        safe_csv(rows).encode("utf-8-sig"),
        f"{prefix}.csv",
        "text/csv",
        key=f"{prefix}_csv",
    )
