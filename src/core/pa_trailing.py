import os, json, glob, unicodedata
from collections import defaultdict

_BOX_DIR = "data/mlb/boxscores"
_LEAGUE_AVG_PA = 4.2  # PA/game for a regular regular; centers the multiplier
_LO, _HI = 0.92, 1.08  # bounds - modest signal, modest nudge

_cache = None  # date -> {norm_name: pa}


def _norm(n):
    if not isinstance(n, str): return ""
    n = unicodedata.normalize("NFKD", n).encode("ascii","ignore").decode().lower()
    n = n.replace(".","").replace(",","").strip()
    for s in (" jr"," sr"," ii"," iii"," iv"):
        if n.endswith(s): n = n[:-len(s)]
    return " ".join(n.split())


def _build_index():
    global _cache
    if _cache is not None: return _cache
    _cache = defaultdict(dict)
    for f in sorted(glob.glob(f"{_BOX_DIR}/*.json")):
        date = os.path.basename(f).replace(".json", "")
        try:
            bx = json.load(open(f))
        except Exception:
            continue
        for _gk, game in bx.items():
            if not isinstance(game, dict): continue
            for pname, rec in game.items():
                if not isinstance(rec, dict): continue
                b = rec.get("batting", {}) or {}
                ab = b.get("atBats")
                bb = b.get("baseOnBalls")
                if ab is not None:
                    _cache[date][_norm(pname)] = (ab or 0) + (bb or 0)
    return _cache


def trailing_pa(norm_name, upto_date, lookback=10):
    """Avg PA/game over the player's last `lookback` appearances before upto_date.
    Returns None if no history. name must already be normalized."""
    idx = _build_index()
    vals = []
    for d in sorted(idx.keys()):
        if str(d) >= str(upto_date): break
        if norm_name in idx[d]:
            vals.append(idx[d][norm_name])
    vals = vals[-lookback:]
    if not vals: return None
    return sum(vals) / len(vals)


def pa_volume_mult(norm_name, upto_date, lookback=10):
    """Bounded multiplier from trailing PA volume. 1.0 if no history (safe)."""
    tpa = trailing_pa(norm_name, upto_date, lookback)
    if tpa is None:
        return 1.0, None
    raw = tpa / _LEAGUE_AVG_PA
    mult = max(_LO, min(_HI, raw))
    return round(mult, 3), round(tpa, 2)
