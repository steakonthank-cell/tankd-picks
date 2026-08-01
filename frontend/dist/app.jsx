const { useState, useMemo, useCallback, useEffect, useRef } = React;

// ─── Constants ───────────────────────────────────────────────────────────────

const SPORTS = ["MLB"];
const TABS = ["Scanner", "Sharp", "Builder", "Moneylines"];
const TIER_COLORS = { ELITE: "#a855f7", FIRE: "#f97316", SOLID: "#22c55e", VALUE: "#3b82f6", STRONG: "#22c55e", DECENT: "#eab308", LEAN: "#64748b" };
const TIER_BG = { ELITE: "rgba(168,85,247,0.15)", FIRE: "rgba(249,115,22,0.15)", SOLID: "rgba(34,197,94,0.15)", VALUE: "rgba(59,130,246,0.15)", STRONG: "rgba(34,197,94,0.15)", DECENT: "rgba(234,179,8,0.15)", LEAN: "rgba(100,116,139,0.15)" };

const C = {
  bg: "#0a1019",
  card: "#0f1923",
  cardHover: "#141f2e",
  border: "#1a2736",
  green: "#22c55e",
  greenDim: "rgba(34,197,94,0.12)",
  yellow: "#eab308",
  yellowDim: "rgba(234,179,8,0.12)",
  red: "#ef4444",
  redDim: "rgba(239,68,68,0.12)",
  text: "#e6e9ed",
  textDim: "#8c97a4",
  accent: "#22c55e",
  base: "#0e1116",
  card2: "#1c232c",
  line: "#262e38",
  line2: "#323c48",
  gold: "#e8a33d",
  goldD: "#7a5418",
  goldBg: "#241b0e",
  teal: "#39b0a6",
  tealBg: "#0e211f",
};

const FONT_DISPLAY = "'Oswald', sans-serif";
const FONT_COND = "'Barlow Condensed', sans-serif";
const FONT_MONO = "'JetBrains Mono', ui-monospace, monospace";

// Team primary colors, keyed by the abbreviations _abbr() emits.
const TEAM_COLORS = {
  ARI:"#a71930", ATH:"#003831", ATL:"#ce1141", BAL:"#df4601", BOS:"#bd3039",
  CHC:"#0e3386", CWS:"#27251f", CIN:"#c6011f", CLE:"#0c2340", COL:"#333366",
  DET:"#0c2340", HOU:"#eb6e1f", KC:"#004687", LAA:"#ba0021", LAD:"#005a9c",
  MIA:"#00a3e0", MIL:"#12284b", MIN:"#002b5c", NYM:"#002d72", NYY:"#0c2340",
  PHI:"#e81828", PIT:"#fdb827", SD:"#2f241d", SF:"#fd5a1e", SEA:"#0c2c56",
  STL:"#c41e3a", TB:"#092c5c", TEX:"#003278", TOR:"#134a8e", WSH:"#ab0003",
};
function teamColor(abbr) {
  return TEAM_COLORS[(abbr || "").toUpperCase()] || C.teal;
}

// Team logos (ESPN CDN), keyed by full team name — ported from the legacy
// Streamlit app's _ESPN_MLB/_ESPN_NBA/_ESPN_WNBA + _team_logo() (app.py).
const TEAM_LOGO_SLUG = {
  MLB: {
    "Arizona Diamondbacks":"ari","Atlanta Braves":"atl","Baltimore Orioles":"bal",
    "Boston Red Sox":"bos","Chicago Cubs":"chc","Chicago White Sox":"chw",
    "Cincinnati Reds":"cin","Cleveland Guardians":"cle","Colorado Rockies":"col",
    "Detroit Tigers":"det","Houston Astros":"hou","Kansas City Royals":"kc",
    "Los Angeles Angels":"laa","Los Angeles Dodgers":"lad","Miami Marlins":"mia",
    "Milwaukee Brewers":"mil","Minnesota Twins":"min","New York Mets":"nym",
    "New York Yankees":"nyy","Athletics":"oak","Oakland Athletics":"oak",
    "Philadelphia Phillies":"phi","Pittsburgh Pirates":"pit","San Diego Padres":"sd",
    "San Francisco Giants":"sf","Seattle Mariners":"sea","St. Louis Cardinals":"stl",
    "Tampa Bay Rays":"tb","Texas Rangers":"tex","Toronto Blue Jays":"tor",
    "Washington Nationals":"wsh",
  },
  NBA: {
    "Atlanta Hawks":"atl","Boston Celtics":"bos","Brooklyn Nets":"bkn",
    "Charlotte Hornets":"cha","Chicago Bulls":"chi","Cleveland Cavaliers":"cle",
    "Dallas Mavericks":"dal","Denver Nuggets":"den","Detroit Pistons":"det",
    "Golden State Warriors":"gs","Houston Rockets":"hou","Indiana Pacers":"ind",
    "Los Angeles Clippers":"lac","Los Angeles Lakers":"lal","Memphis Grizzlies":"mem",
    "Miami Heat":"mia","Milwaukee Bucks":"mil","Minnesota Timberwolves":"min",
    "New Orleans Pelicans":"no","New York Knicks":"ny","Oklahoma City Thunder":"okc",
    "Orlando Magic":"orl","Philadelphia 76ers":"phi","Phoenix Suns":"phx",
    "Portland Trail Blazers":"por","Sacramento Kings":"sac","San Antonio Spurs":"sa",
    "Toronto Raptors":"tor","Utah Jazz":"utah","Washington Wizards":"wsh",
  },
  WNBA: {
    "Atlanta Dream":"atl","Chicago Sky":"chi","Connecticut Sun":"conn",
    "Dallas Wings":"dal","Indiana Fever":"ind","Las Vegas Aces":"lv",
    "Los Angeles Sparks":"la","Minnesota Lynx":"min","New York Liberty":"ny",
    "Phoenix Mercury":"phx","Seattle Storm":"sea","Washington Mystics":"wsh",
    "Golden State Valkyries":"gsv","Portland Fire":"por",
  },
};
function teamLogoUrl(fullName, sport) {
  const slug = (TEAM_LOGO_SLUG[sport] || {})[fullName];
  if (!slug) return null;
  const sportPath = { MLB: "mlb", NBA: "nba", WNBA: "wnba" }[sport] || "mlb";
  return `https://a.espncdn.com/i/teamlogos/${sportPath}/500/${slug}.png`;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pctColor(val) {
  const n = parseInt(val);
  if (n >= 75) return C.green;
  if (n >= 50) return C.yellow;
  return C.red;
}
function pctBg(val) {
  const n = parseInt(val);
  if (n >= 75) return C.greenDim;
  if (n >= 50) return C.yellowDim;
  return C.redDim;
}
function scoreColor(s) {
  if (s >= 90) return C.green;
  if (s >= 75) return C.yellow;
  return C.red;
}

function formatPF(pf) {
  if (pf == null) return { txt: "\u2014", neutral: true };
  const v = pf / 100;
  return { txt: v.toFixed(2), neutral: Math.abs(v - 1) < 0.005 };
}

// Short "as of" stamp for the header \u2014 last_scan is when today's board was
// scored; model_trained_at is when the underlying model weights were last
// fit (data refreshes nightly, the model itself does not \u2014 these can and do
// diverge by weeks).
function formatAsOf(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function daysSince(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

// Color a recent-form average by whether it clears the betting line.
function formColor(val, line, side) {
  const v = parseFloat(val);
  const l = parseFloat(line);
  if (isNaN(v) || isNaN(l)) return C.textDim;
  const over = (side || "Over").toLowerCase() === "over";
  const clears = over ? v >= l : v <= l;
  const margin = Math.abs(v - l) / Math.max(l, 0.5);
  if (clears) return margin > 0.25 ? C.green : C.teal;
  return C.red;
}

// Honest tier -> chip colors
function tierColors(tier) {
  if (tier === "LOCK")   return { fg: C.gold, bg: C.goldBg, bd: C.goldD };
  if (tier === "STRONG") return { fg: C.teal, bg: C.tealBg, bd: "#1c4b45" };
  if (tier === "LEAN")   return { fg: C.textDim, bg: C.card2, bd: C.line2 };
  return { fg: C.textDim, bg: C.card2, bd: C.line2 };
}

function getStatTypes(sport, picks) {
  return [...new Set(picks.filter(p => true).map(p => p.stat_type))];
}

function getLines(picks, statType) {
  return [...new Set(picks.filter(p => p.stat_type === statType).map(p => p.line))].sort((a, b) => a - b);
}

// ─── Sub-Components ──────────────────────────────────────────────────────────

function TierBadge({ tier }) {
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, letterSpacing: 1.2,
      color: TIER_COLORS[tier], background: TIER_BG[tier],
      padding: "2px 7px", borderRadius: 4, textTransform: "uppercase",
    }}>{tier}</span>
  );
}

function StatCell({ value, frac, label, line, side }) {
  const col = formColor(value, line, side);
  return (
    <div style={{ textAlign: "center", flex: 1 }}>
      <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>{label}</div>
      <div style={{ color: col, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{value}</div>
      {frac && <div style={{ color: C.textDim, fontSize: 9, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>{frac}</div>}
    </div>
  );
}

function PlayerAvatar({ name, team, headshot, mlbId, size = 52 }) {
  const initials = (name || "").split(" ").map(n => n[0]).join("").slice(0, 2);
  const tc = teamColor(team);
  const src = headshot || (mlbId ? `https://midfield.mlbstatic.com/v1/people/${mlbId}/spots/120` : null);
  const [failed, setFailed] = React.useState(false);
  const show = src && !failed;
  return (
    <div style={{
      width: size, height: size, borderRadius: 11, flexShrink: 0, overflow: "hidden",
      background: C.card2, border: `2px solid ${tc}`,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {show ? (
        <img src={src} alt="" onError={() => setFailed(true)}
          style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top center" }} />
      ) : (
        <span style={{ fontFamily: FONT_DISPLAY, fontSize: size * 0.38, fontWeight: 600, color: tc }}>{initials}</span>
      )}
    </div>
  );
}

function TeamLogo({ name, sport, abbr, size = 52 }) {
  const tc = teamColor(abbr);
  const src = teamLogoUrl(name, sport);
  const [failed, setFailed] = React.useState(false);
  const show = src && !failed;
  return (
    <div style={{
      width: size, height: size, borderRadius: 11, flexShrink: 0, overflow: "hidden",
      background: C.card2, border: `2px solid ${tc}`,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {show ? (
        <img src={src} alt="" onError={() => setFailed(true)}
          style={{ width: "78%", height: "78%", objectFit: "contain" }} />
      ) : (
        <span style={{ fontFamily: FONT_DISPLAY, fontSize: size * 0.32, fontWeight: 600, color: tc }}>{abbr}</span>
      )}
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────────────

function confDisplay(mp) {
  if (mp == null) return { tier: "", pct: null };
  let tier, lo, hi, raw0, raw1;
  if (mp >= 0.92)      { tier = "LOCK";   lo = 0.68; hi = 0.72; raw0 = 0.92; raw1 = 1.00; }
  else if (mp >= 0.80) { tier = "STRONG"; lo = 0.63; hi = 0.68; raw0 = 0.80; raw1 = 0.92; }
  else if (mp >= 0.68) { tier = "LEAN";   lo = 0.58; hi = 0.63; raw0 = 0.68; raw1 = 0.80; }
  else                 { tier = "PASS";   lo = 0.50; hi = 0.58; raw0 = 0.40; raw1 = 0.68; }
  const f = Math.max(0, Math.min(1, (mp - raw0) / (raw1 - raw0)));
  const pct = Math.round((lo + f * (hi - lo)) * 100);
  return { tier, pct };
}

// Explicit failure state for a broken /api/picks fetch. Previously this
// silently fell back to hardcoded mock picks (fake players, fake ELITE
// tiers) with no indication they weren't real — for a props-betting
// dashboard, showing nothing is safer than showing confident-looking fake
// data with no way to tell the difference.
function PicksErrorState({ sport, onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 20px" }}>
      <div style={{ fontSize: 30, marginBottom: 12 }}>⚠️</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 6 }}>
        Couldn't load {sport} picks
      </div>
      <div style={{ fontSize: 12, color: C.textDim, marginBottom: 18, maxWidth: 300, marginLeft: "auto", marginRight: "auto" }}>
        The picks API didn't respond. Nothing is shown rather than stale or placeholder data.
      </div>
      <button onClick={onRetry} style={{
        padding: "8px 22px", borderRadius: 8, border: `1px solid ${C.line2}`,
        background: "transparent", color: C.text, fontSize: 13, fontWeight: 600, cursor: "pointer",
      }}>
        Retry
      </button>
    </div>
  );
}

function TankdPicks() {
  const [sport, setSport] = useState("MLB");
  const [tab, setTab] = useState("Scanner");
  const [segment, setSegment] = useState("hitter"); // hitter | pitcher (MLB only)
  const [statType, setStatType] = useState(null);
  const [line, setLine] = useState(null);
  const [sortBy, setSortBy] = useState("score");
  const [sortDir, setSortDir] = useState("desc");
  const [gradeFilter, setGradeFilter] = useState("all"); // all | LOCK | STRONG | LEAN
  const [tierFilter, setTierFilter] = useState("all"); // all | ELITE | STRONG | DECENT | LEAN (v2_tier, non-goblin only)
  const [builderLegs, setBuilderLegs] = useState([]);

  const [apiPicks, setApiPicks] = useState({});
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState({}); // { [sport]: true } on failure
  const [retryTick, setRetryTick] = useState(0);
  const [meta, setMeta] = useState({}); // { [sport]: { last_scan, model_trained_at, api_version } }

  useEffect(() => {
    setLoading(true);
    fetch("/api/picks/" + sport)
      .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(data => {
        const transformed = (data.picks || []).map(p => ({
          ...p,
          l5: (p.l5 != null ? String(p.l5) : "—"),
          l10: (p.l10 != null ? String(p.l10) : "—"),
          l5_frac: "",
          l10_frac: "",
          segment: p.segment || (p.is_pitcher ? "pitcher" : "hitter"),
        }));
        setApiPicks(prev => ({ ...prev, [sport]: transformed }));
        setFetchError(prev => ({ ...prev, [sport]: false }));
        setMeta(prev => ({ ...prev, [sport]: {
          last_scan: data.last_scan || null,
          model_trained_at: data.model_trained_at || null,
          api_version: data.api_version || null,
        } }));
        setLoading(false);
      })
      .catch(() => {
        setFetchError(prev => ({ ...prev, [sport]: true }));
        setLoading(false);
      });
  }, [sport, retryTick]);

  const picks = apiPicks[sport] || [];
  const hasError = !!fetchError[sport] && !apiPicks[sport];
  const retry = useCallback(() => setRetryTick(t => t + 1), []);
  const activeMeta = meta[sport] || {};

  // For MLB, filter by segment first
  const segmentPicks = (sport === "MLB"
    ? picks.filter(p => p.segment === segment)
    : picks);

  const statTypes = useMemo(() => getStatTypes(sport, segmentPicks), [sport, segment, apiPicks]);
  const activeStatType = statType && statTypes.includes(statType) ? statType : statTypes[0];

  const lines = useMemo(
    () => getLines(segmentPicks, activeStatType),
    [sport, segment, activeStatType, apiPicks]
  );
  const activeLine = line !== null && lines.includes(line) ? line : lines[0] ?? null;

  // Reset selections on sport change
  const handleSportChange = useCallback((s) => {
    setSport(s);
    setStatType(null);
    setLine(null);
    setSegment("hitter");
  }, []);

  // Filtered + sorted picks for scanner
  const filtered = useMemo(() => {
    // grade filter overrides stat/line filters: show ALL goblins of that grade, sorted by model prob
    if (gradeFilter !== "all") {
      let g = segmentPicks.filter(p => p.grade === gradeFilter);
      g.sort((a, b) => (b.model_prob || 0) - (a.model_prob || 0));
      return g;
    }
    // v2_tier filter — a separate, unvalidated heuristic scale from goblin
    // grade. Excludes goblin rows: they carry a v2_tier value too (computed
    // unconditionally server-side) but it's not the scale they're graded on,
    // so mixing them in here would let e.g. a LOCK goblin double up under an
    // unrelated "DECENT" bucket.
    if (tierFilter !== "all") {
      let t = segmentPicks.filter(p => p.tier === tierFilter && !p.is_goblin);
      t.sort((a, b) => (b.score || 0) - (a.score || 0));
      return t;
    }
    let f = segmentPicks.filter(p => p.stat_type === activeStatType);
    if (activeLine !== null) f = f.filter(p => p.line === activeLine);
    f.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      const na = typeof av === "string" ? parseFloat(av) : av;
      const nb = typeof bv === "string" ? parseFloat(bv) : bv;
      const aNull = na == null || isNaN(na);
      const bNull = nb == null || isNaN(nb);
      if (aNull && bNull) return 0;
      if (aNull) return 1;   // nulls always sink
      if (bNull) return -1;
      return sortDir === "desc" ? nb - na : na - nb;
    });
    return f;
  }, [segmentPicks, activeStatType, activeLine, sortBy, sortDir, gradeFilter, tierFilter]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir("desc"); }
  };

  const addToBuilder = (pick) => {
    if (builderLegs.find(l => l.player === pick.player && l.stat_type === pick.stat_type)) return;
    setBuilderLegs(prev => [...prev, pick]);
  };
  const removeFromBuilder = (idx) => {
    setBuilderLegs(prev => prev.filter((_, i) => i !== idx));
  };

  // ─── Tab Icons (inline SVGs) ──────────────────────────────────────────────

  const tabIcons = {
    Scanner: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>,
    Sharp: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>,
    Builder: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
    Moneylines: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>,
  };

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div style={{
      background: C.bg, color: C.text, minHeight: "100vh",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      display: "flex", flexDirection: "column", maxWidth: 480, margin: "0 auto",
      position: "relative", paddingBottom: 70,
    }}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{ padding: "16px 16px 0" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: `linear-gradient(150deg, ${C.gold}, #c77f1e)`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 800, fontSize: 18, color: "#1a1206",
            }}>T</div>
            <div>
              <div style={{ fontWeight: 600, fontSize: 17, letterSpacing: 0.3 }}>TANK'D PICKS</div>
              <div style={{ fontSize: 9.5, color: C.textDim, letterSpacing: 2, textTransform: "uppercase", marginTop: 1 }}>MLB · AI scanner</div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%",
              background: C.green, boxShadow: `0 0 6px ${C.green}`,
            }} />
            <span style={{ fontSize: 11, color: C.textDim }}>Live</span>
          </div>
        </div>

        {(activeMeta.last_scan || activeMeta.model_trained_at) && (() => {
          const modelDays = daysSince(activeMeta.model_trained_at);
          const modelStale = modelDays != null && modelDays > 14;
          return (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, fontSize: 10, color: C.textDim }}>
              {activeMeta.last_scan && (
                <span>Board as of {formatAsOf(activeMeta.last_scan)}</span>
              )}
              {activeMeta.model_trained_at && (
                <span style={{ color: modelStale ? C.red : C.textDim }}>
                  · Model trained {formatAsOf(activeMeta.model_trained_at)}
                  {modelStale ? ` (${modelDays}d ago)` : ""}
                </span>
              )}
              {activeMeta.api_version && (
                <span style={{ marginLeft: "auto", fontFamily: FONT_MONO, opacity: 0.7 }}>v{activeMeta.api_version}</span>
              )}
            </div>
          );
        })()}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, padding: "0 12px", marginTop: 12 }}>
        {hasError && !loading && (tab === "Scanner" || tab === "Sharp") ? (
          <PicksErrorState sport={sport} onRetry={retry} />
        ) : (
          <>
            {tab === "Scanner" && (
              <ScannerTab
                sport={sport} segment={segment} setSegment={setSegment}
                statTypes={statTypes} activeStatType={activeStatType} setStatType={setStatType}
                lines={lines} activeLine={activeLine} setLine={setLine}
                filtered={filtered} sortBy={sortBy} sortDir={sortDir} toggleSort={toggleSort} setSortBy={setSortBy} setSortDir={setSortDir}
                gradeFilter={gradeFilter} setGradeFilter={setGradeFilter}
                tierFilter={tierFilter} setTierFilter={setTierFilter}
                addToBuilder={addToBuilder}
              />
            )}
            {tab === "Sharp" && <SharpTab picks={picks} sport={sport} />}
            {tab === "Builder" && (
              <BuilderTab legs={builderLegs} removeLeg={removeFromBuilder} clearAll={() => setBuilderLegs([])} />
            )}
            {tab === "Moneylines" && <MoneylineTab />}
          </>
        )}
      </div>

      {/* ── Bottom Nav ───────────────────────────────────────────────────── */}
      <div style={{
        position: "fixed", bottom: 0, left: "50%", transform: "translateX(-50%)",
        width: "100%", maxWidth: 480,
        background: "linear-gradient(to top, #0e1116 72%, transparent)",
        paddingTop: 20,
      }}>
        <div style={{
          display: "flex", justifyContent: "space-around",
          background: "#11161d", borderTop: `1px solid ${C.line}`,
          padding: "8px 0 12px",
        }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none", cursor: "pointer",
              display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
              color: tab === t ? C.gold : C.textDim, transition: "color 0.15s",
              padding: "4px 12px",
            }}>
              {tabIcons[t]}
              <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: 0.3 }}>{t}</span>
              {t === "Builder" && builderLegs.length > 0 && (
                <span style={{
                  position: "absolute", marginTop: -8, marginLeft: 16,
                  width: 16, height: 16, borderRadius: "50%",
                  background: C.gold, color: "#1a1206", fontSize: 9, fontWeight: 800,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>{builderLegs.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Scanner Tab ─────────────────────────────────────────────────────────────

function ScannerTab({ sport, segment, setSegment, statTypes, activeStatType, setStatType, lines, activeLine, setLine, filtered, sortBy, sortDir, toggleSort, setSortBy, setSortDir, addToBuilder, gradeFilter, setGradeFilter, tierFilter, setTierFilter }) {
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [search, setSearch] = useState("");
  const [sortOpen, setSortOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);

  // Incremental render — the per-stat cap was raised 25 -> 1000 server-side
  // (see api/server.py) so every eligible pick is now fetched, but mounting
  // hundreds of cards (each with a headshot + expandable detail section of
  // variable height, which rules out fixed-row virtualization) at once would
  // be janky on mobile. Render BATCH_SIZE at a time and grow via an
  // IntersectionObserver sentinel as the user scrolls near the bottom —
  // sorting/filtering still runs over the FULL fetched set (see `filtered`
  // above); this only controls how much of that already-correct result is
  // mounted to the DOM.
  const BATCH_SIZE = 30;
  const [visibleCount, setVisibleCount] = useState(BATCH_SIZE);
  const sentinelRef = useRef(null);

  const shown = useMemo(
    () => filtered.filter(p => !search || p.player.toLowerCase().includes(search.toLowerCase())),
    [filtered, search]
  );

  // Reset to the first batch whenever the result set changes underneath us
  // (stat/line/segment/grade/tier filter, sort, or search) so switching
  // context is always a fast, small first paint.
  useEffect(() => { setVisibleCount(BATCH_SIZE); }, [filtered, search]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) setVisibleCount(c => c + BATCH_SIZE); },
      { rootMargin: "400px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [visibleCount, shown.length]);
  const SortArrow = ({ col }) => {
    if (sortBy !== col) return null;
    return <span style={{ marginLeft: 2, fontSize: 9 }}>{sortDir === "desc" ? "▼" : "▲"}</span>;
  };

  return (
    <>
      {/* Hitter / Pitcher segment toggle (MLB only) */}
      {sport === "MLB" && (
        <div style={{ display: "flex", gap: 3, background: C.card2, borderRadius: 9, padding: 3, marginBottom: 10, border: `1px solid ${C.line}` }}>
          {["hitter", "pitcher"].map(seg => (
            <button key={seg} onClick={() => setSegment(seg)} style={{
              flex: 1, padding: "8px 0", borderRadius: 6, border: "none", cursor: "pointer",
              fontSize: 13, fontWeight: 600, letterSpacing: 0.3,
              background: segment === seg ? C.gold : "transparent",
              color: segment === seg ? "#1a1206" : C.textDim,
              transition: "all 0.15s",
            }}>{seg === "hitter" ? "Hitters" : "Pitchers"}</button>
          ))}
        </div>
      )}

      {/* Grade/tier filter — one consolidated dropdown (was two parallel
          button rows: goblin grade LOCK/STRONG/LEAN and score-tier
          ELITE/STRONG/DECENT/LEAN, which put "STRONG"/"LEAN" on screen twice
          and read as one confusing control). Same expand/collapse pattern as
          the Sort dropdown below. Options stay grouped under labeled headers
          and internally tagged by system, so the two unrelated STRONG/LEAN
          scales never merge into a single filter value. MLB gets both groups
          (goblin grading is MLB-only); other sports get tier only, since
          v2_tier is computed for every sport but goblins aren't. */}
      {(() => {
        const FILTER_GROUPS = sport === "MLB"
          ? [
              { system: "grade", header: "Goblin grade", tag: "calibrated %", options: ["LOCK", "STRONG", "LEAN", "FLOOR"] },
              { system: "tier",  header: "Score tier",    tag: "heuristic",   options: ["ELITE", "STRONG", "DECENT", "LEAN"] },
            ]
          : [
              { system: "tier",  header: "Score tier",    tag: "heuristic",   options: ["ELITE", "STRONG", "DECENT", "LEAN"] },
            ];
        const activeSystem = gradeFilter !== "all" ? "grade" : (tierFilter !== "all" ? "tier" : null);
        const activeValue = activeSystem === "grade" ? gradeFilter : (activeSystem === "tier" ? tierFilter : "All");
        const activeColor = activeSystem === "grade" ? tierColors(activeValue)
          : activeSystem === "tier" ? { fg: TIER_COLORS[activeValue] || C.textDim, bg: TIER_BG[activeValue] || C.card2, bd: C.line2 }
          : { fg: C.text, bg: C.line2, bd: C.line2 };
        const selectFilter = (system, value) => {
          setGradeFilter(system === "grade" ? value : "all");
          setTierFilter(system === "tier" ? value : "all");
          setFilterOpen(false);
        };
        return (
          <div style={{ marginBottom: 10 }}>
            <div style={{ position: "relative" }}>
              <button onClick={() => setFilterOpen(o => !o)} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%",
                padding: "8px 11px", borderRadius: 8, cursor: "pointer",
                fontFamily: FONT_COND, fontSize: 13, fontWeight: 600,
                background: activeSystem ? activeColor.bg : C.card2,
                color: activeSystem ? activeColor.fg : C.text,
                border: `1px solid ${activeSystem ? activeColor.bd : C.line2}`,
              }}>
                <span>Filter: <span style={{ fontWeight: 800 }}>{activeValue}</span></span>
                <span style={{ fontSize: 9 }}>▼</span>
              </button>
              {filterOpen && (
                <div style={{
                  position: "absolute", top: "calc(100% + 5px)", left: 0, right: 0, zIndex: 30,
                  background: C.card, border: `1px solid ${C.line2}`, borderRadius: 10, padding: 5,
                  boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                }}>
                  <div onClick={() => selectFilter(null, "all")} style={{
                    padding: "8px 11px", borderRadius: 6, cursor: "pointer",
                    fontFamily: FONT_COND, fontSize: 14,
                    color: !activeSystem ? C.gold : C.textDim,
                  }}
                    onMouseEnter={e => { if (activeSystem) e.currentTarget.style.color = C.text; }}
                    onMouseLeave={e => { if (activeSystem) e.currentTarget.style.color = C.textDim; }}
                  >All</div>
                  {FILTER_GROUPS.map(g => (
                    <div key={g.system}>
                      <div style={{
                        padding: "10px 11px 3px", fontFamily: FONT_MONO, fontSize: 9,
                        color: C.dim2 || "#5c6672", letterSpacing: 1, textTransform: "uppercase",
                      }}>{g.header} <span style={{ opacity: 0.7 }}>· {g.tag}</span></div>
                      {g.options.map(opt => {
                        const isActive = activeSystem === g.system && activeValue === opt;
                        return (
                          <div key={g.system + opt} onClick={() => selectFilter(g.system, opt)} style={{
                            padding: "8px 11px", borderRadius: 6, cursor: "pointer",
                            fontFamily: FONT_COND, fontSize: 14,
                            color: isActive ? C.gold : C.textDim,
                          }}
                            onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = C.text; }}
                            onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = C.textDim; }}
                          >{opt}</div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}
            </div>
            {activeSystem === "grade" && (
              <div style={{ fontSize: 10, color: C.textDim, marginTop: 6, textAlign: "center" }}>
                model hit-rate estimate · goblins only · 14-day sample
              </div>
            )}
            {activeSystem === "tier" && (
              <div style={{ fontSize: 10, color: C.textDim, marginTop: 6, textAlign: "center" }}>
                heuristic score tier · non-goblin picks
              </div>
            )}
          </div>
        );
      })()}

      {/* Stat type chips */}
      <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 8, WebkitOverflowScrolling: "touch" }}>
        {statTypes.map(st => (
          <button key={st} onClick={() => { setStatType(st); setLine(null); }} style={{
            whiteSpace: "nowrap", padding: "6px 14px", borderRadius: 20, border: "none", cursor: "pointer",
            fontSize: 12, fontWeight: 600, flexShrink: 0, transition: "all 0.15s",
            background: activeStatType === st ? C.gold : C.card2,
            color: activeStatType === st ? "#1a1206" : C.textDim,
            border: `1px solid ${activeStatType === st ? C.gold : C.line}`,
          }}>{st}</button>
        ))}
      </div>

      {/* Line selector — compact chips */}
      {lines.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 11 }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.textDim, letterSpacing: 1, flexShrink: 0 }}>LINE</span>
          <div style={{ display: "flex", gap: 5, flex: 1, overflowX: "auto" }}>
            {lines.map(l => (
              <button key={l} onClick={() => setLine(l)} style={{
                minWidth: 52, padding: "8px 0", borderRadius: 8, cursor: "pointer", border: "none",
                fontFamily: FONT_MONO, fontSize: 14, fontWeight: 700, fontVariantNumeric: "tabular-nums",
                transition: "all 0.15s", flex: "0 0 auto",
                background: activeLine === l ? C.line2 : C.card2,
                color: activeLine === l ? C.text : C.textDim,
                border: `1px solid ${activeLine === l ? C.line2 : C.line}`,
              }}>{l}</button>
            ))}
          </div>
        </div>
      )}

      {/* Player search */}
      <div style={{ marginBottom: 10 }}>
        <input
          type="text"
          placeholder="Search player..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setExpandedIdx(null); }}
          style={{
            width: "100%", padding: "8px 12px", borderRadius: 8,
            border: "1px solid " + C.border, background: "#0d1520",
            color: C.text, fontSize: 13, outline: "none",
          }}
        />
      </div>

      {/* Sort bar */}
      {(() => {
        const SORT_OPTS = [
          { key: "score",    label: "Score",  tag: "model" },
          { key: "ai_proj",  label: "Projection", tag: "AI proj" },
          { key: "ops_vs",   label: "OPS vs pitcher", tag: "matchup" },
          { key: "avg_vs",   label: "BA vs pitcher",  tag: "matchup" },
          { key: "k_pct_vs", label: "K% vs pitcher",  tag: "matchup" },
          { key: "edge",     label: "Edge",   tag: "proj\u2212line" },
          { key: "l10",      label: "L10 form", tag: "" },
        ];
        const active = SORT_OPTS.find(o => o.key === sortBy) || SORT_OPTS[0];
        const isMatchup = ["ops_vs","avg_vs","k_pct_vs"].includes(sortBy);
        return (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 11 }}>
            <div style={{ fontFamily: FONT_MONO, fontSize: 10, color: C.textDim, letterSpacing: 1 }}>
              {isMatchup ? <span>ranked by <span style={{ color: C.gold }}>{active.label}</span></span> : "Today's board"}
            </div>
            <div style={{ position: "relative" }}>
              <button onClick={() => setSortOpen(o => !o)} style={{
                display: "flex", alignItems: "center", gap: 6, padding: "7px 11px", borderRadius: 8, cursor: "pointer",
                fontFamily: FONT_COND, fontSize: 13, fontWeight: 600, background: C.card2, color: C.text,
                border: `1px solid ${C.line2}`,
              }}>
                Sort: <span style={{ color: C.gold }}>{active.label.replace(" pitcher","").replace(" form","")}</span>
                <span style={{ fontSize: 9, color: C.textDim }}>▼</span>
              </button>
              {sortOpen && (
                <div style={{
                  position: "absolute", top: "calc(100% + 5px)", right: 0, zIndex: 30,
                  background: C.card, border: `1px solid ${C.line2}`, borderRadius: 10, padding: 5,
                  minWidth: 165, boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                }}>
                  {SORT_OPTS.map(o => (
                    <div key={o.key} onClick={() => { setSortBy(o.key); setSortDir("desc"); setSortOpen(false); }}
                      style={{
                        padding: "8px 11px", borderRadius: 6, cursor: "pointer",
                        fontFamily: FONT_COND, fontSize: 14,
                        color: sortBy === o.key ? C.gold : C.textDim,
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                      }}
                      onMouseEnter={e => { if (sortBy !== o.key) e.currentTarget.style.color = C.text; }}
                      onMouseLeave={e => { if (sortBy !== o.key) e.currentTarget.style.color = C.textDim; }}
                    >
                      {o.label}
                      {o.tag && <span style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.dim2 || "#5c6672" }}>{o.tag}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* Picks List */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {shown.length === 0 && (
          <div style={{ textAlign: "center", padding: 40, color: C.textDim, fontSize: 13 }}>
            {search
              ? "No players match " + search
              : gradeFilter !== "all"
                ? `No ${gradeFilter} picks right now`
                : tierFilter !== "all"
                  ? `No ${tierFilter} picks right now`
                  : "No picks for this line yet"}
          </div>
        )}
        {shown.slice(0, visibleCount).map((pick, i) => (
          <div key={`${pick.player}-${pick.stat_type}-${pick.line}`}
            onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
            style={{
              background: "#161b22", borderRadius: 14, overflow: "hidden",
              border: `1px solid ${C.line}`, borderLeft: "none", cursor: "pointer",
              transition: "border-color 0.15s", display: "flex", marginBottom: 11,
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.line2}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.line}
          >
            <div style={{ width: 5, flexShrink: 0, background: teamColor(pick.team) }} />
            <div style={{ flex: 1, padding: "13px 14px", minWidth: 0 }}>
            {/* Top row: player info + score */}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <PlayerAvatar name={pick.player} team={pick.team} headshot={pick.headshot} mlbId={pick.mlb_id} size={52} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: FONT_DISPLAY, fontWeight: 600, fontSize: 18, letterSpacing: 0.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.player}</span>
                  {pick.team && <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: teamColor(pick.team), fontWeight: 700, letterSpacing: 1 }}>{pick.team}</span>}
                </div>
                <div style={{ fontFamily: FONT_COND, fontSize: 14, color: C.textDim, marginTop: 2, fontWeight: 500 }}>
                  <span style={{ color: (pick.side || "").toLowerCase() === "over" ? C.green : C.red, fontWeight: 700 }}>{pick.side}</span>
                  {" "}<b style={{ color: C.text, fontWeight: 700 }}>{pick.line}</b> {pick.stat_type}{pick.is_goblin ? " \u00B7 goblin" : ""}
                </div>
                {(() => {
                  const lens = { ops_vs: ["OPS", pick.ops_vs, 3], avg_vs: ["BA", pick.avg_vs, 3], k_pct_vs: ["K%", pick.k_pct_vs, 0] }[sortBy];
                  if (!lens || lens[1] == null) return null;
                  const [lbl, val, dec] = lens;
                  const tc = teamColor(pick.team);
                  const shown = lbl === "BA" ? Number(val).toFixed(3).replace(/^0/, "") : (lbl === "K%" ? Math.round(val) + "%" : Number(val).toFixed(3));
                  return (
                    <div style={{ display: "inline-flex", alignItems: "baseline", gap: 5, marginTop: 5, padding: "3px 9px", borderRadius: 6,
                      background: `${tc}22`, border: `1px solid ${tc}66` }}>
                      <span style={{ fontFamily: FONT_MONO, fontSize: 13, fontWeight: 800, color: tc }}>{shown}</span>
                      <span style={{ fontFamily: FONT_COND, fontSize: 11, color: C.textDim, fontWeight: 600 }}>{lbl} vs pitcher</span>
                      {pick.ab_vs != null && <span style={{ fontFamily: FONT_MONO, fontSize: 9, color: C.dim2 || "#5c6672" }}>{pick.ab_vs} AB</span>}
                    </div>
                  );
                })()}
              </div>
              {/* Confidence chip — honest tier + calibrated % */}
              {(() => {
                const cd = pick.model_prob != null ? confDisplay(pick.model_prob) : null;
                // Badge must agree with the LOCK/STRONG/LEAN filter tabs, which
                // key off pick.grade (server-computed, and overridden to "FLOOR"
                // for trivial <=0.5 lines). Recomputing tier from raw model_prob
                // here caused floor bets to render "LOCK" while the LOCK filter
                // (correctly) excluded them.
                const tier = pick.grade || (cd ? cd.tier : (pick.tier || ""));
                // pick.grade (goblin model) and pick.tier (v2_tier, computed
                // in features/pipeline.py from score/edge/consistency) are two
                // unrelated scales that happen to share the words STRONG/LEAN.
                // The LOCK/STRONG/LEAN filter tabs only ever match pick.grade
                // (goblins only, see the "goblins only" note above them), so
                // styling a v2_tier "STRONG"/"LEAN" badge with the same
                // gold/teal "graded" palette falsely implies it's filterable
                // under that tab. Route ungraded picks through the separate
                // TIER_COLORS/TIER_BG palette so they read as visually distinct.
                const tc = pick.grade
                  ? tierColors(tier)
                  : { fg: TIER_COLORS[tier] || C.textDim, bg: TIER_BG[tier] || C.card2, bd: C.line2 };
                // The number itself must also read distinctly: a goblin's cd.pct
                // is a calibrated win probability, but pick.score is an unscaled
                // 0-100 heuristic (edge/consistency/streak) with no probabilistic
                // meaning \u2014 showing it the same size/weight/color as a calibrated
                // % implied it was one. De-emphasize it and label the unit so it
                // can't be misread as a %.
                const isCalibrated = cd && cd.pct != null;
                return (
                  <div style={{ flexShrink: 0, textAlign: "center", minWidth: 56 }}>
                    <div style={{ fontFamily: FONT_MONO, fontSize: isCalibrated ? 23 : 19, fontWeight: 800, color: isCalibrated ? C.text : C.textDim, lineHeight: 1, letterSpacing: -1, fontVariantNumeric: "tabular-nums" }}>
                      {isCalibrated
                        ? cd.pct + "%"
                        : (pick.score != null
                            ? <>{pick.score}<span style={{ fontSize: 10, fontWeight: 700, marginLeft: 2, color: C.textDim }}>SC</span></>
                            : "\u2014")}
                    </div>
                    <div style={{ marginTop: 5, fontFamily: FONT_COND, fontSize: 10, fontWeight: 700, letterSpacing: 0.8, padding: "2px 0", borderRadius: 5, color: tc.fg, background: tc.bg, border: `1px solid ${tc.bd}` }}>
                      {tier || "SC"}
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Stats row */}
            <div style={{ display: "flex", alignItems: "flex-start", gap: 1, marginTop: 13, background: C.line, borderRadius: 9, overflow: "hidden" }}>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px" }}>
                <StatCell value={pick.l5} frac={pick.l5_frac} label="L5" line={pick.line} side={pick.side} />
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px" }}>
                <StatCell value={pick.l10} frac={pick.l10_frac} label="L10" line={pick.line} side={pick.side} />
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center", opacity: pick.split_is_live === false ? 0.55 : 1 }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>
                  OPS vs{pick.split_is_live === false && <span title="Season average — live vs-hand splits unavailable"> · szn</span>}
                </div>
                <div style={{ color: pick.ops_vs == null ? C.textDim : (pick.ops_vs >= 0.800 ? C.green : pick.ops_vs <= 0.600 ? C.red : C.text), fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {pick.ops_vs != null ? pick.ops_vs.toFixed(3) : "—"}
                </div>
                {/* Sample size (PA vs this hand) — the Savant pull was widened
                    from qualified-hitter-only (min=q, ~300+ season PA) to a
                    20-PA floor to cover far more players; this discloses how
                    thin any given row's sample is instead of hiding it. */}
                {pick.ab_vs != null && <div style={{ color: C.textDim, fontSize: 9, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>{pick.ab_vs} PA</div>}
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center", opacity: pick.split_is_live === false ? 0.55 : 1 }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>
                  BA vs{pick.split_is_live === false && <span title="Season average — live vs-hand splits unavailable"> · szn</span>}
                </div>
                <div style={{ color: pick.avg_vs == null ? C.textDim : (pick.avg_vs >= 0.300 ? C.green : pick.avg_vs <= 0.220 ? C.red : C.text), fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {pick.avg_vs != null ? pick.avg_vs.toFixed(3).replace(/^0/, "") : "—"}
                </div>
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Edge</div>
                {/* thresholds tuned to the live Edge_Pct/v2_edge percentage distribution
                    (median ~55%, 75th pct ~74%, 25th pct ~31% as of 2026-07-06 scan) —
                    not the old raw-unit (AI_Proj-PP_Line) scale this used to be on */}
                <div style={{ color: pick.edge >= 70 ? C.green : pick.edge >= 40 ? C.gold : C.red, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {pick.edge >= 0 ? "+" : ""}{pick.edge.toFixed(1)}%
                </div>
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Proj</div>
                <div style={{ color: C.text, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{pick.ai_proj}</div>
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>PF</div>
                {(() => { const pf = formatPF(pick.park_factor); return (
                  <div style={{ color: pf.neutral ? C.textDim : (pick.park_factor > 100 ? C.green : C.red), fontWeight: 600, fontSize: 14, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{pf.txt}</div>
                ); })()}
              </div>
            </div>

            {/* Detail panel */}
            {expandedIdx === i ? (
              <div style={{ marginTop: 10, borderTop: "1px solid " + C.border, paddingTop: 10 }}>
                {pick.opp_pitcher && (
                  <div style={{ display: "flex", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 11 }}>
                      <span style={{ color: C.textDim }}>vs </span>
                      <span style={{ fontWeight: 700, color: C.text }}>{pick.opp_pitcher}</span>
                      {pick.pitch_hand && <span style={{ color: C.textDim }}> ({pick.pitch_hand}HP)</span>}
                    </div>
                    {pick.opp_team && pick.opp_team !== "NAN" && (
                      <div style={{ fontSize: 11, color: C.textDim }}>@ {pick.opp_team}</div>
                    )}
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginBottom: 8 }}>
                  {pick.ops_vs != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center", opacity: pick.split_is_live === false ? 0.55 : 1 }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>OPS vs{pick.split_is_live === false ? " · szn" : ""}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: pick.ops_vs >= 0.800 ? C.green : pick.ops_vs <= 0.600 ? C.red : C.text }}>{pick.ops_vs.toFixed(3)}</div>
                    </div>
                  )}
                  {pick.avg_vs != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center", opacity: pick.split_is_live === false ? 0.55 : 1 }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>BA vs{pick.split_is_live === false ? " · szn" : ""}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: pick.avg_vs >= 0.300 ? C.green : pick.avg_vs <= 0.220 ? C.red : C.text }}>{pick.avg_vs.toFixed(3).replace(/^0/, "")}</div>
                    </div>
                  )}
                  {pick.k_pct_vs != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center", opacity: pick.split_is_live === false ? 0.55 : 1 }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>K% vs{pick.split_is_live === false ? " · szn" : ""}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: pick.k_pct_vs >= 25 ? C.red : pick.k_pct_vs <= 15 ? C.green : C.text }}>{pick.k_pct_vs}%</div>
                    </div>
                  )}
                  {pick.temp_f != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>Temp</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{pick.temp_f}°F</div>
                    </div>
                  )}
                  {pick.wind_speed != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>Wind</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{pick.wind_speed} mph</div>
                    </div>
                  )}
                  {pick.game_total != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>O/U</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{pick.game_total}</div>
                    </div>
                  )}
                  {pick.streak != null && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>Streak</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: pick.streak > 0 ? C.green : C.red }}>{pick.streak > 0 ? "+" : ""}{pick.streak}</div>
                    </div>
                  )}
                  {pick.weather_adj != null && pick.weather_adj !== 1.0 && (
                    <div style={{ background: "rgba(100,116,139,0.08)", borderRadius: 8, padding: "6px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>Wx Adj</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: pick.weather_adj > 1 ? C.green : C.red }}>{pick.weather_adj.toFixed(2)}</div>
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  {pick.is_goblin && <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: "rgba(168,85,247,0.2)", color: "#a855f7", fontWeight: 600 }}>Goblin Mode</span>}
                  {pick.is_demon && <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: "rgba(239,68,68,0.2)", color: "#ef4444", fontWeight: 600 }}>Demon</span>}
                </div>
                <button onClick={(e) => { e.stopPropagation(); addToBuilder(pick); }} style={{
                  width: "100%", padding: "11px 0", borderRadius: 9, border: "none", cursor: "pointer",
                  background: C.gold, color: "#1a1206", fontWeight: 600, fontSize: 13, letterSpacing: 0.2,
                }}>+ Add to builder</button>
              </div>
            ) : (
              <div style={{ textAlign: "center", marginTop: 8, fontSize: 10, color: C.textDim, opacity: 0.5 }}>
                Tap for details
              </div>
            )}
            </div>
          </div>
        ))}
        {visibleCount < shown.length && (
          <div ref={sentinelRef} style={{ textAlign: "center", padding: 20, color: C.textDim, fontSize: 11 }}>
            Loading more… ({visibleCount} of {shown.length})
          </div>
        )}
      </div>
    </>
  );
}

// ─── Sharp Tab ───────────────────────────────────────────────────────────────

function SharpTab({ picks, sport }) {
  const sharp = (picks || []).filter(p => p.sharp);

  if (sport !== "MLB") {
    return <div style={{ padding: 32, textAlign: "center", color: C.textDim }}>
      Sharp board is MLB pitcher props only.
    </div>;
  }

  return (
    <div>
      {/* Honest context header */}
      <div style={{
        background: "linear-gradient(135deg, rgba(34,197,94,0.12), rgba(34,197,94,0.04))",
        border: `1px solid ${C.green}44`, borderRadius: 12, padding: 14, marginBottom: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 16, fontWeight: 800, color: C.green, letterSpacing: 0.5 }}>⚡ SHARP</span>
          <span style={{
            fontSize: 13, fontWeight: 800, color: "#000", background: C.green,
            padding: "3px 10px", borderRadius: 6, fontVariantNumeric: "tabular-nums",
          }}>{sharp.length} today</span>
        </div>
        <div style={{ fontSize: 11, color: C.text, lineHeight: 1.5 }}>
          K / Outs props where the model disagrees with the line by 2+.
        </div>
        <div style={{ fontSize: 10, color: C.textDim, lineHeight: 1.5, marginTop: 4 }}>
          81% over 32 backtested picks · last 14 days · small sample, will regress · goblin payouts reduced · not financial advice
        </div>
      </div>

      {sharp.length === 0 ? (
        <div style={{
          background: C.card, borderRadius: 12, padding: 36, textAlign: "center",
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>🛑</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>No sharp plays today</div>
          <div style={{ fontSize: 12, color: C.textDim }}>
            The model has no edge-2+ pitcher plays on this slate. Sitting out is a position.
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {sharp.map((p, i) => {
            const typ = p.is_goblin ? "GOBLIN" : "STD";
            return (
              <div key={p.player + "-" + p.stat_type + "-" + i} style={{
                background: C.card, borderRadius: 12, padding: "12px 14px",
                border: `1px solid ${C.green}66`,
                boxShadow: `0 0 14px rgba(34,197,94,0.18)`,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <PlayerAvatar name={p.player} team={p.team} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontWeight: 700, fontSize: 14 }}>{p.player}</span>
                      <span style={{
                        fontSize: 9, fontWeight: 800, padding: "2px 6px", borderRadius: 4,
                        background: p.is_goblin ? "rgba(168,85,247,0.2)" : "rgba(100,116,139,0.2)",
                        color: p.is_goblin ? "#a855f7" : C.textDim,
                      }}>{typ}</span>
                    </div>
                    <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
                      {p.side} {p.line} {p.stat_type}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>Edge</div>
                    <div style={{
                      fontSize: 18, fontWeight: 800, color: C.green, fontVariantNumeric: "tabular-nums",
                    }}>{p.edge > 0 ? "+" : ""}{p.edge.toFixed(1)}%</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 11, color: C.textDim }}>
                  <span>proj <b style={{ color: C.text }}>{p.ai_proj}</b></span>
                  <span>L5 <b style={{ color: C.text }}>{p.l5}</b></span>
                  <span>L10 <b style={{ color: C.text }}>{p.l10}</b></span>
                  {p.opp_team && p.opp_team !== "NAN" && <span>vs <b style={{ color: C.text }}>{p.opp_team}</b></span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Trends Tab ──────────────────────────────────────────────────────────────

function TrendsTab({ picks, sport }) {
  const [tStat, setTStat] = React.useState(null);
  const [tLine, setTLine] = React.useState(null);

  const statTypes = React.useMemo(
    () => [...new Set(picks.map(p => p.stat_type))].sort(),
    [picks]
  );
  const activeStat = tStat && statTypes.includes(tStat) ? tStat : statTypes[0];

  const lines = React.useMemo(
    () => [...new Set(picks.filter(p => p.stat_type === activeStat).map(p => p.line))].sort((a, b) => a - b),
    [picks, activeStat]
  );
  const activeLine = tLine !== null && lines.includes(tLine) ? tLine : (lines[0] ?? null);

  const rows = React.useMemo(() => {
    let f = picks.filter(p => p.stat_type === activeStat);
    if (activeLine !== null) f = f.filter(p => p.line === activeLine);
    return f.slice().sort((a, b) => (b.edge || 0) - (a.edge || 0));
  }, [picks, activeStat, activeLine]);

  if (!picks.length) {
    return <div style={{ padding: 24, textAlign: "center", color: C.textDim }}>No picks available.</div>;
  }

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Trends by Stat</div>

      <select
        value={activeStat || ""}
        onChange={e => { setTStat(e.target.value); setTLine(null); }}
        style={{
          width: "100%", padding: "10px 12px", borderRadius: 10,
          background: "#0d1520", color: C.text, border: `1px solid ${C.border}`,
          fontSize: 14, fontWeight: 700, marginBottom: 10, cursor: "pointer",
        }}
      >
        {statTypes.map(s => <option key={s} value={s}>{s}</option>)}
      </select>

      <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 10 }}>
        {lines.map(l => (
          <button key={l} onClick={() => setTLine(l)} style={{
            whiteSpace: "nowrap", padding: "6px 14px", borderRadius: 8, border: "none", cursor: "pointer",
            fontSize: 12, fontWeight: 700, flexShrink: 0,
            background: activeLine === l ? C.green : "#1a2736",
            color: activeLine === l ? "#000" : C.textDim,
          }}>{l}</button>
        ))}
      </div>

      <div style={{ fontSize: 11, color: C.textDim, marginBottom: 8 }}>
        {rows.length} players · {activeStat} {activeLine !== null ? activeLine : ""} · ranked by edge
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.map((p, i) => (
          <div key={p.player + "-" + p.line + "-" + i} style={{
            background: C.card, borderRadius: 10, padding: 12, border: `1px solid ${C.border}`,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: C.textDim, width: 22, textAlign: "center" }}>{i + 1}</div>
            <PlayerAvatar name={p.player} team={p.team} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.player}</div>
              <div style={{ fontSize: 11, color: C.textDim }}>{p.team} · {p.side} {p.line}</div>
            </div>
            <div style={{ textAlign: "center", minWidth: 50 }}>
              <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase" }}>Edge</div>
              <div style={{ fontWeight: 800, fontSize: 15, color: C.green }}>{(p.edge || 0).toFixed(1)}%</div>
            </div>
            <div style={{ textAlign: "center", minWidth: 40 }}>
              <div style={{ fontSize: 9, color: C.textDim, textTransform: "uppercase" }}>SC</div>
              <div style={{ fontWeight: 800, fontSize: 15, color: scoreColor(p.score) }}>{Math.round(p.score || 0)}</div>
            </div>
            {p.tier ? <TierBadge tier={p.tier} /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function BuilderTab({ legs, removeLeg, clearAll, picks = [], addToBuilder }) {
  const [bStat, setBStat] = React.useState(null);
  const statTypes = React.useMemo(() => [...new Set(picks.map(p => p.stat_type))].sort(), [picks]);
  const activeStat = bStat && statTypes.includes(bStat) ? bStat : statTypes[0];
  const browseRows = React.useMemo(() => {
    return picks.filter(p => p.stat_type === activeStat)
      .slice().sort((a, b) => (b.edge || 0) - (a.edge || 0)).slice(0, 30);
  }, [picks, activeStat]);
  const inParlay = (p) => legs.some(l => l.player === p.player && l.stat_type === p.stat_type && l.line === p.line);
  const totalScore = legs.length > 0
    ? Math.round(legs.reduce((s, l) => s + l.score, 0) / legs.length)
    : 0;
  const avgEdge = legs.length > 0
    ? (legs.reduce((s, l) => s + l.edge, 0) / legs.length).toFixed(1)
    : "0.0";

  const legCount = legs.length;
  const parlayType = legCount <= 2 ? "Power Play" : legCount <= 4 ? "Flex Play" : "Demon Play";
  const isPromoCompatible = legCount >= 3 && legCount <= 6;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Parlay Builder</div>
        {legs.length > 0 && (
          <button onClick={clearAll} style={{
            background: C.redDim, color: C.red, border: "none",
            padding: "4px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer",
          }}>Clear All</button>
        )}
      </div>

      {/* Browse by stat — add legs directly */}
      {picks.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <select
            value={activeStat || ""}
            onChange={e => setBStat(e.target.value)}
            style={{
              width: "100%", padding: "10px 12px", borderRadius: 10,
              background: "#0d1520", color: C.text, border: `1px solid ${C.border}`,
              fontSize: 14, fontWeight: 700, marginBottom: 10, cursor: "pointer",
            }}
          >
            {statTypes.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 320, overflowY: "auto" }}>
            {browseRows.map((p, i) => {
              const added = inParlay(p);
              return (
                <div key={p.player + "-" + p.line + "-" + i} style={{
                  background: C.card, borderRadius: 10, padding: "8px 10px", border: `1px solid ${C.border}`,
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.player}</div>
                    <div style={{ fontSize: 10, color: C.textDim }}>
                      {p.side} {p.line}
                      {p.ops_vs != null ? " · OPS " + p.ops_vs.toFixed(3) : ""}
                      {p.avg_vs != null ? " · BA " + p.avg_vs.toFixed(3).replace(/^0/, "") : ""}
                      {p.k_pct_vs != null ? " · K% " + p.k_pct_vs : ""}
                      {p.split_is_live === false && (p.ops_vs != null || p.avg_vs != null || p.k_pct_vs != null) ? " (szn)" : ""}
                    </div>
                  </div>
                  <div style={{ textAlign: "center", minWidth: 38 }}>
                    <div style={{ fontSize: 8, color: C.textDim, textTransform: "uppercase" }}>Edge</div>
                    <div style={{ fontSize: 13, fontWeight: 800, color: C.green }}>{(p.edge || 0).toFixed(1)}%</div>
                  </div>
                  <div style={{ textAlign: "center", minWidth: 30 }}>
                    <div style={{ fontSize: 8, color: C.textDim, textTransform: "uppercase" }}>SC</div>
                    <div style={{ fontSize: 13, fontWeight: 800, color: scoreColor(p.score) }}>{Math.round(p.score || 0)}</div>
                  </div>
                  <button
                    onClick={() => !added && addToBuilder && addToBuilder(p)}
                    disabled={added}
                    style={{
                      border: "none", cursor: added ? "default" : "pointer",
                      borderRadius: 8, padding: "6px 10px", fontSize: 12, fontWeight: 800,
                      background: added ? "#1a2736" : C.green, color: added ? C.textDim : "#000",
                      flexShrink: 0,
                    }}
                  >{added ? "✓" : "+"}</button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {legs.length === 0 ? (
        <div style={{
          background: C.card, borderRadius: 12, padding: 40,
          border: `1px solid ${C.border}`, textAlign: "center",
        }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>🏗</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>No legs yet</div>
          <div style={{ fontSize: 12, color: C.textDim }}>Tap picks in Scanner to add legs</div>
        </div>
      ) : (
        <>
          {/* Summary card */}
          <div style={{
            background: "linear-gradient(135deg, #0d1520, #111d2d)",
            borderRadius: 12, padding: 16, marginBottom: 12,
            border: `1px solid ${C.green}33`,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: 1 }}>Legs</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.green }}>{legCount}</div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: 1 }}>Avg Score</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: scoreColor(totalScore), fontVariantNumeric: "tabular-nums" }}>{totalScore}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: 1 }}>Avg Edge</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.green, fontVariantNumeric: "tabular-nums" }}>+{avgEdge}%</div>
              </div>
            </div>
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              background: "#0a1019", borderRadius: 8, padding: "8px 12px",
            }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{parlayType}</span>
              <span style={{
                fontSize: 10, fontWeight: 700,
                color: isPromoCompatible ? C.green : C.yellow,
                background: isPromoCompatible ? C.greenDim : C.yellowDim,
                padding: "2px 8px", borderRadius: 4,
              }}>{isPromoCompatible ? "Promo OK" : "No Promo"}</span>
            </div>
            {!isPromoCompatible && legCount < 3 && (
              <div style={{ fontSize: 10, color: C.textDim, marginTop: 6, textAlign: "center" }}>
                Add {3 - legCount} more leg{3 - legCount > 1 ? "s" : ""} for promo eligibility
              </div>
            )}
          </div>

          {/* Leg cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {legs.map((leg, i) => (
              <div key={i} style={{
                background: C.card, borderRadius: 10, padding: "10px 12px",
                border: `1px solid ${C.border}`,
                display: "flex", alignItems: "center", gap: 10,
              }}>
                <div style={{
                  width: 24, height: 24, borderRadius: 6,
                  background: C.greenDim, display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 11, fontWeight: 800, color: C.green,
                }}>{i + 1}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{leg.player}</div>
                  <div style={{ fontSize: 11, color: C.textDim }}>{leg.side} {leg.line} {leg.stat_type}</div>
                </div>
                <div style={{
                  fontSize: 14, fontWeight: 800, color: scoreColor(leg.score),
                  fontVariantNumeric: "tabular-nums",
                }}>{leg.score}</div>
                <button onClick={() => removeLeg(i)} style={{
                  background: C.redDim, border: "none", cursor: "pointer",
                  width: 24, height: 24, borderRadius: 6,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: C.red, fontSize: 14, fontWeight: 700,
                }}>×</button>
              </div>
            ))}
          </div>

          {/* Note about promos */}
          <div style={{
            marginTop: 12, padding: "10px 14px", borderRadius: 10,
            background: C.yellowDim, border: `1px solid ${C.yellow}22`,
          }}>
            <div style={{ fontSize: 11, color: C.yellow, fontWeight: 600, marginBottom: 2 }}>Promo Rule</div>
            <div style={{ fontSize: 10, color: C.textDim, lineHeight: 1.5 }}>
              PrizePicks promos can't be paired with other promos. Use goblin or standard lines to complement.
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Moneylines Tab ──────────────────────────────────────────────────────────

// MLB Stats API team IDs, mirrored from src/sports/mlb/game_sim_live.py's
// TEAM_META/NAME_TO_ID (kept in sync manually — team IDs are static
// reference data, not a projection input). Used only to pre-select a
// matchup in the Sim Explorer link-out below; never touches pick data/logic.
const MLB_TEAM_IDS = {
  "Los Angeles Angels": 108, "Arizona Diamondbacks": 109, "Baltimore Orioles": 110,
  "Boston Red Sox": 111, "Chicago Cubs": 112, "Cincinnati Reds": 113,
  "Cleveland Guardians": 114, "Colorado Rockies": 115, "Detroit Tigers": 116,
  "Houston Astros": 117, "Kansas City Royals": 118, "Los Angeles Dodgers": 119,
  "Washington Nationals": 120, "New York Mets": 121, "Athletics": 133,
  "Pittsburgh Pirates": 134, "San Diego Padres": 135, "Seattle Mariners": 136,
  "San Francisco Giants": 137, "St. Louis Cardinals": 138, "Tampa Bay Rays": 139,
  "Texas Rangers": 140, "Toronto Blue Jays": 141, "Minnesota Twins": 142,
  "Philadelphia Phillies": 143, "Atlanta Braves": 144, "Chicago White Sox": 145,
  "Miami Marlins": 146, "New York Yankees": 147, "Milwaukee Brewers": 158,
};

// output/moneylines/latest.csv (built by smart_picks.py) keeps only ONE row
// per game — the recommended side, deduped by taking the highest Win% team
// per matchup. There is no "other side" odds/probability in this data source,
// so we render each row as a single pick (team @ opponent) rather than a
// two-team comparison the API doesn't actually provide.
function buildMoneylinePicks(rows) {
  return rows
    .filter(r => r.Team && r.Opponent)
    .map(r => ({
      team: r.Team,
      opponent: r.Opponent,
      teamAbbr: r.Team_Abbr || r.Team.slice(0, 3).toUpperCase(),
      opponentAbbr: r.Opponent_Abbr || r.Opponent.slice(0, 3).toUpperCase(),
      home: !!r.Home,
      odds: Math.round(Number(r["Avg Odds"]) || 0),
      bestOdds: Math.round(Number(r["Best Odds"]) || 0),
      bestBook: r["Best Book"] || "",
      // No independent confidence model backs moneylines (unlike player
      // props) — Win% (implied probability from the odds, vig not removed)
      // is the only real signal available, so SC reuses it directly on the
      // same 0-100 scale as the picks "score" field.
      winPct: Math.round(Number(r["Win %"]) || 0),
      gameTotal: r["Game Total"] != null && r["Game Total"] !== "" && !isNaN(r["Game Total"]) ? Number(r["Game Total"]) : null,
      books: r.Books != null && r.Books !== "" && !isNaN(r.Books) ? Number(r.Books) : null,
      time: r.Time || "",
      sport: r.Sport || "",
      // Sim Explorer deep-link IDs (MLB only) — null if either team isn't in
      // MLB_TEAM_IDS, so the link-out falls back to the Sim Explorer root.
      homeTeamId: r.Home ? (MLB_TEAM_IDS[r.Team] ?? null) : (MLB_TEAM_IDS[r.Opponent] ?? null),
      awayTeamId: r.Home ? (MLB_TEAM_IDS[r.Opponent] ?? null) : (MLB_TEAM_IDS[r.Team] ?? null),
    }));
}

function MoneylineTab() {
  const [picks, setPicks] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch("/api/moneylines")
      .then(r => r.json())
      .then(data => setPicks(buildMoneylinePicks(data.games || [])))
      .catch(() => setPicks([]))
      .finally(() => setLoading(false));
  }, []);

  const list = picks || [];

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Today's Moneylines</div>
      {loading ? (
        <div style={{ color: C.textDim, fontSize: 13, textAlign: "center", padding: 30 }}>Loading...</div>
      ) : list.length === 0 ? (
        <div style={{ color: C.textDim, fontSize: 13, textAlign: "center", padding: 30 }}>No moneylines available yet.</div>
      ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {list.map((pick, i) => (
          <div key={`${pick.team}-${pick.opponent}-${i}`} style={{
            background: "#161b22", borderRadius: 14, overflow: "hidden",
            border: `1px solid ${C.line}`, borderLeft: "none",
            display: "flex", transition: "border-color 0.15s",
          }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.line2}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.line}
          >
            <div style={{ width: 5, flexShrink: 0, background: teamColor(pick.teamAbbr) }} />
            <div style={{ flex: 1, padding: "13px 14px", minWidth: 0 }}>

              {/* Top row: team info + SC chip */}
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <TeamLogo name={pick.team} sport={pick.sport} abbr={pick.teamAbbr} size={52} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontFamily: FONT_DISPLAY, fontWeight: 600, fontSize: 18, letterSpacing: 0.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.team}</span>
                    <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: teamColor(pick.teamAbbr), fontWeight: 700, letterSpacing: 1 }}>{pick.teamAbbr}</span>
                  </div>
                  <div style={{ fontFamily: FONT_COND, fontSize: 14, color: C.textDim, marginTop: 2, fontWeight: 500 }}>
                    <span style={{ fontWeight: 700 }}>{pick.home ? "(H)" : "@"}</span>{" "}
                    <b style={{ color: C.text, fontWeight: 700 }}>{pick.opponent}</b>
                  </div>
                  <div style={{ fontSize: 9, color: C.textDim, marginTop: 5, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>
                    {pick.sport ? pick.sport + " · " : ""}{pick.time}
                  </div>
                </div>
                <div style={{ flexShrink: 0, textAlign: "center", minWidth: 56 }}>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 23, fontWeight: 800, color: C.text, lineHeight: 1, letterSpacing: -1, fontVariantNumeric: "tabular-nums" }}>
                    {pick.winPct}%
                  </div>
                  <div style={{ marginTop: 5, fontFamily: FONT_COND, fontSize: 10, fontWeight: 700, letterSpacing: 0.8, padding: "2px 0", borderRadius: 5, color: C.textDim, background: C.card2, border: `1px solid ${C.line2}` }}>
                    SC
                  </div>
                </div>
              </div>

              {/* Stats row */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 1, marginTop: 13, background: C.line, borderRadius: 9, overflow: "hidden" }}>
                <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                  <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Win%</div>
                  <div style={{ color: scoreColor(pick.winPct), fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                    {pick.winPct}%
                  </div>
                </div>
                <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                  <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Odds</div>
                  <div style={{ color: pick.odds > 0 ? C.green : C.text, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                    {pick.odds > 0 ? "+" : ""}{pick.odds}
                  </div>
                </div>
                <div style={{ flex: 1, background: C.card2, padding: "9px 4px" }}>
                  <StatCell
                    value={`${pick.bestOdds > 0 ? "+" : ""}${pick.bestOdds}`}
                    frac={pick.bestBook || null}
                    label="Best Odds"
                    line={null} side={null}
                  />
                </div>
                <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                  <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>O/U</div>
                  <div style={{ color: C.text, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                    {pick.gameTotal != null ? pick.gameTotal : "—"}
                  </div>
                </div>
                <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                  <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Books</div>
                  <div style={{ color: C.text, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                    {pick.books != null ? pick.books : "—"}
                  </div>
                </div>
              </div>

              {/* Sim Explorer link-out — exploratory, not a confidence signal.
                  Deep-links to the matchup when both teams resolve to MLB
                  team IDs; otherwise falls back to the Sim Explorer root. */}
              <a
                href={
                  pick.awayTeamId != null && pick.homeTeamId != null
                    ? `http://${window.location.hostname}:8502/?tab=sim&away=${pick.awayTeamId}&home=${pick.homeTeamId}`
                    : `http://${window.location.hostname}:8502/`
                }
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "block", textAlign: "center", marginTop: 8,
                  padding: "7px 0", borderRadius: 8, fontSize: 11, fontWeight: 600,
                  letterSpacing: 0.3, textDecoration: "none",
                  color: C.textDim, background: "transparent", border: `1px solid ${C.line2}`,
                }}
              >
                Run Simulation
              </a>

            </div>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}
