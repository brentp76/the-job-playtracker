import itertools
import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ----------------------------
# CONFIG (Your Game)
# ----------------------------
SUITS = [
    "Tools",
    "Goods",
    "Crew",
    "Access",
    "Spotlight",
    "Blackout",
    "Squeeze",
    "Clean-Up",
    "Leverage",
    "Aftermath",
    "Fog",
    "Middlemen",
    "Fence",
]

# Non-Authority suits required by player count
SUITS_REQUIRED = {
    2: 3,
    3: 4,
    4: 6,
    5: 6,
}

RULESET_PROFILES = ["Basic", "Standard", "Full", "Experimental"]

MODULES = [
    "Heat/Disgrace",
    "Safe",
    "Specialists",
    "Contingencies",
]

# ----------------------------
# GOOGLE SHEETS BACKEND
# ----------------------------
def get_gsheet_client():
    # Streamlit secrets must include:
    # [gcp_service_account] with the full service account json keys
    # and a string SHEET_ID
    import gspread
    from google.oauth2.service_account import Credentials

    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def get_sheet():
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["SHEET_ID"])
    # Tabs:
    # Plays (rows appended)
    # If not present, create
    try:
        ws = sh.worksheet("Plays")
    except Exception:
        ws = sh.add_worksheet(title="Plays", rows=2000, cols=30)
        ws.append_row([
            "timestamp_utc",
            "player_count",
            "ruleset_profile",
            "suits_used_json",
            "modules_on_json",
            "winner",
            "notes",
        ])
    return ws

def read_plays_df():
    ws = get_sheet()
    rows = ws.get_all_records()
    if not rows:
        return pd.DataFrame(columns=[
            "timestamp_utc","player_count","ruleset_profile",
            "suits_used_json","modules_on_json","winner","notes"
        ])
    df = pd.DataFrame(rows)
    # Normalize types
    if "player_count" in df.columns:
        df["player_count"] = pd.to_numeric(df["player_count"], errors="coerce").astype("Int64")
    return df

def append_play(play: dict):
    ws = get_sheet()
    ws.append_row([
        play["timestamp_utc"],
        play["player_count"],
        play["ruleset_profile"],
        json.dumps(play["suits_used"], ensure_ascii=False),
        json.dumps(play["modules_on"], ensure_ascii=False),
        play.get("winner",""),
        play.get("notes",""),
    ])

# ----------------------------
# COMBO GENERATION
# ----------------------------
def canonical_suits_list(suits):
    # Sort for stable combo IDs
    return sorted(suits, key=lambda x: x.lower())

def combo_id(player_count: int, ruleset_profile: str, suits_used: list[str]) -> str:
    suits_key = "|".join(canonical_suits_list(suits_used))
    return f"{player_count}P::{ruleset_profile}::{suits_key}"

def generate_all_combos():
    combos = []
    for pc, k in SUITS_REQUIRED.items():
        for suit_set in itertools.combinations(SUITS, k):
            suits_used = canonical_suits_list(list(suit_set))
            for profile in RULESET_PROFILES:
                combos.append({
                    "combo_id": combo_id(pc, profile, suits_used),
                    "player_count": pc,
                    "ruleset_profile": profile,
                    "suits_used": suits_used,
                })
    return pd.DataFrame(combos)

def compute_coverage(all_combos_df: pd.DataFrame, plays_df: pd.DataFrame) -> pd.DataFrame:
    if plays_df.empty:
        all_combos_df["played_count"] = 0
        all_combos_df["last_played_utc"] = ""
        return all_combos_df

    # Build combo_id for each play
    def play_to_combo_id(row):
        try:
            suits = json.loads(row["suits_used_json"]) if isinstance(row["suits_used_json"], str) else []
        except Exception:
            suits = []
        suits = canonical_suits_list(suits)
        return combo_id(int(row["player_count"]), str(row["ruleset_profile"]), suits)

    plays_df = plays_df.copy()
    plays_df["combo_id"] = plays_df.apply(play_to_combo_id, axis=1)

    counts = plays_df.groupby("combo_id").size().rename("played_count")
    last_play = plays_df.groupby("combo_id")["timestamp_utc"].max().rename("last_played_utc")

    out = all_combos_df.merge(counts, on="combo_id", how="left").merge(last_play, on="combo_id", how="left")
    out["played_count"] = out["played_count"].fillna(0).astype(int)
    out["last_played_utc"] = out["last_played_utc"].fillna("")
    return out

# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="The Job Playtest Tracker", layout="wide")

st.title("The Job — Playtest Tracker")
st.caption("Log plays and see unplayed suit combinations by player count and ruleset profile.")

tabs = st.tabs(["Log a Play", "Unplayed Combos", "Stats"])

# Load data
plays_df = read_plays_df()
all_combos_df = generate_all_combos()
coverage_df = compute_coverage(all_combos_df, plays_df)

# -------- Tab 1: Log a Play --------
with tabs[0]:
    st.subheader("Log a Play")

    col1, col2, col3 = st.columns(3)
    with col1:
        player_count = st.selectbox("Player Count", [2,3,4,5], index=2)
        ruleset_profile = st.selectbox("Ruleset Profile", RULESET_PROFILES, index=1)

    with col2:
        k = SUITS_REQUIRED[player_count]
        suits_used = st.multiselect(
            f"Non-Authority Suits Used (pick exactly {k})",
            options=SUITS,
            default=[],
        )
        if len(suits_used) != k:
            st.warning(f"Select exactly {k} suits for {player_count} players.")

    with col3:
        modules_on = st.multiselect("Modules Enabled", options=MODULES, default=["Heat/Disgrace","Safe","Specialists","Contingencies"])
        winner = st.text_input("Winner (optional)")
        notes = st.text_area("Notes (optional)", height=100)

    if st.button("Submit Play Log", type="primary"):
        if len(suits_used) != SUITS_REQUIRED[player_count]:
            st.error("Fix suit selection before submitting.")
        else:
            play = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "player_count": int(player_count),
                "ruleset_profile": ruleset_profile,
                "suits_used": canonical_suits_list(suits_used),
                "modules_on": sorted(modules_on),
                "winner": winner.strip(),
                "notes": notes.strip(),
            }
            append_play(play)
            st.success("Logged! Refreshing…")
            st.rerun()

    st.divider()
    st.subheader("Recent Plays")
    if plays_df.empty:
        st.info("No plays logged yet.")
    else:
        show = plays_df.tail(20).copy()
        st.dataframe(show, use_container_width=True)

# -------- Tab 2: Unplayed Combos --------
with tabs[1]:
    st.subheader("Unplayed Suit Combos")

    f1, f2, f3 = st.columns(3)
    with f1:
        pc_filter = st.multiselect("Filter Player Count", [2,3,4,5], default=[2,3,4,5])
    with f2:
        profile_filter = st.multiselect("Filter Ruleset Profile", RULESET_PROFILES, default=RULESET_PROFILES)
    with f3:
        contains_suit = st.selectbox("Must Include Suit (optional)", ["(none)"] + SUITS, index=0)

    filtered = coverage_df[
        coverage_df["player_count"].isin(pc_filter) &
        coverage_df["ruleset_profile"].isin(profile_filter)
    ].copy()

    if contains_suit != "(none)":
        filtered["has_suit"] = filtered["suits_used"].apply(lambda x: contains_suit in x)
        filtered = filtered[filtered["has_suit"]].drop(columns=["has_suit"])

    unplayed = filtered[filtered["played_count"] == 0].copy()
    st.write(f"Unplayed combos: **{len(unplayed)}**")

    # Suggest next: pick a random unplayed (or earliest alphabetical)
    if len(unplayed) > 0:
        st.markdown("**Suggested next play:**")
        suggestion = unplayed.sort_values(["player_count","ruleset_profile","combo_id"]).head(1).iloc[0]
        st.code(
            f'{suggestion["player_count"]}P | {suggestion["ruleset_profile"]} | Suits: {", ".join(suggestion["suits_used"])}',
            language="text"
        )

    st.dataframe(
        unplayed[["player_count","ruleset_profile","suits_used","combo_id"]].sort_values(
            ["player_count","ruleset_profile","combo_id"]
        ),
        use_container_width=True,
        height=520
    )

# -------- Tab 3: Stats --------
with tabs[2]:
    st.subheader("Coverage Stats")

    colA, colB = st.columns(2)

    with colA:
        st.markdown("**Coverage by Player Count**")
        cov_pc = coverage_df.groupby("player_count")["played_count"].apply(lambda s: (s > 0).mean()).reset_index()
        cov_pc.columns = ["player_count", "coverage_rate"]
        cov_pc["coverage_rate"] = (cov_pc["coverage_rate"] * 100).round(1).astype(str) + "%"
        st.dataframe(cov_pc, use_container_width=True)

    with colB:
        st.markdown("**Most Played Combos**")
        top = coverage_df.sort_values("played_count", ascending=False).head(15)
        st.dataframe(top[["player_count","ruleset_profile","suits_used","played_count","last_played_utc"]], use_container_width=True)

    st.divider()
    st.markdown("**Suit Appearance Frequency (from logged plays)**")
    if plays_df.empty:
        st.info("Log some plays to see suit frequency.")
    else:
        # explode suits_used_json
        suits_list = []
        for _, row in plays_df.iterrows():
            try:
                suits = json.loads(row["suits_used_json"])
                suits_list.extend(suits)
            except Exception:
                pass
        freq = pd.Series(suits_list).value_counts().reset_index()
        freq.columns = ["suit", "times_used"]
        st.dataframe(freq, use_container_width=True)
