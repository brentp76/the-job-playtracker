import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ============================================================
# The Job — Playtest Tracker (LOCAL MEMORY VERSION)
# ============================================================

# ---------- CONFIG ----------
st.set_page_config(
    page_title="The Job Playtest Tracker",
    layout="wide",
)

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
]

RECOMMENDED_SUITS = {2: 3, 3: 4, 4: 6, 5: 6}

# ---------- HELPERS ----------
def density_label(player_count, suit_count):
    rec = RECOMMENDED_SUITS.get(player_count)
    if not rec:
        return "Unknown"
    if suit_count < rec:
        return "Thin"
    if suit_count == rec:
        return "Recommended"
    return "Dense"


# ---------- STATE ----------
if "plays" not in st.session_state:
    st.session_state.plays = []

if "form_key" not in st.session_state:
    st.session_state.form_key = 0


# ---------- HEADER ----------
st.title("The Job — Playtest Tracker")
st.caption(
    "Log playtests with any combination of suits and modules. "
    "Track what has been tested and what still needs coverage."
)

# ---------- TABS ----------
tabs = st.tabs(
    [
        "Log a Play",
        "Recent Plays",
        "Stats",
    ]
)

# ============================================================
# TAB 0 — LOG A PLAY
# ============================================================
with tabs[0]:
    st.subheader("Log a Play (No Limits)")

    submitted = False

    with st.form(
        key=f"log_form_{st.session_state.form_key}",
        clear_on_submit=True,
    ):
        col1, col2, col3 = st.columns(3)

        # ---------- COLUMN 1 ----------
        with col1:
            player_count = st.selectbox("Player Count", [2, 3, 4, 5], index=1)
            rec = RECOMMENDED_SUITS.get(player_count)
            st.caption(
                f"Suggested testing target: **{rec}** suits (not enforced)."
            )

            first_play = st.checkbox(
                "First play? (first time this group played The Job)",
                value=False,
            )

            st.markdown("**Players**")
            players = []
            for i in range(player_count):
                players.append(
                    st.text_input(f"Player {i+1} name")
                )

            st.markdown("**Scores (Reputation)**")
            scores = []
            for i in range(player_count):
                label = players[i] if players[i] else f"Player {i+1}"
                scores.append(
                    st.number_input(
                        f"{label} score",
                        value=0,
                        step=1,
                    )
                )

        # ---------- COLUMN 2 ----------
        with col2:
            suits_used = st.multiselect(
                "Suits Used (pick any amount)",
                options=SUITS,
                default=[],
            )

            st.caption(
                f"Selected: **{len(suits_used)}** suits • "
                f"Density: **{density_label(player_count, len(suits_used))}**"
            )

            st.caption(
                "Authority included."
                if "Authority" in suits_used
                else "Authority not included."
            )

        # ---------- COLUMN 3 ----------
        with col3:
            modules_on = st.multiselect(
                "Modules Enabled",
                options=MODULES,
                default=MODULES,
            )

            winner = st.text_input("Winner (optional)")
            notes = st.text_area(
                "Notes (optional)",
                height=160,
            )

        submitted = st.form_submit_button("Submit Play Log")

    if submitted:
        cleaned_players = [
            p.strip() if p.strip() else f"Player {i+1}"
            for i, p in enumerate(players)
        ]
        cleaned_scores = [int(s) for s in scores]

        play = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "player_count": player_count,
            "first_play": first_play,
            "suits_used": sorted(suits_used),
            "modules_on": sorted(modules_on),
            "players": cleaned_players,
            "scores": cleaned_scores,
            "winner": winner.strip(),
            "notes": notes.strip(),
        }

        st.session_state.plays.append(play)

        st.success("Play logged.")
        st.session_state.form_key += 1
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
        df["suit_count"] = df["suits_used"].apply(len)
        df["has_authority"] = df["suits_used"].apply(
            lambda xs: "Authority" in xs
        )
        df["density"] = df.apply(
            lambda r: density_label(r["player_count"], r["suit_count"]),
            axis=1,
        )

        st.dataframe(
            df[
                [
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
            ].tail(25),
            use_container_width=True,
        )


# ============================================================
# TAB 2 — STATS
# ============================================================
with tabs[2]:
    st.subheader("Stats")

    if not st.session_state.plays:
        st.info("No data yet.")
    else:
        df = pd.DataFrame(st.session_state.plays)

        st.metric("Total Plays Logged", len(df))
        st.metric(
            "Unique Suit Sets",
            df["suits_used"].astype(str).nunique(),
        )

        st.markdown("**Most Used Suits**")
        suit_counts = {}
        for suits in df["suits_used"]:
            for s in suits:
                suit_counts[s] = suit_counts.get(s, 0) + 1

        st.bar_chart(pd.Series(suit_counts).sort_values(ascending=False))
