"""
Moneylines Scanner — Best Team Moneylines Across All Sports

Fetches h2h (moneyline) odds from The Odds API for NBA, MLB, and WNBA,
identifies the best value plays based on implied probability and payout.

Usage:
    from src.core.moneylines import run_moneylines_scanner
    run_moneylines_scanner()
"""

import os
import requests
import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo('America/New_York')

CACHE_DIR  = 'moneylines_cache'
CACHE_FILE = os.path.join(CACHE_DIR, 'moneylines_cache.json')
CACHE_DURATION_MINUTES = 30

SPORT_CONFIGS = {
    'NBA':  'basketball_nba',
    'MLB':  'baseball_mlb',
    'WNBA': 'basketball_wnba',
}

TARGET_BOOKS = ['fanduel', 'draftkings', 'betmgm', 'caesars', 'espnbet']
BASE_URL = "https://api.the-odds-api.com/v4/sports"


def _american_to_implied(odds: float) -> float:
    """Convert American odds to implied probability (0-1)."""
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    else:
        return abs(odds) / (abs(odds) + 100.0)


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        age = (time.time() - os.path.getmtime(CACHE_FILE)) / 60
        if age < CACHE_DURATION_MINUTES:
            print(f"   Using cached moneylines ({int(age)}m ago)")
            with open(CACHE_FILE) as f:
                return json.load(f)
        print(f"   Moneylines cache expired ({int(age)}m old) — fetching fresh")
    except Exception:
        pass
    return None


def _save_cache(data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


BOOK_LABELS = {
    'fanduel':   'FD',
    'draftkings':'DK',
    'betmgm':    'MGM',
    'caesars':   'CZR',
    'espnbet':   'ESPN',
}


def fetch_moneylines(api_key: str) -> list:
    cached = _load_cache()
    if cached is not None:
        return cached

    all_lines = []
    today = datetime.now(_EASTERN).strftime('%Y-%m-%d')

    for sport_label, sport_key in SPORT_CONFIGS.items():
        url = f"{BASE_URL}/{sport_key}/odds"
        params = {
            'apiKey':      api_key,
            'regions':     'us',
            'markets':     'h2h,totals',
            'oddsFormat':  'american',
            'bookmakers':  ','.join(TARGET_BOOKS),
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"   {sport_label}: API error {resp.status_code}")
                continue
            games = resp.json()
        except Exception as e:
            print(f"   {sport_label}: request failed — {e}")
            continue

        for game in games:
            try:
                ct = game.get('commence_time', '')
                if ct:
                    dt_utc = datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    dt_est = dt_utc.astimezone(_EASTERN)
                    game_date = dt_est.strftime('%Y-%m-%d')
                    game_time = dt_est.strftime('%I:%M %p ET')
                else:
                    game_date = today
                    game_time = 'TBD'
            except Exception:
                game_date = today
                game_time = 'TBD'

            home = game.get('home_team', '')
            away = game.get('away_team', '')

            # Collect per-book h2h odds and game totals
            team_book_odds = {home: {}, away: {}}  # team -> {book: odds}
            game_totals = []  # list of (line, over_odds, under_odds, book)

            for bm in game.get('bookmakers', []):
                book_key   = bm.get('key', '')
                book_label = BOOK_LABELS.get(book_key, book_key.upper()[:4])
                if book_key not in TARGET_BOOKS:
                    continue
                for mkt in bm.get('markets', []):
                    mkt_key = mkt.get('key')

                    if mkt_key == 'h2h':
                        for outcome in mkt.get('outcomes', []):
                            team  = outcome.get('name', '')
                            price = outcome.get('price')
                            if team in team_book_odds and price is not None:
                                team_book_odds[team][book_label] = float(price)

                    elif mkt_key == 'totals':
                        over_odds  = None
                        under_odds = None
                        total_line = None
                        for outcome in mkt.get('outcomes', []):
                            pt = outcome.get('point')
                            pr = outcome.get('price')
                            nm = outcome.get('name', '').lower()
                            if pt is not None:
                                total_line = float(pt)
                            if nm == 'over'  and pr is not None: over_odds  = float(pr)
                            if nm == 'under' and pr is not None: under_odds = float(pr)
                        if total_line is not None:
                            game_totals.append({
                                'line': total_line,
                                'over': over_odds,
                                'under': under_odds,
                                'book': book_label,
                            })

            # Summarise game total (avg line across books)
            total_line_avg = None
            total_over_avg = None
            total_under_avg = None
            if game_totals:
                total_line_avg  = round(sum(g['line'] for g in game_totals) / len(game_totals), 1)
                over_list       = [g['over']  for g in game_totals if g['over']  is not None]
                under_list      = [g['under'] for g in game_totals if g['under'] is not None]
                total_over_avg  = round(sum(over_list)  / len(over_list),  0) if over_list  else None
                total_under_avg = round(sum(under_list) / len(under_list), 0) if under_list else None

            # Build per-team rows with full book breakdown
            for team in [home, away]:
                book_odds = team_book_odds.get(team, {})
                if not book_odds:
                    continue

                odds_vals = list(book_odds.values())
                avg_odds  = sum(odds_vals) / len(odds_vals)
                best_odds  = max(odds_vals)
                worst_odds = min(odds_vals)
                best_book  = max(book_odds, key=book_odds.get)
                worst_book = min(book_odds, key=book_odds.get)
                implied    = _american_to_implied(avg_odds)
                opponent   = away if team == home else home
                is_home    = (team == home)

                row = {
                    'Sport':       sport_label,
                    'Date':        game_date,
                    'Time':        game_time,
                    'Team':        team,
                    'Opponent':    opponent,
                    'Home':        is_home,
                    'Avg Odds':    round(avg_odds),
                    'Best Odds':   round(best_odds),
                    'Best Book':   best_book,
                    'Worst Odds':  round(worst_odds),
                    'Worst Book':  worst_book,
                    'Win %':       round(implied * 100, 1),
                    'Books':       len(odds_vals),
                    'Game Total':  total_line_avg,
                    'Over Odds':   total_over_avg,
                    'Under Odds':  total_under_avg,
                }
                # Add individual book columns
                for bk in BOOK_LABELS.values():
                    row[bk] = book_odds.get(bk, None)

                all_lines.append(row)

    _save_cache(all_lines)
    return all_lines


def run_moneylines_scanner(api_key: str = None):
    """Print best moneylines across NBA, MLB, WNBA."""
    print("\n" + "=" * 60)
    print("   MONEYLINES  —  NBA  |  MLB  |  WNBA")
    print("=" * 60)

    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv('ODDS_API_KEY')
        except Exception:
            pass

    if not api_key:
        print("\n   ODDS_API_KEY not set. Add it to your .env file.")
        input("\nPress Enter to return...")
        return

    print(f"\n   Fetching moneylines...")
    lines = fetch_moneylines(api_key)

    if not lines:
        print("\n   No moneyline data available.")
        input("\nPress Enter to return...")
        return

    from datetime import datetime as _dt
    today = _dt.now(_EASTERN).strftime('%Y-%m-%d')

    # Group by sport, filter to today + upcoming
    by_sport = {}
    for row in lines:
        if row['Date'] < today:
            continue
        by_sport.setdefault(row['Sport'], []).append(row)

    if not by_sport:
        print("\n   No upcoming games found.")
        input("\nPress Enter to return...")
        return

    sep = " │ "
    w_team = 28
    w_opp  = 28

    for sport in ['NBA', 'MLB', 'WNBA']:
        rows = by_sport.get(sport, [])
        if not rows:
            continue

        # Sort: best value first = highest implied probability (favorite) or
        # best underdog value (implied < 50 = underdog, sorted by implied desc within day)
        rows_sorted = sorted(rows, key=lambda r: (-int(r['Date'] == today), r['Date'], -r['Implied']))

        print(f"\n{'─' * 72}")
        print(f"  {sport} MONEYLINES  ({len(rows)} teams)")
        print(f"{'─' * 72}")
        print(f"  {'TEAM':<{w_team}}{sep}{'OPPONENT':<{w_opp}}{sep}{'ODDS':>6}{sep}{'WIN%':>5}{sep}{'TIME'}")
        print(f"{'─' * 72}")

        seen_games = set()
        for r in rows_sorted:
            game_key = tuple(sorted([r['Team'], r['Opponent']]))
            home_marker = ' (H)' if r['Home'] else '     '
            team_s = (r['Team'] + home_marker)[:w_team]
            opp_s  = r['Opponent'][:w_opp]
            odds_s = f"{int(r['Odds']):+d}" if r['Odds'] != 0 else '  ---'
            pct_s  = f"{r['Implied']:.1f}%"
            time_s = r['Time']

            # Underdog flag
            flag = ''
            if r['Implied'] < 45:
                flag = ' ⬆'   # value underdog
            elif r['Implied'] > 70:
                flag = ' ★'   # heavy favourite

            # Separator between games
            if game_key not in seen_games and seen_games:
                pass  # no separator needed — sorted naturally
            seen_games.add(game_key)

            print(f"  {team_s:<{w_team}}{sep}{opp_s:<{w_opp}}{sep}{odds_s:>6}{sep}{pct_s:>5}{sep}{time_s}{flag}")

        print(f"{'─' * 72}")

    print(f"\n   ★ = Heavy favourite (>70% implied)  |  ⬆ = Underdog value (<45% implied)")
    print(f"   Odds = avg across {', '.join(TARGET_BOOKS[:3])} etc.  |  WIN% = implied probability (devig not applied)")
    print(f"   (H) = Home team")

    input("\nPress Enter to return to menu...")
