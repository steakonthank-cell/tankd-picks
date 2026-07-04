import re

# ============================================================
# PART A: scanner.py — build name→id map (cached), write MLB_ID
# ============================================================
sp = "src/sports/mlb/scanner.py"
src = open(sp).read()
orig = src

# A1. Add the id-map loader after the _abbr function (idempotent)
if "_load_player_ids" not in src:
    loader = '''
# ── MLB player-id map for headshots (cached from stats API) ──
_PLAYER_IDS = None
def _load_player_ids():
    global _PLAYER_IDS
    if _PLAYER_IDS is not None:
        return _PLAYER_IDS
    import json, os, time
    cache = "data/mlb/player_ids.json"
    try:
        # refresh if missing or older than 7 days
        fresh = os.path.exists(cache) and (time.time() - os.path.getmtime(cache) < 7*86400)
        if fresh:
            _PLAYER_IDS = json.load(open(cache))
            return _PLAYER_IDS
    except Exception:
        pass
    ids = {}
    try:
        import requests
        r = requests.get("https://statsapi.mlb.com/api/v1/sports/1/players",
                         params={"season": 2026}, timeout=15)
        if r.status_code == 200:
            for p in r.json().get("people", []):
                nm = normalize_name(p.get("fullName", ""))
                if nm and p.get("id"):
                    ids[nm] = p["id"]
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(ids, open(cache, "w"))
    except Exception as _e:
        print(f"[scanner] player-id map fetch failed: {_e}")
    _PLAYER_IDS = ids
    return _PLAYER_IDS

'''
    # insert right after the _abbr function definition
    anchor = '''def _abbr(full):
    return _TEAM_ABBR.get(full, full[:3].upper() if full else "")'''
    assert anchor in src, "_abbr anchor not found"
    src = src.replace(anchor, anchor + "\n" + loader)

# A2. Add MLB_ID to the result dict, right after Team
old_team = "            'Team':        _abbr(player_to_team.get(normalize_name(player_name), '')),"
new_team = old_team + "\n            'MLB_ID':      _load_player_ids().get(normalize_name(player_name), ''),"
assert old_team in src, "Team result line not found"
src = src.replace(old_team, new_team)

assert src != orig, "scanner unchanged"
open(sp, "w").write(src)
print("scanner.py: MLB_ID wiring added")

# ============================================================
# PART B: api/server.py — serve a headshot URL from MLB_ID
# ============================================================
ap = "api/server.py"
asrc = open(ap).read()
aorig = asrc

# Add "headshot" + "mlb_id" to the pick dict, right after the team line
old_api_team = '            "team": row.get("team", row.get("Team", "")),'
new_api_team = old_api_team + '''
            "mlb_id": (str(int(float(row.get("MLB_ID")))) if pd.notna(row.get("MLB_ID")) and str(row.get("MLB_ID")).strip() not in ("", "nan") else None),
            "headshot": (f"https://midfield.mlbstatic.com/v1/people/{int(float(row.get('MLB_ID')))}/spots/120" if pd.notna(row.get("MLB_ID")) and str(row.get("MLB_ID")).strip() not in ("", "nan") else None),'''
assert old_api_team in asrc, "api team line not found"
asrc = asrc.replace(old_api_team, new_api_team)

assert asrc != aorig, "server unchanged"
open(ap, "w").write(asrc)
print("api/server.py: headshot + mlb_id served")
print("Stage 1 complete")
