import re

p = "frontend/dist/app.jsx"
src = open(p).read()
orig = src

# ============================================================
# 1. Remove the DUPLICATE search block (there are two identical ones)
# ============================================================
search_block = '''      {/* Player search */}
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

'''
cnt = src.count(search_block)
assert cnt == 2, f"expected 2 identical search blocks, found {cnt}"
# remove the first occurrence only (keep one)
src = src.replace(search_block, "", 1)

# ============================================================
# 2. Compact the LINE SELECTOR — kill the gradient hero panel, inline chips
# ============================================================
old_lines = '''      {/* \u2605 LINE SELECTOR — Hero Feature */}
      {lines.length > 0 && (
        <div style={{
          background: "linear-gradient(135deg, #0d1520, #111d2d)", borderRadius: 12,
          padding: "10px 12px", marginBottom: 12,
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8, fontWeight: 600 }}>
            Select Line
          </div>
          <div style={{ display: "flex", gap: 6, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
            {lines.map(l => (
              <button key={l} onClick={() => setLine(l)} style={{
                minWidth: 64, padding: "10px 16px", borderRadius: 10, cursor: "pointer",
                fontSize: 16, fontWeight: 800, fontVariantNumeric: "tabular-nums",
                transition: "all 0.2s", border: "none",
                background: activeLine === l
                  ? `linear-gradient(135deg, ${C.green}, #16a34a)`
                  : "#1a2736",
                color: activeLine === l ? "#000" : C.text,
                boxShadow: activeLine === l ? `0 4px 16px rgba(34,197,94,0.3)` : "none",
              }}>{l}</button>
            ))}
          </div>
        </div>
      )}'''
new_lines = '''      {/* Line selector — compact chips */}
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
      )}'''
assert old_lines in src, "line selector block not found"
src = src.replace(old_lines, new_lines)

# ============================================================
# 3. Stat chips — green-active -> gold-active, gunmetal rest
# ============================================================
old_chip = '''            background: activeStatType === st ? C.green : "#1a2736",
            color: activeStatType === st ? "#000" : C.textDim,
          }}>{st}</button>'''
new_chip = '''            background: activeStatType === st ? C.gold : C.card2,
            color: activeStatType === st ? "#1a1206" : C.textDim,
            border: `1px solid ${activeStatType === st ? C.gold : C.line}`,
          }}>{st}</button>'''
assert old_chip in src, "stat chip style not found"
src = src.replace(old_chip, new_chip)

# ============================================================
# 4. Replace the sort row with a proper dropdown (matchup lenses)
# ============================================================
old_sortrow = '''      <div style={{ display: "flex", gap: 4, marginBottom: 8, paddingLeft: 50 }}>
        {[
          { key: "score", label: "SC" },
          { key: "edge", label: "Edge" },
          { key: "l5", label: "L5" },
          { key: "l10", label: "L10" },
        ].map(({ key, label }) => (
          <button key={key} onClick={() => toggleSort(key)} style={{
            background: sortBy === key ? "#1a2736" : "transparent",
            border: "none", cursor: "pointer", color: sortBy === key ? C.text : C.textDim,
            fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 4,
            letterSpacing: 0.5, textTransform: "uppercase", minWidth: 50, textAlign: "center",
          }}>{label}<SortArrow col={key} /></button>
        ))}
      </div>'''
new_sortrow = '''      {(() => {
        const SORT_OPTS = [
          { key: "score",    label: "Score",  tag: "model" },
          { key: "ops_vs",   label: "OPS vs pitcher", tag: "matchup" },
          { key: "avg_vs",   label: "BA vs pitcher",  tag: "matchup" },
          { key: "k_pct_vs", label: "K% vs pitcher",  tag: "matchup" },
          { key: "edge",     label: "Edge",   tag: "proj\\u2212line" },
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
                <span style={{ fontSize: 9, color: C.textDim }}>\\u25BC</span>
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
      })()}'''
assert old_sortrow in src, "sort row not found"
src = src.replace(old_sortrow, new_sortrow)

# ============================================================
# 5. Add sortOpen state + accept setSortBy/setSortDir props in ScannerTab
# ============================================================
old_sig = "function ScannerTab({ sport, segment, setSegment, statTypes, activeStatType, setStatType, lines, activeLine, setLine, filtered, sortBy, sortDir, toggleSort, addToBuilder, gradeFilter, setGradeFilter }) {"
new_sig = "function ScannerTab({ sport, segment, setSegment, statTypes, activeStatType, setStatType, lines, activeLine, setLine, filtered, sortBy, sortDir, toggleSort, setSortBy, setSortDir, addToBuilder, gradeFilter, setGradeFilter }) {"
assert old_sig in src, "ScannerTab signature not found"
src = src.replace(old_sig, new_sig)

old_state = '''  const [expandedIdx, setExpandedIdx] = useState(null);
  const [search, setSearch] = useState("");'''
new_state = '''  const [expandedIdx, setExpandedIdx] = useState(null);
  const [search, setSearch] = useState("");
  const [sortOpen, setSortOpen] = useState(false);'''
assert old_state in src, "ScannerTab state not found"
src = src.replace(old_state, new_state)

# pass setSortBy/setSortDir down where ScannerTab is rendered
old_render = "            filtered={filtered} sortBy={sortBy} sortDir={sortDir} toggleSort={toggleSort}"
new_render = "            filtered={filtered} sortBy={sortBy} sortDir={sortDir} toggleSort={toggleSort} setSortBy={setSortBy} setSortDir={setSortDir}"
assert old_render in src, "ScannerTab render props not found"
src = src.replace(old_render, new_render)

# ============================================================
# 6. Fix sort to sink nulls to the bottom (matchup stats have gaps)
# ============================================================
old_sort = '''    f.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      const na = typeof av === "string" ? parseInt(av) : av;
      const nb = typeof bv === "string" ? parseInt(bv) : bv;
      return sortDir === "desc" ? nb - na : na - nb;
    });'''
new_sort = '''    f.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      const na = typeof av === "string" ? parseFloat(av) : av;
      const nb = typeof bv === "string" ? parseFloat(bv) : bv;
      const aNull = na == null || isNaN(na);
      const bNull = nb == null || isNaN(nb);
      if (aNull && bNull) return 0;
      if (aNull) return 1;   // nulls always sink
      if (bNull) return -1;
      return sortDir === "desc" ? nb - na : na - nb;
    });'''
assert old_sort in src, "sort comparator not found"
src = src.replace(old_sort, new_sort)

# ============================================================
# 7. Add the lens badge to the card (after the bet line)
# ============================================================
old_betline = '''                <div style={{ fontFamily: FONT_COND, fontSize: 14, color: C.textDim, marginTop: 2, fontWeight: 500 }}>
                  <span style={{ color: (pick.side || "").toLowerCase() === "over" ? C.green : C.red, fontWeight: 700 }}>{pick.side}</span>
                  {" "}<b style={{ color: C.text, fontWeight: 700 }}>{pick.line}</b> {pick.stat_type}{pick.is_goblin ? " \\u00B7 goblin" : ""}
                </div>'''
new_betline = old_betline + '''
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
                })()}'''
assert old_betline in src, "bet line not found for lens badge"
src = src.replace(old_betline, new_betline)

assert src != orig, "no changes made"
open(p, "w").write(src)
print("Stage 3 applied: dedup search, compact lines, gold chips, sort dropdown, lens badge, null-sink sort")
