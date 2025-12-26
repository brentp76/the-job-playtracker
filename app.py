with tabs[0]:
    st.subheader("Log a Play (No Limits)")

    # Form reset key
    if "form_key" not in st.session_state:
        st.session_state.form_key = 0

    with st.form(key=f"log_form_{st.session_state.form_key}", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            player_count = st.selectbox("Player Count", [2, 3, 4, 5], index=1)
            rec = RECOMMENDED_SUITS.get(int(player_count))
            st.caption(f"Recommendation for {player_count} players: **{rec}** suits (not enforced).")

            first_play = st.checkbox("First play? (first time this group played The Job)", value=False)

            st.markdown("**Players**")
            players = []
            for i in range(int(player_count)):
                players.append(st.text_input(f"Player {i+1} name").strip())

            st.markdown("**Scores (Reputation)**")
            scores = []
            for i in range(int(player_count)):
                label = players[i] if players[i] else f"Player {i+1}"
                scores.append(st.number_input(f"{label} score", value=0, step=1))

        with col2:
            suits_used = st.multiselect("Suits Used (pick any amount)", options=SUITS, default=[])
            st.caption(
                f"Selected: **{len(suits_used)}** suits • Density tag: **{density_label(player_count, len(suits_used))}**"
            )
            st.caption("Authority included." if "Authority" in suits_used else "Authority not included.")

        with col3:
            modules_on = st.multiselect(
                "Modules Enabled",
                options=MODULES,
                default=["Wagering/Promises", "Jobs", "Heat/Disgrace", "Safe", "Specialists", "Contingencies"],
            )
            winner = st.text_input("Winner (optional)")
            notes = st.text_area("Notes (optional)", height=160)

        # ✅ SUBMIT BUTTON MUST BE INSIDE THE FORM BLOCK
        submitted = st.form_submit_button("Submit Play Log")

    # Handle submission OUTSIDE the form block
    if submitted:
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
            "winner": winner.strip(),
            "notes": notes.strip(),
        }
        append_play(play)

        st.success("Logged! Clearing form…")
        st.session_state.form_key += 1
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
