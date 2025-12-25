import itertools
import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ============================================================
# The Job — Playtest Tracker (Google Sheets persistence)
# Backward compatible with older sheets (auto-add missing columns)
#
# Features:
# - No Ruleset Profile
# - Modules include Jobs + Special Suits
# - "First play?" checkbox
# - Player names + score inputs per player count
# - Unlimited suits selectable (including Authority)
# - Recommended coverage (ignores Authority by default)
# ============================================================

SUITS = [
    "Authority",
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

# Recommended suit counts by player count (NOT enforced).
# Coverage ignores Authority by default.
RECOMMENDED_SUITS = {2: 3, 3: 4, 4: 6, 5: 6}

MODULES = [
    "Wagering/Promises",   # core loop, but trackable
    "Jobs",
    "Heat/Disgrace",
    "Safe",
    "Specialists",
    "Contingencies",
    "Special Suits",
]

# Canonical sheet schema we want
SHEET_TITLE = "Plays"
SHEET_HEADERS = [
    "timestamp_utc",
    "player_count",
    "suits_used_json",
    "modules_on_json",
    "first_play",
    "players_json",
    "scores_json",
    "winner",
    "notes",
]


# ----------------------------
# Google Sheets helpers
# ----------------------------
def get_gsheet_client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)


def ensure_sheet_schema(ws):
    """
    Ensures row 1 has all SHEET_HEADERS.
    If the sheet already exists with fewer columns, we append missing headers.
    """
    current = ws.row_values(1)
    if not current:
        ws.append_row(SHEET_HEADERS)
        return

    # If headers differ/are missing, extend with missing ones
    missing = [h for h in SHEET_HEADERS if h not in current]
    if missing:
        # Add missing headers at the end of row 1
        new_headers = current + missing
        ws.update("A1", [new_headers])


def get_sheet():
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["SHEET_ID"])

    try:
        ws = sh.worksheet(SHEET_TITLE)
    except Exception:
        ws = sh.add_worksheet(title=SHEET_TITLE, rows=5000, cols=50)
        ws.append_row(SHEET_HEADERS)
        return ws

    ensure_sheet_schema(ws)
    return ws


def append_play(play: dict):
    ws = get_sheet()
    ws.append_row(
        [
            play.get("timestamp_utc", ""),
            play.get("player_count", ""),
            json.dumps(play.get("suits_used", []), ensure_ascii=False),
            json.dumps(play.get("modules_on", []), ensure_ascii=False),
            bool(play.get("first_play", False)),
            json.dumps(play.get("players", []), ensure_ascii=False),
            json.dumps(play.get("scores", []), ensure_ascii=False),
            play.get("winner", ""),
            play.get("notes", ""),
        ]
    )


def read_plays_df():
    ws = get_sheet()
    rows = ws.get_all_records()

    # Create empty df with expected columns
    if not rows:
        return pd.DataFrame(columns=SHEET_HEADERS)

    df = pd.DataFrame(rows)

    # Backfill any missing columns (older rows/sheets)
    for col in SHEET_HEADERS:
        if col not in df.columns:
            df[col] = "" if col.endswith("_json") or col in ["winner", "notes", "timestamp_utc"] else False

    # Normalize types
    df["player_count"] = pd.to_numeric(df["player_count"], errors="coerce").astype("Int64")

    # first_play might be stored as TRUE/FALSE, True/False, or blank
    def to_bool(x):
        if isinstance(x, bool):
            return x
        s = str(x).strip().lower()
        return s in ["true", "1", "yes", "y"]

    df["first_play"] = df["first_play"].apply(to_bool)

    return df


# ----------------------------
# JSON decode helpers
# ----------------------------
def canonical_list(items):
    return sorted([str(x).strip() for x in items if str(x).strip()], key=lambda s: s.lower())


def decode_json_list(val):
    if isinstance(val, list):
        return val
    if not isinstance(val, str) or not val.strip():
        return []
    try:
        out = json.loads(val)
        return out if isinstance(out, list) else []
    except Exception:
        return []


# ----------------------------
# Combo + coverage helpers
# ----------------------------
def density_label(player_count: int, suit_count: int) -> str:
    rec = RECOMMENDED_SUITS.get(int(player_count), None)
    if rec is None:
        return "Unknown"
    diff = suit_count - rec
    if diff == 0:
        return "Recommended"
    if diff > 0:
        return f"Over (+{diff})"
    return f"Under ({diff})"


def combo_id(player_count: int, suits_used: list[str]) -> str:
    suits_key = "|".join(canonical_list(suits_used))
    return f"{player_count}P::{suits_key}"


def generate_recommended_combos() -> pd.DataFrame:
    non_authority = [s for s in SUITS if s != "Authority"]
    rows = []
    for pc, k in RECOMMENDED_SUITS.items():
        for suit_set in itertools.combinations(non_authority, k):
            suits_used = canonical_list(list(suit_set))
            rows.append(
                {
                    "combo_id": combo_id(pc, suits_used),
                    "player_count": pc,
                    "suits_used": suits_used,
                    "recommended_suit_count": k,
                }
            )
    return pd.DataFrame(rows)


def compute_coverage(recommended_df: pd.DataFrame, plays_df: pd.DataFrame) -> pd.DataFrame:
    out = recommended_df.copy()
    if plays_df.empty:
        out["played_count"] = 0
        out["last_played_utc"] = ""
        return out

    df = plays_df.copy()
    df["suits_used"] = df["suits_used_json"].apply(decode_json_list).apply(canonical_list)

    # Ignore Authority for coverage matching
    df["suits_used_no_authority"] = df["suits_used"].apply(lambda xs: [x for x in xs if x != "Authority"])
    df["combo_id"] = df.apply(
        lambda r: combo_id(int(r["player_count"]), r["suits_used_no_authority"])
        if pd.notna(r["player_count"])
        else None,
        axis=1,
    )

    counts = df.groupby("combo_id").size().rename("played_count")
    last_play = df.groupby("combo_id")["timestamp_utc"].max().rename("last_played_utc")

    out = out.merge(counts, on="combo_id", how="left").merge(last_play, on="combo_id", how="left")
    out["played_count"] = out["played_count"].fillna(0).astype(int)
    out["last_played_utc"] = out["last_played_utc"].fillna("")
    return out


def compute_observed_combos(plays_df: pd.DataFrame) -> pd.DataFrame:
    if plays_df.empty:
        return pd.DataFrame(
            columns=[
                "combo_id",
                "player_count",
                "suits_used",
                "played_count",
                "last_played_utc",
                "suit_count",
                "density",
                "has_authority",
            ]
        )

    df = plays_df.copy()
    df["suits_used"] = df["suits_used_json"].apply(decode_json_list).apply(canonical_list)
    df["suit_count"] = df["suits_used"].apply(len)
    df["has_authority"] = df["suits_used"].apply(lambda xs: "Authority" in xs)
    df["density"] = df.apply(
        lambda r: density_label(int(r["player_count"]), int(r["suit_count"])) if pd.notna(r["player_count"]) else "Unknown",
        axis=1,
    )
    df["combo_id"] = df.apply(
        lambda r: combo_id(int(r["player_count"]), r["suits_used"])
        if pd.notna(r["player_count"])
        else None,
        axis=1,
    )

    grp = (
        df.groupby(["combo_id", "player_count"], dropna=True)
        .agg(
            played_count=("combo_id", "size"),
            last_played_utc=("timestamp_utc", "max"),
            suits_used=("suits_used", "first"),
            suit_count=("suit_count", "first"),
            density=("density", "first"),
            has_authority=("has_authority", "first"),
        )
        .reset_index()
    )
    return grp.sort_values(["player_count", "played_count"], ascending=[True, False])


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="The Job Playtest Tracker", layout="wide")
st.title("The Job — Playtest Tracker")
st.caption("Log plays with any modules and any suit counts (including Authority).")

tabs = st.tabs(["Log a Play", "Unplayed (Recommended) Combos", "Stats"])

plays_df = read_plays_df()
recommended_df = generate_recommended_combos()
coverage_df = compute_coverage(recommended_df, plays_df)
observed_df = compute_observed_combos(plays_df)

# -------- Tab 1 --------
with tabs[0]:
    st.subheader("Log a Play (No Limits)")

    col1, col2, col3 = st.columns(3)

    with col1:
        player_count = st.selectbox("Player Count", [2, 3, 4, 5], index=1)
        rec = RECOMMENDED_SUITS.get(int(player_count))
        st.caption(f"Recommendation for {player_count} players: **{rec}** suits (not enforced).")

        first_play = st.checkbox("First play? (first time this group played The Job)", value=False)

        st.markdown("**Players**")
        players = []
        for i in range(int(player_count)):
            players.append(st.text_input(f"Player {i+1} name", key=f"pname_{i}").strip())

        st.markdown("**Scores (Reputation)**")
        scores = []
        for i in range(int(player_count)):
            label = players[i] if players[i] else f"Player {i+1}"
            scores.append(st.number_input(f"{label} score", value=0, step=1, key=f"pscore_{i}"))

    with col2:
        suits_used = st.multiselect("Suits Used (pick any amount)", options=SUITS, default=[])
        st.caption(f"Selected: **{len(suits_used)}** suits • Density tag: **{density_label(player_count, len(suits_used))}**")
        st.caption("Authority included." if "Authority" in suits_used else "Authority not included.")

    with col3:
        modules_on = st.multiselect(
            "Modules Enabled",
            options=MODULES,
            default=["Wagering/Promises", "Jobs", "Heat/Disgrace", "Safe", "Specialists", "Contingencies"],
        )

        winner_options = ["(none)"] + [p for p in players if p]
        winner_sel = st.selectbox("Winner (optional)", winner_options, index=0)
        notes = st.text_area("Notes (optional)", height=160)

    if st.button("Submit Play Log", type="primary"):
        cleaned_players = [p if p else f"Player {i+1}" for i, p in enumerate(players)]
        cleaned_scores = [int(s) for s in scores]

        play = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "player_count": int(player_count),
            "suits_used": canonical_list(suits_used),
            "modules_on": sorted(modules_on),
            "first_play": bool(first_play),
            "players": cleaned_players,
            "scores": cleaned_scores,
            "winner": "" if winner_sel == "(none)" else winner_sel,
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
        show = plays_df.copy()
        show["suits_used"] = show["suits_used_json"].apply(decode_json_list).apply(canonical_list)
        show["modules_on"] = show["modules_on_json"].apply(decode_json_list)
        show["players"] = show["players_json"].apply(decode_json_list)
        show["scores"] = show["scores_json"].apply(decode_json_list)
        show["suit_count"] = show["suits_used"].apply(len)
        show["has_authority"] = show["suits_used"].apply(lambda xs: "Authority" in xs)
        show["density"] = show.apply(
            lambda r: density_label(int(r["player_count"]), int(r["suit_count"])) if pd.notna(r["player_count"]) else "Unknown",
            axis=1,
        )

        cols = [
            "timestamp_utc",
            "player_count",
            "first_play",
            "suit_count",
            "density",
            "has_authority",
            "suits_used",
            "modules_on",
            "players",
            "scores",
            "winner",
            "notes",
        ]
        st.dataframe(show[cols].tail(25), use_container_width=True)

# -------- Tab 2 --------
with tabs[1]:
    st.subheader("Unplayed Combos (Recommended suit counts only)")
    st.caption("Coverage ignores Authority, so Authority-on games can still fill coverage for a recommended suit mix.")

    f1, f2, f3 = st.columns(3)
    with f1:
        pc_filter = st.multiselect("Filter Player Count", [2, 3, 4, 5], default=[2, 3, 4, 5])
    with f2:
        contains_suit = st.selectbox("Must Include Suit (optional)", ["(none)"] + [s for s in SUITS if s != "Authority"], index=0)
    with f3:
        show_played_too = st.checkbox("Show played combos too", value=False)

    filtered = coverage_df[coverage_df["player_count"].isin(pc_filter)].copy()
    if contains_suit != "(none)":
        filtered = filtered[filtered["suits_used"].apply(lambda xs: contains_suit in xs)]
    if not show_played_too:
        filtered = filtered[filtered["played_count"] == 0]

    st.write(f"Combos shown: **{len(filtered)}**")

    if len(filtered) > 0 and not show_played_too:
        suggestion = filtered.sort_values(["player_count", "combo_id"]).head(1).iloc[0]
        st.markdown("**Suggested next (recommended) play:**")
        st.code(f'{suggestion["player_count"]}P | Non-Authority suits: {", ".join(suggestion["suits_used"])}', language="text")

    st.dataframe(
        filtered[["player_count", "suits_used", "played_count", "last_played_utc", "combo_id"]].sort_values(
            ["player_count", "played_count", "combo_id"], ascending=[True, True, True]
        ),
        use_container_width=True,
        height=560,
    )

# -------- Tab 3 --------
with tabs[2]:
    st.subheader("Stats")

    if plays_df.empty:
        st.info("Log some plays to see stats.")
    else:
        df = plays_df.copy()
        df["suits_used"] = df["suits_used_json"].apply(decode_json_list).apply(canonical_list)
        df["modules_on"] = df["modules_on_json"].apply(decode_json_list)
        df["players"] = df["players_json"].apply(decode_json_list)
        df["scores"] = df["scores_json"].apply(decode_json_list)
        df["suit_count"] = df["suits_used"].apply(len)
        df["has_authority"] = df["suits_used"].apply(lambda xs: "Authority" in xs)
        df["density"] = df.apply(
            lambda r: density_label(int(r["player_count"]), int(r["suit_count"])) if pd.notna(r["player_count"]) else "Unknown",
            axis=1,
        )

        colA, colB = st.columns(2)

        with colA:
            st.markdown("**Suit count distribution**")
            dist = df.groupby(["player_count", "suit_count"]).size().reset_index(name="plays")
            st.dataframe(dist.sort_values(["player_count", "suit_count"]), use_container_width=True)

            st.markdown("**First-play rate**")
            fp = df.groupby("player_count")["first_play"].mean().reset_index()
            fp["first_play_rate"] = (fp["first_play"] * 100).round(1).astype(str) + "%"
            st.dataframe(fp[["player_count", "first_play_rate"]], use_container_width=True)

        with colB:
            st.markdown("**Observed combos (any suit counts, Authority on/off)**")
            st.dataframe(
                observed_df[
                    ["player_count", "suit_count", "density", "has_authority", "suits_used", "played_count", "last_played_utc"]
                ].head(40),
                use_container_width=True,
            )

        st.divider()
        st.markdown("**Recommended coverage by player count**")
        cov_pc = coverage_df.groupby("player_count")["played_count"].apply(lambda s: (s > 0).mean()).reset_index()
        cov_pc.columns = ["player_count", "recommended_coverage_rate"]
        cov_pc["recommended_coverage_rate"] = (cov_pc["recommended_coverage_rate"] * 100).round(1).astype(str) + "%"
        st.dataframe(cov_pc, use_container_width=True)

        st.divider()
        st.markdown("**Suit appearance frequency**")
        suits_flat = []
        for xs in df["suits_used"].tolist():
            suits_flat.extend(xs)
        freq = pd.Series(suits_flat).value_counts().reset_index()
        freq.columns = ["suit", "times_used"]
        st.dataframe(freq, use_container_width=True)

        st.divider()
        st.markdown("**Module usage frequency**")
        mods_flat = []
        for xs in df["modules_on"].tolist():
            mods_flat.extend(xs)
        mf = pd.Series(mods_flat).value_counts().reset_index()
        mf.columns = ["module", "times_used"]
        st.dataframe(mf, use_container_width=True)
