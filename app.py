import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ============================================================
# The Job — Playtest Tracker (NUCLEAR OPTION: NO FORMS)
# Guaranteed fix for: "This form has no submit button"
# - Uses NO st.form() anywhere
# - Uses a normal st.button() to submit
# - Unlimited suits selectable (including Authority)
# - Modules include Jobs
# - First play checkbox
# - Player names + per-player scores
# - Recent plays + basic stats
# ============================================================

# ---------- CONFIG ----------
st.set_page_config(page_title="The Job Playtest Tracker", layout="wide")

# ---------- CONSTANTS ----------
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

MODULES = [
    "Wagering/Promises",
    "Jobs",
    "Heat/Disgrace",
    "Safe",
    "Specialists",
    "Contingencies",
    "Special Suits",
]

RECOMMENDED_SUITS = {2: 3, 3: 4, 4: 6, 5: 6}

# ---------- HELPERS ----------
def density_label(player_count: int, suit_count: int) -> str:
    rec = RECOMMENDED_SUITS.get(int(player_count))
    if not rec:
        return "Unknown"
    if suit_count < rec:
        return f"Thin (under {rec})"
    if suit_count == rec:
        return "Recommended"
    return f"Dense (over {rec})"


def safe_str_list(xs):
    return sorted([str(x).strip() for x in xs if str(x).strip()], key=lambda s: s.lower())


# ---------- STATE ----------
if "plays" not in st.session_state:
    st.session_state.plays = []

# Used to force-clear widget state after submit
if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0


def key(name: str) -> str:
    """Namespaced keys so we can reset everything by changing reset_nonce."""
    return f"{name}__{st.session_state.reset_nonce}"


# ---------- HEADER ----------
st.title("The Job — Playtest Tracker")
st.caption(
    "Log playtests with any suits and any modules. This version uses no forms (guaranteed submit-button fix)."
)

tabs = st.tabs(["Log a Play", "Recent Plays", "Stats"])

# ============================================================
# TAB 0 — LOG A PLAY (NO FORM)
# ============================================================
with tabs[0]:
    st.subheader("Log a Play (No Limits)")

    col1, col2, col3 = st.columns(3)

    # ---------- COLUMN 1 ----------
    with col1:
        player_count = st.selectbox("Player Count", [2, 3, 4, 5], index=1, key=key("player_count"))

        rec = RECOMMENDED_SUITS.get(int(player_count))
        st.caption(f"Suggested testing target: **{rec}** suits (not enforced).")

        first_play = st.checkbox(
            "First play? (first time this group played The Job)",
            value=False,
            key=key("first_play"),
        )

        st.markdown("**Players**")
        players = []
        for i in range(int(player_count)):
            players.append(st.text_input(f"Player {i+1} name", key=key(f"pname_{i}")))

        st.markdown("**Scores (Reputation)**")
        scores = []
        for i in range(int(player_count)):
            label = players[i].strip() if players[i].strip() else f"Player {i+1}"
            scores.append(st.number_input(f"{label} score", value=0, step=1, key=key(f"pscore_{i}")))

    # ---------- COLUMN 2 ----------
    with col2:
        suits_used = st.multiselect("Suits Used (pick any amount)", options=SUITS, default=[], key=key("suits_used"))
        st.caption(f"Selected: **{len(suits_used)}** suits • Density: **{density_label(int(player_count), len(suits_used))}**")
        st.caption("Authority included." if "Authority" in suits_used else "Authority not included.")

    # ---------- COLUMN 3 ----------
    with col3:
        modules_on = st.multiselect(
            "Modules Enabled",
            options=MODULES,
            default=["Wagering/Promises", "Jobs", "Heat/Disgrace", "Safe", "Specialists", "Contingencies"],
            key=key("modules_on"),
        )
        winner = st.text_input("Winner (optional)", key=key("winner"))
        notes = st.text_area("Notes (optional)", height=160, key=key("notes"))

    st.divider()

    # ---------- SUBMIT ----------
    if st.button("Submit Play Log", type="primary", key=key("submit")):
        cleaned_players = [
            (p.strip() if p.strip() else f"Player {i+1}") for i, p in enumerate(players)
        ]
        cleaned_scores = [int(s) for s in scores]

        play = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "player_count": int(player_count),
            "first_play": bool(first_play),
            "suits_used": safe_str_list(suits_used),
            "modules_on": safe_str_list(modules_on),
            "players": cleaned_players,
            "scores": cleaned_scores,
            "winner": winner.strip(),
            "notes": notes.strip(),
        }

        st.session_state.plays.append(play)
        st.success("Play logged! Clearing inputs…")

        # Clear inputs by changing key namespace and rerunning
        st.session_state.reset_nonce += 1
        st.rerun()

# ============================================================
# TAB 1 — RECENT PLAYS
# ============================================================
with tabs[1]:
    st.subheader("Recent Plays")

    if not st.session_state.plays:
        st.info("No plays logged yet.")
    else:
        df = pd.DataFrame(st.session_state.plays)
        df["suit_count"] = df["suits_used"].apply(lambda xs: len(xs) if isinstance(xs, list) else 0)
        df["has_authority"] = df["suits_used"].apply(lambda xs: "Authority" in xs if isinstance(xs, list) else False)
        df["density"] = df.apply(lambda r: density_label(int(r["player_count"]), int(r["suit_count"])), axis=1)

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
        st.dataframe(df[cols].tail(50), use_container_width=True)

# ============================================================
# TAB 2 — STATS
# ============================================================
with tabs[2]:
    st.subheader("Stats")

    if not st.session_state.plays:
        st.info("Log some plays to see stats.")
    else:
        df = pd.DataFrame(st.session_state.plays)

        st.metric("Total Plays Logged", len(df))

        # Unique suit sets
        suit_sets = df["suits_used"].apply(lambda xs: tuple(xs) if isinstance(xs, list) else tuple())
        st.metric("Unique Suit Sets Played", suit_sets.nunique())

        st.divider()

        # Suit frequency
        st.markdown("### Suit Usage Frequency")
        suit_counts = {}
        for xs in df["suits_used"]:
            if not isinstance(xs, list):
                continue
            for s in xs:
                suit_counts[s] = suit_counts.get(s, 0) + 1
        if suit_counts:
            suit_series = pd.Series(suit_counts).sort_values(ascending=False)
            st.bar_chart(suit_series)
        else:
            st.info("No suit data yet.")

        st.divider()

        # Module frequency
        st.markdown("### Module Usage Frequency")
        mod_counts = {}
        for xs in df["modules_on"]:
            if not isinstance(xs, list):
                continue
            for m in xs:
                mod_counts[m] = mod_counts.get(m, 0) + 1
        if mod_counts:
            mod_series = pd.Series(mod_counts).sort_values(ascending=False)
            st.bar_chart(mod_series)
        else:
            st.info("No module data yet.")

        st.divider()

        # Player count distribution
        st.markdown("### Player Count Distribution")
        pc = df["player_count"].value_counts().sort_index()
        st.bar_chart(pc)
