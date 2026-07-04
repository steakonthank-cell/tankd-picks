# MLB MONEYLINE PREDICTOR — BUILD PLAN
Status: NOT BUILT. Scaffold TODO at src/sports/mlb/moneyline_pythag.py.
Created 2026-06-16 (the HA-model + name-join-bug session).

THE ONE RULE: each step has a GATE. Don't advance until it passes. The model
does NOT enter the app until Step 4 proves it beats the CLOSING LINE out of sample.

STEP 0 (quick win, anytime): fix broken plumbing.
  server.py ~179 imports get_moneylines which does NOT exist (use fetch_moneylines).
  output/moneylines/latest.csv is never written. smart_picks.py already sends ML to
  Discord fine; only the dashboard endpoint is broken. Fix: smart_picks writes
  latest.csv; server.py reads it. No leakage risk.

STEP 1: build game-outcome table [GATE: 5 games match real scores].
  Sum boxscore runs per team per game -> home/away score -> home_win(1/0).
  Source: data/mlb/boxscores/*.json, data/mlb/raw/batting_logs.csv (date,team_id,opponent_id,R).

STEP 2: pre-game features [GATE: no same-game data].
  Only pre-first-pitch info. Lag everything with .shift(1) like features.py.
  Team run form, starter quality (reuse ER/HA models), rest, home/away, park.
  Kill any feature that peeks at the game's own result. Do this rested.

STEP 3: Pythagorean first [GATE: TIME-ORDERED split].
  win% = R^1.83 / (R^1.83 + RA^1.83). Classifier only if Pythag underperforms;
  mirror tennis/match_win_train.py BUT fix its positional-split bug (sort by date,
  test=recent slice). Calibrate. AUC>0.70 = suspect leakage.

STEP 4: backtest vs CLOSING lines [GATE: beat the line OOS or it's dead].
  implied prob via _american_to_implied. Bet only on disagreement >~4%.
  Measure calibration + ROI. No edge vs closing line = does NOT go in app.

STEP 5: only after Step 4 passes — wire to output/moneylines, server.py, Discord, cron.

NOTES: all existing models are player props (no game model yet). Tennis match_win
metrics were never saved. Don't copy tennis positional-split bug. MLB data is
current-roster anchored.
