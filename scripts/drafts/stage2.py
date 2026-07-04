import re, time

# ============================================================
# PART A: index.html — add Google Fonts + bump cache-buster
# ============================================================
ip = "frontend/dist/index.html"
ih = open(ip).read()
iorig = ih

if "fonts.googleapis" not in ih:
    fonts = '''    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
    <title>'''
    ih = ih.replace("    <title>", fonts, 1)

# bump the app.jsx cache-buster so browsers fetch the new file
ih = re.sub(r'/app\.jsx\?v=\d+', f'/app.jsx?v={int(time.time())}', ih)

if ih != iorig:
    open(ip, "w").write(ih)
    print("index.html: fonts added + cache-buster bumped")
else:
    print("index.html: no change (already had fonts?) — bumping buster anyway")
    ih = re.sub(r'/app\.jsx\?v=\d+', f'/app.jsx?v={int(time.time())}', open(ip).read())
    open(ip, "w").write(ih)

# ============================================================
# PART B: app.jsx — team colors, PlayerAvatar rewrite, card redesign
# ============================================================
ap = "frontend/dist/app.jsx"
src = open(ap).read()
orig = src

# B1. Add TEAM_COLORS map + font constants after the C palette close
if "TEAM_COLORS" not in src:
    palette_close = '''  teal: "#39b0a6",
  tealBg: "#0e211f",
};'''
    addition = palette_close + '''

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
}'''
    assert palette_close in src, "palette close not found"
    src = src.replace(palette_close, addition)

# B2. Rewrite PlayerAvatar to render headshot with initials fallback
old_avatar = '''function PlayerAvatar({ name, team }) {
  const initials = name.split(" ").map(n => n[0]).join("").slice(0, 2);
  return (
    <div style={{
      width: 38, height: 38, borderRadius: 10, background: "linear-gradient(135deg, #1e293b, #334155)",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 13, fontWeight: 700, color: C.textDim, flexShrink: 0,
      border: `1px solid ${C.border}`,
    }}>{initials}</div>
  );
}'''
new_avatar = '''function PlayerAvatar({ name, team, headshot, mlbId, size = 52 }) {
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
}'''
assert old_avatar in src, "PlayerAvatar not found"
src = src.replace(old_avatar, new_avatar)

# B3. Add team-color spine to the card container + restructure to flex
old_container = '''            style={{
              background: "#161b22", borderRadius: 14, padding: "15px",
              border: `1px solid ${C.line}`, cursor: "pointer",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.line2}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.line}
          >'''
new_container = '''            style={{
              background: "#161b22", borderRadius: 14, overflow: "hidden",
              border: `1px solid ${C.line}`, borderLeft: "none", cursor: "pointer",
              transition: "border-color 0.15s", display: "flex", marginBottom: 11,
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.line2}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.line}
          >
            <div style={{ width: 5, flexShrink: 0, background: teamColor(pick.team) }} />
            <div style={{ flex: 1, padding: "13px 14px", minWidth: 0 }}>'''
assert old_container in src, "card container not found"
src = src.replace(old_container, new_container)

# B4. Rewrite the top row (avatar + name + confidence) for the v2 look
old_toprow = '''            {/* Top row: player info + score */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <PlayerAvatar name={pick.player} team={pick.team} />'''
new_toprow = '''            {/* Top row: player info + score */}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <PlayerAvatar name={pick.player} team={pick.team} headshot={pick.headshot} mlbId={pick.mlb_id} size={52} />'''
assert old_toprow in src, "top row start not found"
src = src.replace(old_toprow, new_toprow)

# B5. Name line -> Oswald; bet line -> colored side
old_name = '''                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 16, letterSpacing: 0.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.player}</span>
                  {pick.team && <span style={{ fontSize: 11, color: C.textDim, fontWeight: 600, letterSpacing: 0.5 }}>{pick.team}</span>}
                </div>
                <div style={{ fontSize: 12, color: C.textDim, marginTop: 3 }}>
                  <span style={{ color: (pick.side || "").toLowerCase() === "over" ? C.green : C.red, fontWeight: 600 }}>{pick.side}</span>
                  {" "}<b style={{ color: C.text }}>{pick.line}</b> {pick.stat_type}{pick.is_goblin ? " \\u00B7 goblin" : ""}
                </div>'''
new_name = '''                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: FONT_DISPLAY, fontWeight: 600, fontSize: 18, letterSpacing: 0.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.player}</span>
                  {pick.team && <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: teamColor(pick.team), fontWeight: 700, letterSpacing: 1 }}>{pick.team}</span>}
                </div>
                <div style={{ fontFamily: FONT_COND, fontSize: 14, color: C.textDim, marginTop: 2, fontWeight: 500 }}>
                  <span style={{ color: (pick.side || "").toLowerCase() === "over" ? C.green : C.red, fontWeight: 700 }}>{pick.side}</span>
                  {" "}<b style={{ color: C.text, fontWeight: 700 }}>{pick.line}</b> {pick.stat_type}{pick.is_goblin ? " \\u00B7 goblin" : ""}
                </div>'''
assert old_name in src, "name/bet line not found"
src = src.replace(old_name, new_name)

# B6. Confidence chip -> scoreboard mono number
old_conf = '''                    <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 17, fontWeight: 700, color: C.text, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
                      {cd && cd.pct != null ? cd.pct + "%" : (pick.score != null ? pick.score : "\\u2014")}
                    </div>
                    <div style={{ marginTop: 5, fontSize: 10, fontWeight: 700, letterSpacing: 0.6, padding: "2px 0", borderRadius: 5, color: tc.fg, background: tc.bg, border: `1px solid ${tc.bd}` }}>
                      {tier || "SC"}
                    </div>'''
new_conf = '''                    <div style={{ fontFamily: FONT_MONO, fontSize: 23, fontWeight: 800, color: C.text, lineHeight: 1, letterSpacing: -1, fontVariantNumeric: "tabular-nums" }}>
                      {cd && cd.pct != null ? cd.pct + "%" : (pick.score != null ? pick.score : "\\u2014")}
                    </div>
                    <div style={{ marginTop: 5, fontFamily: FONT_COND, fontSize: 10, fontWeight: 700, letterSpacing: 0.8, padding: "2px 0", borderRadius: 5, color: tc.fg, background: tc.bg, border: `1px solid ${tc.bd}` }}>
                      {tier || "SC"}
                    </div>'''
assert old_conf in src, "confidence chip not found"
src = src.replace(old_conf, new_conf)

# B7. Close the extra card-inner wrapper div we opened in B3.
# The card previously ended with:  </div>\n          </div>\n        ))}
# We added one opening <div> (card-inner), so we need one more closing </div>.
old_close = '''            ) : (
              <div style={{ textAlign: "center", marginTop: 8, fontSize: 10, color: C.textDim, opacity: 0.5 }}>
                Tap for details
              </div>
            )}
          </div>
        ))}'''
new_close = '''            ) : (
              <div style={{ textAlign: "center", marginTop: 8, fontSize: 10, color: C.textDim, opacity: 0.5 }}>
                Tap for details
              </div>
            )}
            </div>
          </div>
        ))}'''
assert old_close in src, "card close not found"
src = src.replace(old_close, new_close)

assert src != orig, "app.jsx unchanged"
open(ap, "w").write(src)
print("app.jsx: team colors + headshots + scoreboard card applied")
print("Stage 2 complete")
