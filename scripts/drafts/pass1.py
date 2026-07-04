import re

p = "frontend/dist/app.jsx"
src = open(p).read()
orig = src

# ============================================================
# EDIT 1: Extend the C palette with gunmetal/gold tokens (additive)
# ============================================================
old_c_end = '''  text: "#e2e8f0",
  textDim: "#64748b",
  accent: "#22c55e",
};'''
new_c_end = '''  text: "#e6e9ed",
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
};'''
assert old_c_end in src, "C palette end not found"
src = src.replace(old_c_end, new_c_end)

# ============================================================
# EDIT 2: Add helpers — formatPF + line-relative stat color
# Insert right after the scoreColor function block.
# ============================================================
anchor = '''function scoreColor(s) {
  if (s >= 90) return C.green;
  if (s >= 75) return C.yellow;
  return C.red;
}'''
helpers = anchor + '''

function formatPF(pf) {
  if (pf == null) return { txt: "\\u2014", neutral: true };
  const v = pf / 100;
  return { txt: v.toFixed(2), neutral: Math.abs(v - 1) < 0.005 };
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
}'''
assert anchor in src, "scoreColor anchor not found"
assert src.count(anchor) == 1
src = src.replace(anchor, helpers)

# ============================================================
# EDIT 3: Rewrite StatCell to color by line, take line+side props
# ============================================================
old_statcell = '''function StatCell({ value, frac, label }) {
  const col = pctColor(value);
  const bg = pctBg(value);
  return (
    <div style={{ textAlign: "center", minWidth: 56 }}>
      <div style={{ fontSize: 10, color: C.textDim, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ background: bg, borderRadius: 6, padding: "4px 6px" }}>
        <div style={{ color: col, fontWeight: 700, fontSize: 14, fontVariantNumeric: "tabular-nums" }}>{value}</div>
        {frac && <div style={{ color: C.textDim, fontSize: 10 }}>{frac}</div>}
      </div>
    </div>
  );
}'''
new_statcell = '''function StatCell({ value, frac, label, line, side }) {
  const col = formColor(value, line, side);
  return (
    <div style={{ textAlign: "center", flex: 1 }}>
      <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>{label}</div>
      <div style={{ color: col, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{value}</div>
      {frac && <div style={{ color: C.textDim, fontSize: 9, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>{frac}</div>}
    </div>
  );
}'''
assert old_statcell in src, "StatCell body not found"
src = src.replace(old_statcell, new_statcell)

# ============================================================
# EDIT 4: Card container styling -> gunmetal
# ============================================================
old_card = '''            style={{
              background: C.card, borderRadius: 12, padding: "12px 14px",
              border: `1px solid ${C.border}`, cursor: "pointer",
              transition: "background 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
            onMouseLeave={e => e.currentTarget.style.background = C.card}
          >'''
new_card = '''            style={{
              background: "#161b22", borderRadius: 14, padding: "15px",
              border: `1px solid ${C.line}`, cursor: "pointer",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.line2}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.line}
          >'''
assert old_card in src, "card container style not found"
src = src.replace(old_card, new_card)

# ============================================================
# EDIT 5: Top row — name badge + confidence chip (honest, gold)
# Replace from the badge ternary through the score-circle close.
# ============================================================
old_top = '''                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.player}</span>
                  {pick.grade && pick.grade !== "FLOOR" && pick.grade !== "SKIP" ? (
                    <span style={{
                      fontSize: 9, fontWeight: 800, padding: "2px 7px", borderRadius: 5, letterSpacing: 0.5,
                      color: "#000",
                      background: pick.grade === "LOCK" ? C.green : pick.grade === "STRONG" ? C.yellow : "#0ea5e9",
                    }}>{pick.grade === "LOCK" ? "\\uD83D\\uDD25 LOCK" : pick.grade}</span>
                  ) : <TierBadge tier={pick.tier} />}
                </div>
                <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
                  {pick.side} {pick.line} {pick.stat_type}{pick.is_goblin ? " \\u00B7 goblin" : ""}
                </div>
              </div>
              {/* Score circle */}
              <div style={{
                width: 44, height: 44, borderRadius: 12, flexShrink: 0,
                background: `linear-gradient(135deg, ${scoreColor(pick.score)}22, ${scoreColor(pick.score)}11)`,
                border: `2px solid ${scoreColor(pick.score)}66`,
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: scoreColor(pick.score), fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {pick.model_prob != null ? (confDisplay(pick.model_prob).pct + "%") : pick.score}
                </div>
                <div style={{ fontSize: 8, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>{pick.model_prob != null ? confDisplay(pick.model_prob).tier : "SC"}</div>
              </div>'''
new_top = '''                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 16, letterSpacing: 0.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pick.player}</span>
                  {pick.team && <span style={{ fontSize: 11, color: C.textDim, fontWeight: 600, letterSpacing: 0.5 }}>{pick.team}</span>}
                </div>
                <div style={{ fontSize: 12, color: C.textDim, marginTop: 3 }}>
                  <span style={{ color: (pick.side || "").toLowerCase() === "over" ? C.green : C.red, fontWeight: 600 }}>{pick.side}</span>
                  {" "}<b style={{ color: C.text }}>{pick.line}</b> {pick.stat_type}{pick.is_goblin ? " \\u00B7 goblin" : ""}
                </div>
              </div>
              {/* Confidence chip — honest tier + calibrated % */}
              {(() => {
                const cd = pick.model_prob != null ? confDisplay(pick.model_prob) : null;
                const tier = cd ? cd.tier : (pick.tier || "");
                const tc = tierColors(tier);
                return (
                  <div style={{ flexShrink: 0, textAlign: "center", minWidth: 56 }}>
                    <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 17, fontWeight: 700, color: C.text, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
                      {cd && cd.pct != null ? cd.pct + "%" : (pick.score != null ? pick.score : "\\u2014")}
                    </div>
                    <div style={{ marginTop: 5, fontSize: 10, fontWeight: 700, letterSpacing: 0.6, padding: "2px 0", borderRadius: 5, color: tc.fg, background: tc.bg, border: `1px solid ${tc.bd}` }}>
                      {tier || "SC"}
                    </div>
                  </div>
                );
              })()}'''
assert old_top in src, "top row block not found"
src = src.replace(old_top, new_top)

# ============================================================
# EDIT 6: Stats row — pass line+side to StatCell, format PF as 1.00
# ============================================================
old_stats = '''            {/* Stats row */}
            <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
              <StatCell value={pick.l5} frac={pick.l5_frac} label="L5" />
              <StatCell value={pick.l10} frac={pick.l10_frac} label="L10" />
              <div style={{ textAlign: "center", minWidth: 50 }}>
                <div style={{ fontSize: 10, color: C.textDim, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>Edge</div>
                <div style={{ background: pctBg(`${pick.edge > 10 ? 80 : pick.edge > 5 ? 60 : 30}`), borderRadius: 6, padding: "4px 6px" }}>
                  <div style={{ color: pick.edge >= 10 ? C.green : pick.edge >= 5 ? C.yellow : C.red, fontWeight: 700, fontSize: 14, fontVariantNumeric: "tabular-nums" }}>
                    +{pick.edge.toFixed(1)}
                  </div>
                </div>
              </div>
              <div style={{ textAlign: "center", minWidth: 50 }}>
                <div style={{ fontSize: 10, color: C.textDim, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>Proj</div>
                <div style={{ background: "rgba(100,116,139,0.1)", borderRadius: 6, padding: "4px 6px" }}>
                  <div style={{ color: C.text, fontWeight: 700, fontSize: 14, fontVariantNumeric: "tabular-nums" }}>
                    {pick.ai_proj}
                  </div>
                </div>
              </div>
              {/* V2 factors mini display */}
              <div style={{ textAlign: "center", minWidth: 42 }}>
                <div style={{ fontSize: 10, color: C.textDim, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>PF</div>
                <div style={{ background: "rgba(100,116,139,0.1)", borderRadius: 6, padding: "4px 6px" }}>
                  <div style={{ color: pick.park_factor > 100 ? C.green : pick.park_factor < 100 ? C.red : C.textDim, fontWeight: 600, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                    {pick.park_factor}
                  </div>
                </div>
              </div>
            </div>'''
new_stats = '''            {/* Stats row */}
            <div style={{ display: "flex", alignItems: "flex-start", gap: 1, marginTop: 13, background: C.line, borderRadius: 9, overflow: "hidden" }}>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px" }}>
                <StatCell value={pick.l5} frac={pick.l5_frac} label="L5" line={pick.line} side={pick.side} />
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px" }}>
                <StatCell value={pick.l10} frac={pick.l10_frac} label="L10" line={pick.line} side={pick.side} />
              </div>
              <div style={{ flex: 1, background: C.card2, padding: "9px 4px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: C.textDim, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Edge</div>
                <div style={{ color: pick.edge >= 10 ? C.green : pick.edge >= 5 ? C.gold : C.red, fontWeight: 700, fontSize: 15, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {pick.edge >= 0 ? "+" : ""}{pick.edge.toFixed(1)}
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
            </div>'''
assert old_stats in src, "stats row block not found"
src = src.replace(old_stats, new_stats)

# ============================================================
# EDIT 7: Restyle Add-to-Builder button to gold
# ============================================================
old_btn = '''                <button onClick={(e) => { e.stopPropagation(); addToBuilder(pick); }} style={{
                  width: "100%", padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer",
                  background: "linear-gradient(135deg, " + C.green + ", #16a34a)",
                  color: "#000", fontWeight: 700, fontSize: 12,
                }}>+ Add to Builder</button>'''
new_btn = '''                <button onClick={(e) => { e.stopPropagation(); addToBuilder(pick); }} style={{
                  width: "100%", padding: "11px 0", borderRadius: 9, border: "none", cursor: "pointer",
                  background: C.gold, color: "#1a1206", fontWeight: 600, fontSize: 13, letterSpacing: 0.2,
                }}>+ Add to builder</button>'''
assert old_btn in src, "add button not found"
src = src.replace(old_btn, new_btn)

# ============================================================
# Write back only if something changed
# ============================================================
assert src != orig, "no edits applied"
open(p, "w").write(src)
print("Pass 1 applied: 7 edits (palette, helpers, StatCell, card, top row, stats, button)")
