"""
PickFinder Props Client

Fetches player prop data from pickfinder.app, which aggregates lines from
20+ sportsbooks (PrizePicks, FanDuel, DraftKings, Caesars, BetMGM, etc.)
and provides hit rates, streaks, and consensus odds.

Authentication:
    Add your PickFinder login credentials to .env:
        PICKFINDER_EMAIL=your@email.com
        PICKFINDER_PASSWORD=yourpassword

    The client logs in automatically via Clerk (PickFinder's auth system)
    and refreshes the session token as needed.

Usage:
    from src.core.odds_providers.pickfinder import PickFinderClient
    client = PickFinderClient()
    df = client.fetch_board(sport='mlb')
    lines = client.fetch_lines_dict(sport='mlb', book='prizepicks')
"""

import os
import re
import json
import time
import requests
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR              = 'pickfinder_cache'
CACHE_DURATION_MINUTES = 30

BASE_URL   = "https://www.pickfinder.app"
API_BASE   = "https://api-v3.pickfinder.app"
CLERK_BASE = "https://clerk.pickfinder.app"

SPORT_PARAMS = {
    'nba':    'nba',
    'mlb':    'mlb',
    'nfl':    'nfl',
    'nhl':    'nhl',
    'tennis': 'tennis',
    'soccer': 'soccer',
    'all':    'all',
}

KNOWN_BOOKS = [
    'prizepicks', 'fanduel', 'draftkings', 'caesars', 'betmgm',
    'bet365', 'underdog', 'betonlineag', 'bovada', 'betrivers',
    'fanatics', 'hardrockbet', 'dabble', 'novig', 'prophetx',
    'rebet', 'parlayplay',
]

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(sport):
    tag = (sport or 'all').lower()
    return os.path.join(CACHE_DIR, f'pickfinder_{tag}.json')


def _load_cache(sport):
    path = _cache_path(sport)
    if not os.path.exists(path):
        return None
    try:
        age_mins = (time.time() - os.path.getmtime(path)) / 60
        if age_mins < CACHE_DURATION_MINUTES:
            print(f"   Using cached PickFinder data ({int(age_mins)}m ago)")
            with open(path) as f:
                return json.load(f)
        print(f"   PickFinder cache expired ({int(age_mins)}m old) — fetching fresh")
        return None
    except Exception as e:
        print(f"   Warning: could not read PickFinder cache: {e}")
        return None


def _load_stale_cache(sport):
    path = _cache_path(sport)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(items, sport):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(sport), 'w') as f:
            json.dump(items, f)
    except Exception as e:
        print(f"   Warning: could not save PickFinder cache: {e}")


# ---------------------------------------------------------------------------
# Clerk authentication
# ---------------------------------------------------------------------------

class _ClerkAuth:
    """
    Handles Clerk email/password sign-in for PickFinder.

    Clerk issues short-lived JWTs (~60s). We call the Clerk FAPI to:
      1. Create a sign-in attempt with email + password
      2. Exchange the completed sign-in for a session token
      3. Use that token for PickFinder API requests
      4. Re-authenticate when the token expires
    """

    CLERK_API_VERSION = "2024-10-01"

    def __init__(self, email: str, password: str):
        self._email    = email
        self._password = password
        self._token    = None
        self._exp      = 0.0   # Unix timestamp when token expires

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/131.0.0.0 Safari/537.36",
            "Origin":          BASE_URL,
            "Referer":         BASE_URL + "/sign-in",
            "Content-Type":    "application/x-www-form-urlencoded",
        })

    def get_token(self) -> str:
        """Return a valid session JWT, re-authenticating if needed."""
        if self._token and time.time() < self._exp - 10:
            return self._token
        self._authenticate()
        return self._token

    def _authenticate(self):
        """Full Clerk sign-in flow: create attempt → complete → get token."""
        ver = self.CLERK_API_VERSION

        # Step 1: Create a sign-in attempt
        r1 = self._session.post(
            f"{CLERK_BASE}/v1/client/sign_ins",
            params={"__clerk_api_version": ver},
            data={
                "identifier": self._email,
                "password":   self._password,
                "strategy":   "password",
            },
            timeout=15,
        )
        if r1.status_code not in (200, 201):
            raise RuntimeError(
                f"PickFinder login failed (step 1): HTTP {r1.status_code} — "
                "check PICKFINDER_EMAIL and PICKFINDER_PASSWORD in .env"
            )

        body1 = r1.json()

        # Step 2: Extract the sign-in ID and created session
        # If status is "complete" we already have the session
        sign_in = body1.get("response", body1)
        status  = sign_in.get("status", "")

        if status == "complete":
            client_obj = body1.get("client", {})
            sessions   = client_obj.get("sessions", [])
            if sessions:
                self._store_session(sessions[0])
                return

        # Try to get token from sign_in directly
        token = sign_in.get("created_session_id") or sign_in.get("id")

        # Step 3: If not yet complete, attempt to complete with password
        if status != "complete" and token:
            r2 = self._session.post(
                f"{CLERK_BASE}/v1/client/sign_ins/{token}/attempt_first_factor",
                params={"__clerk_api_version": ver},
                data={
                    "strategy": "password",
                    "password": self._password,
                },
                timeout=15,
            )
            if r2.status_code not in (200, 201):
                raise RuntimeError(
                    f"PickFinder login failed (step 2): HTTP {r2.status_code}"
                )
            body2     = r2.json()
            client_obj = body2.get("client", {})
            sessions   = client_obj.get("sessions", [])
            if sessions:
                self._store_session(sessions[0])
                return

        # Step 4: Fallback — get token from /v1/client
        r3 = self._session.get(
            f"{CLERK_BASE}/v1/client",
            params={"__clerk_api_version": ver},
            timeout=10,
        )
        if r3.status_code == 200:
            client_obj = r3.json().get("response", r3.json())
            sessions   = client_obj.get("sessions", [])
            if sessions:
                self._store_session(sessions[0])
                return

        raise RuntimeError(
            "PickFinder: could not obtain session token after sign-in. "
            "Check credentials in .env."
        )

    def _store_session(self, session_obj: dict):
        """Extract and store the JWT from a Clerk session object."""
        token = (
            session_obj.get("last_active_token", {}).get("jwt")
            or session_obj.get("id")
        )
        if not token:
            raise RuntimeError("PickFinder: Clerk returned a session but no JWT token.")
        self._token = token

        # Decode the exp claim from the JWT payload (no signature verification needed)
        try:
            import base64
            payload_b64 = token.split(".")[1]
            padding     = 4 - len(payload_b64) % 4
            payload     = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
            self._exp   = float(payload.get("exp", time.time() + 55))
        except Exception:
            self._exp = time.time() + 55   # assume 55s if decode fails


# ---------------------------------------------------------------------------
# American odds → implied probability
# ---------------------------------------------------------------------------

def _american_to_implied(price):
    try:
        p = float(price)
        if p > 0:
            return 100 / (p + 100)
        else:
            return abs(p) / (abs(p) + 100)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Page RSC payload parser (fallback if direct API doesn't return JSON)
# ---------------------------------------------------------------------------

def _extract_json_objects_from_page(html: str) -> list:
    all_items = []

    chunks = re.findall(
        r'self\.__next_f\.push\(\[(\d+),(.+?)\]\)</script>',
        html, re.DOTALL
    )
    if not chunks:
        nd = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            html, re.DOTALL
        )
        if nd:
            try:
                data = json.loads(nd.group(1))
                pp   = data.get('props', {}).get('pageProps', {})
                return pp.get('items', [])
            except Exception:
                pass
        return []

    for _, chunk_body in chunks:
        if chunk_body.strip() in ('null', 'undefined', ''):
            continue
        try:
            content = json.loads(chunk_body)
        except Exception:
            content = chunk_body

        if not isinstance(content, str):
            continue

        for line in content.split('\n'):
            colon_idx = line.find(':')
            if colon_idx == -1:
                continue
            payload = line[colon_idx + 1:].strip()
            if not (payload.startswith('{') or payload.startswith('[')):
                continue
            if payload.startswith('T'):
                comma_idx = payload.find(',')
                if comma_idx != -1:
                    payload = payload[comma_idx + 1:]
            try:
                obj = json.loads(payload)
            except Exception:
                continue

            if isinstance(obj, dict):
                items = obj.get('items')
                if items and isinstance(items, list) and items:
                    if 'player_name' in items[0] or 'stat' in items[0]:
                        all_items.extend(items)
                        continue
                if 'player_name' in obj and 'line' in obj:
                    all_items.append(obj)
            elif isinstance(obj, list):
                for elem in obj:
                    if isinstance(elem, dict) and 'player_name' in elem and 'line' in elem:
                        all_items.append(elem)

    return all_items


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class PickFinderClient:

    def __init__(self, email=None, password=None):
        """
        Args:
            email:    PickFinder account email. Falls back to PICKFINDER_EMAIL env var.
            password: PickFinder password.       Falls back to PICKFINDER_PASSWORD env var.
        """
        self._email    = email    or os.getenv('PICKFINDER_EMAIL',    '')
        self._password = password or os.getenv('PICKFINDER_PASSWORD', '')
        self._auth     = None

        if self._email and self._password:
            self._auth = _ClerkAuth(self._email, self._password)

        self._http = requests.Session()
        self._http.headers.update({
            "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/131.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         BASE_URL + "/",
        })

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def fetch_board(self, sport='all', modifier='none', include_alts=False) -> pd.DataFrame:
        """
        Fetch all props from PickFinder for a given sport.

        Args:
            sport:        'all', 'nba', 'mlb', 'tennis', etc.
            modifier:     'none' (standard lines only)
            include_alts: if True, include alternate lines

        Returns:
            DataFrame with columns:
                player_name, stat, sport, league, game_string, start_date,
                line, book, over_price, under_price,
                hit_rate_l5, hit_rate_l10, hit_rate_l15, streak,
                avg_last10, consensus_over_ip, consensus_under_ip,
                favorite_count_over, favorite_count_under, is_alt_line
        """
        if not self._auth:
            print("   ⚠️  No PickFinder credentials — add to .env:")
            print("      PICKFINDER_EMAIL=your@email.com")
            print("      PICKFINDER_PASSWORD=yourpassword")
            return pd.DataFrame()

        cached = _load_cache(sport)
        if cached is not None:
            return self._apply_filters(pd.DataFrame(cached), include_alts)

        items = self._fetch_all_items(sport, modifier)
        if not items:
            stale = _load_stale_cache(sport)
            if stale:
                print("   Using stale PickFinder cache (live fetch failed)")
                return self._apply_filters(pd.DataFrame(stale), include_alts)
            return pd.DataFrame()

        rows = self._flatten_items(items)
        _save_cache(rows, sport)
        return self._apply_filters(pd.DataFrame(rows), include_alts)

    def fetch_lines_dict(self, sport='all', book='prizepicks', include_alts=False) -> dict:
        """Return {player_name: {stat: line}} for a specific book."""
        df = self.fetch_board(sport=sport, include_alts=include_alts)
        if df.empty:
            return {}
        df_book = df[df['book'] == book]
        result  = {}
        for _, row in df_book.iterrows():
            player = row['player_name']
            if player not in result:
                result[player] = {}
            result[player][row['stat']] = float(row['line'])
        return result

    def fetch_enriched(self, sport='all', book='prizepicks') -> pd.DataFrame:
        """One row per player+stat at the given book, with hit rates and consensus."""
        df = self.fetch_board(sport=sport)
        if df.empty:
            return df
        return df[df['book'] == book].copy()

    # -----------------------------------------------------------------------
    # Internal fetching
    # -----------------------------------------------------------------------

    def _fetch_all_items(self, sport, modifier) -> list:
        sport_param = SPORT_PARAMS.get(sport.lower(), 'all')

        try:
            token = self._auth.get_token()
        except Exception as e:
            print(f"   PickFinder login failed: {e}")
            return []

        print(f"   Fetching PickFinder ({sport_param})...")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/json",
            "Origin":        BASE_URL,
            "Referer":       BASE_URL + "/props",
        }

        all_items = []
        page      = 1
        per_page  = 100
        total_pages = 1

        while page <= total_pages:
            params = {
                "sport":    sport_param,
                "modifier": modifier,
                "page":     page,
                "perPage":  per_page,
                "sort":     "",
                "app":      "",
                "games":    "",
            }
            try:
                r = self._http.get(
                    f"{API_BASE}/props",
                    headers=headers,
                    params=params,
                    timeout=20,
                )
            except Exception as e:
                print(f"   PickFinder fetch error (page {page}): {e}")
                break

            if r.status_code == 401:
                # Token may have just expired — re-auth once then retry
                try:
                    token = self._auth.get_token()
                    headers["Authorization"] = f"Bearer {token}"
                    r = self._http.get(f"{API_BASE}/props", headers=headers, params=params, timeout=20)
                except Exception:
                    pass

            if r.status_code != 200:
                print(f"   PickFinder: HTTP {r.status_code} (page {page})")
                break

            try:
                data = r.json()
            except Exception as e:
                print(f"   PickFinder: JSON parse error on page {page}: {e}")
                break

            items = data.get('items', [])
            if not items:
                break

            all_items.extend(items)
            total_pages = data.get('totalPages', 1)

            if page == 1:
                total = data.get('totalItems', '?')
                print(f"   PickFinder: {total} props across {total_pages} pages")

            page += 1

        return all_items

    # -----------------------------------------------------------------------
    # Flatten items → rows (one row per player+stat+book)
    # -----------------------------------------------------------------------

    def _flatten_items(self, items: list) -> list:
        rows = []
        for item in items:
            base = {
                'player_name':            item.get('player_name', ''),
                'player_name_normalized': item.get('player_name_normalized', ''),
                'stat':                   item.get('stat', ''),
                'market_id':              item.get('market_id', ''),
                'sport':                  item.get('sport', ''),
                'league':                 item.get('league', ''),
                'game_string':            item.get('game_string', ''),
                'start_date':             item.get('start_date', ''),
                'line':                   item.get('line', 0),
                'hit_rate_l5':            item.get('hitRateLast5',  -1),
                'hit_rate_l10':           item.get('hitRateLast10', -1),
                'hit_rate_l15':           item.get('hitRateLast15', -1),
                'streak':                 item.get('streak', 0),
                'avg_last10':             item.get('averageLast10', None),
                'diff_last10':            item.get('differenceLast10', None),
                'consensus_over_ip':      item.get('consensus_over_ip',  0),
                'consensus_under_ip':     item.get('consensus_under_ip', 0),
                'favorite_count_over':    item.get('favorite_count_over',  0),
                'favorite_count_under':   item.get('favorite_count_under', 0),
                'is_alt_line':            item.get('isAltLine', False),
            }

            apps = item.get('apps', {})
            if not apps:
                row = dict(base)
                row.update({'book': '', 'over_price': None, 'under_price': None, 'is_main': True})
                rows.append(row)
                continue

            for book_name, book_data in apps.items():
                outcomes  = book_data.get('outcomes', {})
                over_out  = outcomes.get('over',  {})
                under_out = outcomes.get('under', {})

                # Line-movement: compare oldest history entry to current prices
                history   = book_data.get('history', [])
                over_drift = under_drift = line_drift = None
                if history:
                    oldest     = min(history, key=lambda x: x.get('timestamp', float('inf')))
                    open_over  = oldest.get('over_price')
                    open_under = oldest.get('under_price')
                    open_line  = oldest.get('line')
                    curr_over  = over_out.get('price')
                    curr_under = under_out.get('price')
                    if curr_over  is not None and open_over  is not None:
                        over_drift  = curr_over  - open_over   # negative → over got pricier
                    if curr_under is not None and open_under is not None:
                        under_drift = curr_under - open_under
                    if open_line  is not None:
                        line_drift  = base['line'] - open_line

                row = dict(base)
                row.update({
                    'book':        book_name,
                    'over_price':  over_out.get('price'),
                    'under_price': under_out.get('price'),
                    'is_main':     over_out.get('is_main', True),
                    'over_drift':  over_drift,
                    'under_drift': under_drift,
                    'line_drift':  line_drift,
                })
                rows.append(row)

        return rows

    def get_movement_summary(self, sport='all') -> dict:
        """
        Aggregate line-movement signals per player+stat across all books.

        Returns:
            {(player_name_normalized, stat): {
                'move_over':  int,   # books where over juice got meaningfully pricier
                'move_under': int,   # books where under juice got meaningfully pricier
                'net':        int,   # move_over - move_under (positive = over pressure)
                'line_moved': bool,  # any book showed the line number itself change
            }}

        Only props with at least one book showing history are included.
        """
        df = self.fetch_board(sport=sport)
        if df.empty or 'over_drift' not in df.columns:
            return {}

        DRIFT_THRESH = 3   # cents — ignore sub-3-cent noise

        result = {}
        for (player, stat), grp in df.groupby(['player_name_normalized', 'stat']):
            valid = grp[grp['over_drift'].notna()]
            if valid.empty:
                continue
            move_over  = int((valid['over_drift']  < -DRIFT_THRESH).sum())
            move_under = int((valid['under_drift'].fillna(0) < -DRIFT_THRESH).sum())
            line_moved = bool((valid['line_drift'].fillna(0).abs() > 0).any())
            if move_over or move_under or line_moved:
                result[(player, stat)] = {
                    'move_over':  move_over,
                    'move_under': move_under,
                    'net':        move_over - move_under,
                    'line_moved': line_moved,
                }
        return result

    def _apply_filters(self, df: pd.DataFrame, include_alts: bool) -> pd.DataFrame:
        if df.empty:
            return df
        if not include_alts and 'is_alt_line' in df.columns:
            df = df[~df['is_alt_line'].fillna(False)]
        return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- TESTING PICKFINDER CLIENT ---")

    email    = os.getenv('PICKFINDER_EMAIL',    '')
    password = os.getenv('PICKFINDER_PASSWORD', '')

    if not email or not password:
        print("\n❌ Add to .env:")
        print("   PICKFINDER_EMAIL=your@email.com")
        print("   PICKFINDER_PASSWORD=yourpassword")
    else:
        print(f"\n✅ Credentials found ({email})")
        client = PickFinderClient()

        print("\nLogging in...")
        df = client.fetch_board(sport='all')

        if df.empty:
            print("❌ No data returned")
        else:
            print(f"✅ {len(df)} rows, {df['player_name'].nunique()} players, {df['book'].nunique()} books")
            print(f"   Sports: {df['sport'].unique().tolist()}")
            print(f"   Books:  {sorted(df['book'].unique().tolist())[:8]}")
            print(f"\n   Sample (PrizePicks, baseball):")
            sample = df[(df['book'] == 'prizepicks') & (df['sport'] == 'baseball')].head(5)
            if not sample.empty:
                cols = ['player_name', 'stat', 'line', 'hit_rate_l10', 'streak']
                print(sample[cols].to_string(index=False))
