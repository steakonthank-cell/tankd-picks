import re

p = "frontend/dist/app.jsx"
src = open(p).read()
orig = src

# ============================================================
# EDIT 1: Header — logo tile to gold, brand type, MLB·AI SCANNER
# ============================================================
old_logo = '''              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 900, fontSize: 16, color: "#000",
            }}>T</div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: -0.5 }}>TANK'D PICKS</div>
              <div style={{ fontSize: 10, color: C.textDim, letterSpacing: 1, textTransform: "uppercase" }}>MLB · AI SCANNER</div>
            </div>'''
new_logo = '''              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 800, fontSize: 18, color: "#1a1206",
            }}>T</div>
            <div>
              <div style={{ fontWeight: 600, fontSize: 17, letterSpacing: 0.3 }}>TANK'D PICKS</div>
              <div style={{ fontSize: 9.5, color: C.textDim, letterSpacing: 2, textTransform: "uppercase", marginTop: 1 }}>MLB · AI scanner</div>
            </div>'''
assert old_logo in src, "header logo block not found"
src = src.replace(old_logo, new_logo)

# The logo tile background — find the green tile and make it gold
old_tile = 'background: `linear-gradient(135deg, ${C.green}, #16a34a)`,'
new_tile = 'background: `linear-gradient(150deg, ${C.gold}, #c77f1e)`,'
if old_tile in src:
    src = src.replace(old_tile, new_tile, 1)

# ============================================================
# EDIT 2: Filter pills — reuse tier colors (LOCK gold / STRONG teal / LEAN muted)
# ============================================================
old_pills = '''            {[
              { key: "all", label: "All", c: "#1a2736" },
              { key: "LOCK", label: "\\uD83D\\uDD25 LOCK", c: "#16a34a" },
              { key: "STRONG", label: "STRONG", c: "#ca8a04" },
              { key: "LEAN", label: "LEAN", c: "#0ea5e9" },
            ].map(g => (
              <button key={g.key} onClick={() => setGradeFilter(g.key)} style={{
                flex: 1, padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer",
                fontSize: 12, fontWeight: 800, transition: "all 0.15s",
                background: gradeFilter === g.key ? g.c : "#0d1520",
                color: gradeFilter === g.key ? (g.key === "all" ? C.text : "#000") : C.textDim,
                boxShadow: gradeFilter === g.key && g.key === "LOCK" ? "0 0 14px rgba(34,197,94,0.55)" : "none",
              }}>{g.label}</button>
            ))}'''
new_pills = '''            {[
              { key: "all", label: "All" },
              { key: "LOCK", label: "LOCK" },
              { key: "STRONG", label: "STRONG" },
              { key: "LEAN", label: "LEAN" },
            ].map(g => {
              const active = gradeFilter === g.key;
              const tc = g.key === "all" ? { fg: C.text, bg: C.line2, bd: C.line2 } : tierColors(g.key);
              return (
                <button key={g.key} onClick={() => setGradeFilter(g.key)} style={{
                  flex: 1, padding: "8px 0", borderRadius: 8, cursor: "pointer",
                  fontSize: 12, fontWeight: 700, letterSpacing: 0.4, transition: "all 0.15s",
                  background: active ? tc.bg : C.card2,
                  color: active ? tc.fg : C.textDim,
                  border: `1px solid ${active ? tc.bd : "transparent"}`,
                }}>{g.label}</button>
              );
            })}'''
assert old_pills in src, "filter pills block not found"
src = src.replace(old_pills, new_pills)

# ============================================================
# EDIT 3: Segment toggle (Hitters/Pitchers) — gunmetal + gold active
# ============================================================
old_seg = '''        <div style={{ display: "flex", gap: 3, background: "#0d1520", borderRadius: 8, padding: 3, marginBottom: 10 }}>
          {["hitter", "pitcher"].map(seg => (
            <button key={seg} onClick={() => setSegment(seg)} style={{
              flex: 1, padding: "7px 0", borderRadius: 6, border: "none", cursor: "pointer",
              fontSize: 12, fontWeight: 700, textTransform: "capitalize",
              background: segment === seg ? "#1a2736" : "transparent",
              color: segment === seg ? C.text : C.textDim,
              transition: "all 0.15s",
            }}>{seg === "hitter" ? "Hitters" : "Pitchers"}</button>
          ))}
        </div>'''
new_seg = '''        <div style={{ display: "flex", gap: 3, background: C.card2, borderRadius: 9, padding: 3, marginBottom: 10, border: `1px solid ${C.line}` }}>
          {["hitter", "pitcher"].map(seg => (
            <button key={seg} onClick={() => setSegment(seg)} style={{
              flex: 1, padding: "8px 0", borderRadius: 6, border: "none", cursor: "pointer",
              fontSize: 13, fontWeight: 600, letterSpacing: 0.3,
              background: segment === seg ? C.gold : "transparent",
              color: segment === seg ? "#1a1206" : C.textDim,
              transition: "all 0.15s",
            }}>{seg === "hitter" ? "Hitters" : "Pitchers"}</button>
          ))}
        </div>'''
assert old_seg in src, "segment toggle block not found"
src = src.replace(old_seg, new_seg)

# ============================================================
# EDIT 4: Bottom nav — gold active tab, gunmetal bar
# ============================================================
old_navbar = '''          background: "#0d1520", borderTop: `1px solid ${C.border}`,
          padding: "8px 0 12px",'''
new_navbar = '''          background: "#11161d", borderTop: `1px solid ${C.line}`,
          padding: "8px 0 12px",'''
assert old_navbar in src, "nav bar block not found"
src = src.replace(old_navbar, new_navbar)

old_navactive = 'color: tab === t ? C.green : C.textDim, transition: "color 0.15s",'
new_navactive = 'color: tab === t ? C.gold : C.textDim, transition: "color 0.15s",'
assert old_navactive in src, "nav active color not found"
src = src.replace(old_navactive, new_navactive)

# Builder badge -> gold
old_badge = '''                  background: C.green, color: "#000", fontSize: 9, fontWeight: 800,'''
new_badge = '''                  background: C.gold, color: "#1a1206", fontSize: 9, fontWeight: 800,'''
if old_badge in src:
    src = src.replace(old_badge, new_badge)

# Bottom-nav gradient backdrop -> gunmetal
old_grad = 'background: "linear-gradient(to top, #080e17 70%, transparent)",'
new_grad = 'background: "linear-gradient(to top, #0e1116 72%, transparent)",'
if old_grad in src:
    src = src.replace(old_grad, new_grad)

# ============================================================
assert src != orig, "no edits applied"
open(p, "w").write(src)
print("Pass 2 applied: header, filter pills (tier colors), segment toggle, bottom nav")
