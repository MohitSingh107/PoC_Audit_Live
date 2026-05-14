# curriculum.py
import gspread
import pandas as pd
import streamlit as st
from rapidfuzz import process
from typing import Optional

SPREADSHEET_ID = "1TUK9kxOcT3tg5nT7MVc3v8gJ9oi83nzI2_aVN6nFAOo"


def _resolve_gspread_client(credentials_dict: dict = None, credentials_path: str = "service_account.json"):
    """
    Build and return an authenticated gspread client.
    Priority: credentials_dict (UI upload) → st.secrets["gcp_service_account"] → local file.
    """
    if credentials_dict:
        return gspread.service_account_from_dict(credentials_dict)

    try:
        secret = st.secrets.get("gcp_service_account", None)
        if secret:
            return gspread.service_account_from_dict(dict(secret))
    except Exception:
        pass

    return gspread.service_account(filename=credentials_path)


class CurriculumService:
    def __init__(self, credentials_dict: dict = None, credentials_path: str = "service_account.json"):
        gc = _resolve_gspread_client(credentials_dict=credentials_dict, credentials_path=credentials_path)
        sh = gc.open_by_key(SPREADSHEET_ID)

        frames = []
        for ws in sh.worksheets():
            values = ws.get_all_values()
            if not values:
                continue

            headers = values[0]
            rows = values[1:]

            if not rows:
                continue

            df = pd.DataFrame(rows, columns=headers)
            df.columns = [c.strip() for c in df.columns]

            # Standardize column names
            rename_map = {
                "Class Name/Topic": "Session Name",
                "Class #": "Session #",
            }
            df.rename(columns=rename_map, inplace=True)

            # Drop columns with empty names (blank columns in sheet)
            df = df.loc[:, df.columns != ""]

            # Drop any remaining duplicate columns
            df = df.loc[:, ~df.columns.duplicated()]

            df["Module"] = ws.title
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True)
        for col in ["Week #", "Session #", "Session Name"]:
            if col in combined.columns:
                combined[col] = combined[col].replace("", pd.NA).ffill()

        self._index = combined

    def modules(self) -> list[str]:
        return self._index["Module"].dropna().unique().tolist()

    def sessions(self, module: str) -> list[str]:
        df = self._index[self._index["Module"] == module]
        return df["Session Name"].dropna().unique().tolist()

    def get_syllabus(self, session_name: str, module: Optional[str] = None) -> str:
        df = self._index[self._index["Module"] == module] if module else self._index

        matched = df[df["Session Name"].str.strip() == session_name.strip()]

        # Fuzzy fallback
        if matched.empty:
            names = df["Session Name"].dropna().unique().tolist()
            hit = process.extractOne(session_name, names)
            if hit and hit[1] >= 82:
                matched = df[df["Session Name"] == hit[0]]

        if matched.empty:
            return ''

        topics = (
            matched["Topics/Objectives of the Class"]
            .dropna().astype(str).str.strip()
            .tolist()
        )
        topics = [t for t in topics if t and "assess" not in t.lower()]
        return "\n".join(f"- {t}" for t in topics)


# ── This runs when you execute the file ──────────────────────────
if __name__ == "__main__":
    curriculum = CurriculumService()
    session_name = input("Enter session name: ")
    syllabus = curriculum.get_syllabus(session_name)
    print(syllabus)