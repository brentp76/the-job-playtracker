import itertools
import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ============================================================
# The Job — Playtest Tracker (Google Sheets persistence)
# - Allows ANY number of suits (including Authority)
# - Logs plays to Google Sheets
# - Shows "recommended coverage" separately (Authority ignored for coverage)
# ============================================================

# ----------------------------
# SUITS (Selectable in the app)
# ----------------------------
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
# Note: These are interpreted as recommended TOTAL suits selected in the app.
# If you'd rather treat these as "non-Authority suits" only, tell me and I’ll adjust.
RECOMMENDED_SUITS = {
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
    import gspread
    from google.oauth2.service_account import Credentials

    # Streamlit secrets must include:
    # SHEET_ID="..."
    # [gcp_service_account] ... service account fields ...
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

    try:
        ws = sh.worksheet("Plays")
    except Exception:
        ws = sh.add_worksheet(title="Plays", rows=2000, cols=30)
        ws.append_row(
            [
                "timestamp_utc",
                "player_count",
                "ruleset_profile",
                "suits_used_json",
                "modules_on_json",
                "winner",
                "notes",
            ]
        )
    return ws


def read_plays_df():
    ws = get_sheet()
    rows = ws.get_all_records()
    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "player_count",
                "ruleset_profile",
                "suits_used_json",
                "modules_on_json",
                "winner",
                "notes",
            ]
        )
    df = pd.DataFrame(rows)
    if "player_count" in df.columns:
        df["player_count"] = pd.to_numeric(df["player_count"], errors="coerce").astype("Int64")
    return df


def append_play(play: dict):
    ws = get_sheet()
    ws.append_row(
        [
            play["timestamp_utc"],
            play["player_count"],
            play["ruleset_profile"],
            json.dumps(play["suits_used"], ensure_ascii=False),
            json.dumps(play["modules_on"], ensure_ascii=False),
            play.get("winner", ""),
            play.get("notes", ""),
        ]
    )


# ----------------------------
# HELPERS
# ----------------------------
def canonical_suits_list(suits: list[str]) -> list[str]:
    return sorted([s.strip() for s in suits if str(s).strip()], key=lambda x: x.lower())


def combo_id(player_count: int, ruleset_profile: str, suits_used: list[str]) -> str:
    suits_key = "|".join(canonical_suits_list(suits_used))
    return f"{player_count}P::{ruleset_profile}::{suits_key}"


def decode_json_list(val):
    if not isinstance(val, str) or not val.strip():
        return []
    try:
        out = json.loads(val)
        return out if isinstance(out, list) else []
    except Exception:
        return []


def density_label(player_count: int, suit_count: int) -> str:
    rec = RECOMMENDED_SUITS.get(int(player_count), None)
    if rec is None:
        return "Unknown"
    diff = suit_count - rec
    if diff == 0:
        return "Recommended"
    if diff > 0:
        return f"Over (+{diff})"
    return f"Under ({diff})"  # diff is negative


# ----------------------------
# RECOMMENDED COMBO GENERATION (Coverage)
# We compute coverage on "recommended suit count" combos.
# IMPORTANT: For coverage, Authority is ignored by default.
# That way:
#   - Recommended combos represent your modular mix, regardless of Authority on/off.
#   - Plays that include Authority still count if the non-Authority portion matches.
# If you want Authority included in coverage, I can change one line.
# ----------------------------
def generate_recommended_combos():
    non_authority_suits = [s for s in SUITS if s != "Authority"]

    combos = []
    for pc, k in RECOMMENDED_SUITS.items():
        for suit_set in itertools.combinations(non_authority_suits, k):
            suits_used = canonical_suits_list(list(suit_set))
            for profile in RULESET_PROFILES:
                combos.append(
                    {
                        "combo_id": combo_id(pc, profile, suits_used),
                        "player_count": pc,
                        "ruleset_profile": profile,
                        "suits_used": suits_used,
                        "recommended_suit_count": k,
                    }
                )
    return pd.DataFrame(combos)


def compute_coverage(recommended_combos_df: pd.DataFrame, plays_df: pd.DataFrame) -> pd.DataFrame:
    if plays_df.empty:
        recommended_combos_df["played_count"] = 0
        recommended_combos_df["last_played_utc"] = ""
        return recommended_combos_df

    plays_df = plays_df.copy()
    plays_df["suits_used"] = plays_df["suits_used_json"].apply(decode_json_list).apply(canonical_suits_list)

    # For coverage matching, we ignore Authority
    plays_df["suits_used_no_authority"] = plays_df["suits_used"].apply(lambda xs: [x for x in xs if x != "Authority"])

    def play_to_combo_id(row):
        if pd.isna(row["player_count"]) or not row["ruleset_profile"]:
            return None
        return combo_id(int(row["player_count"]), str(row["ruleset_profile"]), row["suits_used_no_authority"])

    plays_df["combo_id"] = plays_df.apply(play_to_combo_id, axis=1)

    counts = plays_df.groupby("combo_id").size().rename("played_count")
    last_play = plays_df.groupby("combo_id")["timestamp_utc"].max().rename("last_played_utc")

    out = (
        recommended_combos_df.merge(counts, on="combo_id", how="left")
        .merge(last_play, on="combo_id", how="left")
    )
    out["played_count"] = out["played_count"].fillna(0).astype(int)
    out["last_played_utc"] = out["last_played_utc"].fillna("")
    return out


def compute_observed_combos(plays_df: pd.DataFrame) -> pd.DataFrame:
    """All combos actually played (including any suit counts and Authority on/off)."""
    if plays_df.empty:
        return pd.DataFrame(
            columns=[
                "combo_id",
                "player_count",
                "ruleset_profile",
                "suits_used",
                "played_count",
                "last_played_utc",
                "suit_count",
                "density",
                "has_authority",
            ]
        )

    df = plays_df.copy()
    df["suits_used"] = df["suits_used_json"].apply(decode_json_list).apply(canonical_suits_list)
    df["suit_count"] = df["suits_used"].apply(len)
    df["has_authority"] = df["suits_used"].apply(lambda xs: "Authority" in xs)
    df["density"] = df.apply(
        lambda r: density_label(int(r["player_count"]), int(r["suit_count"])) if pd.notna(r["player_count"]) else "Unknown",
        axis=1,
    )
    df["combo_id"] = df.apply(
        lambda r: combo_id(int(r["player_count"]), str(r["ruleset_profile"]), r["suits_used"])
        if pd.notna(r["player_count"])
        else None,
        axis=1,
    )

    grp = (
        df.groupby(["combo_id", "player_count", "ruleset_profile"], dropna=True)
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
    return grp.sort_values(["player_count", "ruleset_profile", "played_count"], ascending=[True, True, False])


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="The Job Playtest Tracker", layout="wide")

st.title("The Job — Playtest Tracker")
st.caption("Log plays with any modules and any suit counts (including Authority).")

tabs = st.tabs(["Log a Play", "Unplayed (Recommended) Combos", "Stats"])

# Load data
plays_df = read_plays_df()
recommended_combos_df = generate_recommended_combos()
coverage_df = compute_coverage(recommended_combos_df, plays_df)
observed_df = compute_observed_combos(plays_df)

# -------- Tab 1: Log a Play --------
with tabs[0]:
    st.subheader("Log a Play (No Limits)")

    col1, col2, col3 = st.columns(3)

    with col1:
        player_count = st.selectbox("Player Count", [2, 3, 4, 5], index=1)
        ruleset_profile = st.selectbox("Ruleset Profile", RULESET_PROFILES, index=1)

        rec = RECOMMENDED_SUITS.get(int(player_count))
        st.caption(f"Recommendation for {player_count} players: **{rec}** suits (not enforced).")

    with col2:
        suits_used = st.multiselect(
            "Suits Used (pick any amount)",
            options=SUITS,
            default=[],
        )
        st.caption(f"Selected: **{len(suits_used)}** suits • Density tag: **{density_label(player_count, len(suits_used))}**")

        if "Authority" in suits_used:
            st.caption("Authority included (dominant suit active unless disabled by a Job).")
        else:
            st.caption("Authority not included (no dominant suit unless created by effects).")

    with col3:
        modules_on = st.multiselect(
            "Modules Enabled",
            options=MODULES,
            default=["Heat/Disgrace", "Safe", "Specialists", "Contingencies"],
        )
        winner = st.text_input("Winner (optional)")
        notes = st.text_area("Notes (optional)", height=100)

    if st.button("Submit Play Log", type="primary"):
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
        show = plays_df.copy()
        show["suits_used"] = show["suits_used_json"].apply(decode_json_list).apply(canonical_suits_list)
        show["suit_count"] = show["suits_used"].apply(len)
        show["has_authority"] = show["suits_used"].apply(lambda xs: "Authority" in xs)
        show["density"] = show.apply(
            lambda r: density_label(int(r["player_count"]), int(r["suit_count"])) if pd.notna(r["player_count"]) else "Unknown",
            axis=1,
        )
        show = show[
            [
                "timestamp_utc",
                "player_count",
                "ruleset_profile",
                "suit_count",
                "density",
                "has_authority",
                "suits_used",
                "modules_on_json",
                "winner",
                "notes",
            ]
        ].tail(25)
        st.dataframe(show, use_container_width=True)

# -------- Tab 2: Unplayed Recommended Combos --------
with tabs[1]:
    st.subheader("Unplayed Combos (Recommended suit counts only)")
    st.caption(
        "This view is your gap list against the recommended chart. "
        "Coverage matching ignores Authority by default, so Authority-on games can still fill coverage."
    )

    f1, f2, f3 = st.columns(3)
    with f1:
        pc_filter = st.multiselect("Filter Player Count", [2, 3, 4, 5], default=[2, 3, 4, 5])
    with f2:
        profile_filter = st.multiselect("Filter Ruleset Profile", RULESET_PROFILES, default=RULESET_PROFILES)
    with f3:
        contains_suit = st.selectbox("Must Include Suit (optional)", ["(none)"] + [s for s in SUITS if s != "Authority"], index=0)

    filtered = coverage_df[
        coverage_df["player_count"].isin(pc_filter) & coverage_df["ruleset_profile"].isin(profile_filter)
    ].copy()

    if contains_suit != "(none)":
        filtered["has_suit"] = filtered["suits_used"].apply(lambda x: contains_suit in x)
        filtered = filtered[filtered["has_suit"]].drop(columns=["has_suit"])

    unplayed = filtered[filtered["played_count"] == 0].copy()
    st.write(f"Unplayed recommended combos: **{len(unplayed)}**")

    if len(unplayed) > 0:
        st.markdown("**Suggested next (recommended) play:**")
        suggestion = unplayed.sort_values(["player_count", "ruleset_profile", "combo_id"]).head(1).iloc[0]
        st.code(
            f'{suggestion["player_count"]}P | {suggestion["ruleset_profile"]} | Non-Authority suits: {", ".join(suggestion["suits_used"])}',
            language="text",
        )

    st.dataframe(
        unplayed[["player_count", "ruleset_profile", "suits_used", "combo_id"]].sort_values(
            ["player_count", "ruleset_profile", "combo_id"]
        ),
        use_container_width=True,
        height=520,
    )

# -------- Tab 3: Stats --------
with tabs[2]:
    st.subheader("Stats")

    colA, colB = st.columns(2)

    with colA:
        st.markdown("**Observed Suit Count Distribution (what people actually played)**")
        if plays_df.empty:
            st.info("Log some plays to see this.")
        else:
            tmp = plays_df.copy()
            tmp["suits_used"] = tmp["suits_used_json"].apply(decode_json_list)
            tmp["suit_count"] = tmp["suits_used"].apply(len)
            dist = tmp.groupby(["player_count", "suit_count"]).size().reset_index(name="plays")
            st.dataframe(dist.sort_values(["player_count", "suit_count"]), use_container_width=True)

    with colB:
        st.markdown("**Observed Combos (including any suit counts and Authority on/off)**")
        if observed_df.empty:
            st.info("No plays logged yet.")
        else:
            st.dataframe(
                observed_df[
                    [
                        "player_count",
                        "ruleset_profile",
                        "suit_count",
                        "density",
                        "has_authority",
                        "suits_used",
                        "played_count",
                        "last_played_utc",
                    ]
                ].head(30),
                use_container_width=True,
            )

    st.divider()
    st.markdown("**Recommended Coverage by Player Count**")
    cov_pc = coverage_df.groupby("player_count")["played_count"].apply(lambda s: (s > 0).mean()).reset_index()
    cov_pc.columns = ["player_count", "recommended_coverage_rate"]
    cov_pc["recommended_coverage_rate"] = (cov_pc["recommended_coverage_rate"] * 100).round(1).astype(str) + "%"
    st.dataframe(cov_pc, use_container_width=True)

    st.divider()
    st.markdown("**Suit Appearance Frequency (from logged plays)**")
    if plays_df.empty:
        st.info("Log some plays to see suit frequency.")
    else:
        suits_list = []
        for _, row in plays_df.iterrows():
            suits_list.extend(decode_json_list(row.get("suits_used_json", "")))
        freq = pd.Series(suits_list).value_counts().reset_index()
        freq.columns = ["suit", "times_used"]
        st.dataframe(freq, use_container_width=True)
