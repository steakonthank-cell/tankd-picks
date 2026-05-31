"""
Sports EV Bot — Streamlit Web App (v2)
Clean, button-triggered UI. Nothing loads until you ask for it.
"""

import os, sys, glob, warnings
import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_BASE = os.path.dirname(os.path.abspath(__file__))

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Tank'd Picks",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

:root {
  --bg:        #01030a;
  --surface:   rgba(6,11,22,0.85);
  --surface2:  rgba(8,14,26,0.9);
  --surface3:  rgba(11,18,32,0.95);
  --glass:     rgba(8,14,26,0.6);
  --glass2:    rgba(255,255,255,0.03);
  --border:    rgba(255,255,255,0.04);
  --border2:   rgba(255,255,255,0.07);
  --border3:   rgba(255,255,255,0.12);
  --text:      #f0f4ff;
  --text2:     #8ba3c7;
  --text3:     #4a6380;
  --text4:     #273850;
  --accent:    #4f8ef7;
  --accent-dk: #1b45cc;
  --accent-lt: #93c5fd;
  --green:     #00e896;
  --green-dk:  #059669;
  --red:       #ff6b6b;
  --gold:      #fbbf24;
  --purple:    #b57bee;
  --radius-sm: 12px;
  --radius-md: 16px;
  --radius-lg: 22px;
  --glow-blue: 0 0 60px rgba(79,142,247,0.18), 0 0 20px rgba(79,142,247,0.1);
  --glow-green:0 0 60px rgba(0,232,150,0.15), 0 0 20px rgba(0,232,150,0.08);
  --glow-sm:   0 4px 24px rgba(0,0,0,0.6);
  --glow-md:   0 8px 40px rgba(0,0,0,0.7);
  --glow-lg:   0 16px 60px rgba(0,0,0,0.8);
}

/* ── Reset / Global ─────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    letter-spacing: -0.01em;
}
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
[data-testid="collapsedControl"] { display: none; }

/* Aurora background */
.stApp {
    background: var(--bg) !important;
    background-image:
        radial-gradient(ellipse 80% 50% at 20% -10%, rgba(79,142,247,0.09) 0%, transparent 55%),
        radial-gradient(ellipse 60% 40% at 80% 10%,  rgba(0,232,150,0.05) 0%, transparent 50%),
        radial-gradient(ellipse 50% 30% at 50% 100%, rgba(181,123,238,0.04) 0%, transparent 50%) !important;
}
.block-container {
    padding: 1.5rem 2.5rem 4rem !important;
    max-width: 1300px !important;
}

/* ── Nav bar ────────────────────────────────────────────────────────── */
.nav-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 0 20px 0;
    border-bottom: 1px solid var(--border2);
    margin-bottom: 28px;
}
.nav-logo {
    font-size: 1.05rem;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -0.4px;
    display: flex;
    align-items: center;
    gap: 9px;
}
.nav-logo span {
    background: linear-gradient(135deg, #bfdbfe, var(--accent));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    filter: drop-shadow(0 0 12px rgba(79,142,247,0.4));
}
.nav-badge {
    font-size: 0.58rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text3);
    background: var(--glass);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border2);
    border-radius: 99px;
    padding: 4px 12px;
}

/* ── Sport tab radio ────────────────────────────────────────────────── */
.stRadio > div {
    display: flex !important;
    flex-direction: row !important;
    gap: 6px !important;
    flex-wrap: wrap !important;
    background: transparent !important;
}
.stRadio label {
    background: var(--glass) !important;
    backdrop-filter: blur(10px) !important;
    -webkit-backdrop-filter: blur(10px) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 99px !important;
    padding: 6px 18px !important;
    color: var(--text3) !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
    white-space: nowrap !important;
}
.stRadio label:hover {
    border-color: rgba(79,142,247,0.4) !important;
    color: var(--accent-lt) !important;
    background: rgba(79,142,247,0.08) !important;
}
.stRadio [data-baseweb="radio"] input:checked + div + label,
.stRadio label[data-checked="true"] {
    background: linear-gradient(135deg, rgba(27,69,204,0.8), rgba(79,142,247,0.6)) !important;
    border-color: rgba(79,142,247,0.5) !important;
    color: #fff !important;
    box-shadow: 0 2px 16px rgba(79,142,247,0.3), inset 0 1px 0 rgba(255,255,255,0.1) !important;
}

/* ── Page titles ────────────────────────────────────────────────────── */
.page-title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 2px;
}
.page-title-row img {
    width: 38px; height: 38px;
    object-fit: contain;
    filter: drop-shadow(0 2px 12px rgba(0,0,0,0.7));
}
.page-title {
    font-size: 1.55rem;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -0.6px;
    margin-bottom: 0;
}
.page-subtitle {
    font-size: 0.78rem;
    color: var(--text3);
    margin-bottom: 24px;
    margin-top: 4px;
    font-weight: 500;
}

/* ── Stat chips ─────────────────────────────────────────────────────── */
.chip-row {
    display: flex;
    gap: 10px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.chip {
    background: var(--glass);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border2);
    border-radius: var(--radius-md);
    padding: 14px 18px;
    text-align: center;
    min-width: 96px;
    position: relative;
    overflow: hidden;
    transition: all 0.18s ease;
}
.chip::before {
    content: '';
    position: absolute;
    top: 0; left: 20%; right: 20%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(79,142,247,0.6), transparent);
}
.chip:hover {
    border-color: var(--border3);
    transform: translateY(-2px);
    box-shadow: var(--glow-sm), inset 0 1px 0 rgba(255,255,255,0.04);
}
.chip-label {
    font-size: 0.58rem;
    color: var(--text4);
    text-transform: uppercase;
    letter-spacing: 1.4px;
    font-weight: 700;
}
.chip-value {
    font-size: 1.3rem;
    font-weight: 800;
    color: var(--text);
    margin-top: 5px;
    letter-spacing: -0.6px;
}
.chip-value.green { color: var(--green); text-shadow: 0 0 20px rgba(0,232,150,0.4); }
.chip-value.blue  { color: var(--accent); text-shadow: 0 0 20px rgba(79,142,247,0.4); }

/* ── Buttons ────────────────────────────────────────────────────────── */
.stButton > button {
    background: var(--glass) !important;
    backdrop-filter: blur(10px) !important;
    -webkit-backdrop-filter: blur(10px) !important;
    color: var(--accent-lt) !important;
    border: 1px solid var(--border3) !important;
    border-radius: var(--radius-sm) !important;
    padding: 9px 22px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.3px !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    background: linear-gradient(135deg, rgba(27,69,204,0.9), rgba(37,99,235,0.9)) !important;
    color: #fff !important;
    border-color: rgba(79,142,247,0.5) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 24px rgba(79,142,247,0.35), inset 0 1px 0 rgba(255,255,255,0.1) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

.stFormSubmitButton > button {
    background: linear-gradient(135deg, rgba(27,69,204,0.9), rgba(37,99,235,0.9)) !important;
    border: 1px solid rgba(79,142,247,0.4) !important;
    color: #fff !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    box-shadow: 0 4px 24px rgba(79,142,247,0.3), inset 0 1px 0 rgba(255,255,255,0.1) !important;
}
.stFormSubmitButton > button:hover {
    box-shadow: 0 8px 36px rgba(79,142,247,0.5), inset 0 1px 0 rgba(255,255,255,0.15) !important;
    transform: translateY(-2px) !important;
}

/* ── Tabs ───────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border2) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text3) !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    padding: 10px 18px !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    transition: all 0.15s ease !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text2) !important; }
.stTabs [aria-selected="true"] {
    color: var(--text) !important;
    border-bottom: 2px solid var(--accent) !important;
    background: transparent !important;
    text-shadow: 0 0 20px rgba(79,142,247,0.4) !important;
}

/* ── Section headers ────────────────────────────────────────────────── */
.section-header {
    font-size: 0.58rem;
    font-weight: 700;
    color: var(--text4);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin: 26px 0 12px;
}

/* ── DataFrames / tables ────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden !important;
    box-shadow: var(--glow-sm) !important;
    backdrop-filter: blur(12px) !important;
}
.stDataFrame { font-size: 0.82rem !important; }
[data-testid="stDataFrame"] table { background: var(--glass) !important; }
[data-testid="stDataFrame"] th {
    background: rgba(8,14,26,0.95) !important;
    color: var(--text3) !important;
    font-size: 0.61rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.2px !important;
    border-bottom: 1px solid var(--border2) !important;
    padding: 11px 14px !important;
}
[data-testid="stDataFrame"] td {
    color: var(--text2) !important;
    border-bottom: 1px solid var(--border) !important;
    padding: 10px 14px !important;
}
[data-testid="stDataFrame"] tr:hover td {
    background: rgba(79,142,247,0.04) !important;
}

/* ── Glass card ─────────────────────────────────────────────────────── */
.card {
    background: var(--glass);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border2);
    border-radius: var(--radius-md);
    padding: 22px 24px;
    margin-bottom: 12px;
    position: relative;
    overflow: hidden;
}
.card::before {
    content: '';
    position: absolute;
    top: 0; left: 15%; right: 15%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.07), transparent);
}

/* ── Alert / info box ───────────────────────────────────────────────── */
.alert {
    background: rgba(79,142,247,0.05);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(79,142,247,0.18);
    border-left: 3px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 12px 16px;
    font-size: 0.8rem;
    color: var(--text3);
    margin-bottom: 16px;
    line-height: 1.6;
}

/* ── Badges ─────────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    background: var(--glass);
    color: var(--text2);
    border-radius: 99px;
    padding: 3px 10px;
    font-size: 0.68rem;
    font-weight: 600;
    border: 1px solid var(--border2);
}
.badge.green {
    background: rgba(0,232,150,0.08);
    color: var(--green);
    border-color: rgba(0,232,150,0.25);
    box-shadow: 0 0 12px rgba(0,232,150,0.1);
}
.badge.blue {
    background: rgba(79,142,247,0.08);
    color: var(--accent-lt);
    border-color: rgba(79,142,247,0.25);
    box-shadow: 0 0 12px rgba(79,142,247,0.1);
}

/* ── Divider ────────────────────────────────────────────────────────── */
.divider { border: none; border-top: 1px solid var(--border2); margin: 24px 0; }

/* ── Empty state ────────────────────────────────────────────────────── */
.empty-state { text-align: center; padding: 60px 20px; color: var(--text3); }
.empty-icon { font-size: 2.2rem; margin-bottom: 12px; opacity: 0.4; }
.empty-text { font-size: 0.84rem; }

/* ── Streamlit native overrides ─────────────────────────────────────── */
.stAlert {
    background: var(--glass) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text2) !important;
}
div[data-testid="stNotification"] {
    background: var(--glass) !important;
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-sm) !important;
}
.stSpinner > div { color: var(--accent) !important; }

.stTextInput input, .stTextInput textarea {
    background: var(--glass) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text) !important;
    font-size: 0.88rem !important;
    caret-color: var(--accent) !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
}
.stTextInput input:focus {
    border-color: rgba(79,142,247,0.5) !important;
    box-shadow: 0 0 0 3px rgba(79,142,247,0.1), 0 0 20px rgba(79,142,247,0.08) !important;
}
.stSelectbox > div > div {
    background: var(--glass) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text) !important;
}
.streamlit-expanderHeader {
    background: var(--glass) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid var(--border2) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text2) !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    padding: 11px 16px !important;
}
.streamlit-expanderContent {
    background: var(--glass) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid var(--border2) !important;
    border-top: none !important;
    border-radius: 0 0 var(--radius-sm) var(--radius-sm) !important;
    padding: 16px !important;
}

/* ── Scrollbar ──────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border3); border-radius: 99px; }

/* ── Top plays cards ────────────────────────────────────────────────── */
.plays-row {
    display: flex;
    gap: 12px;
    overflow-x: auto;
    padding-bottom: 10px;
    margin-bottom: 22px;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
}
.plays-row::-webkit-scrollbar { height: 3px; }
.plays-row::-webkit-scrollbar-thumb { background: var(--border3); border-radius: 99px; }

.play-card {
    flex: 0 0 158px;
    background: var(--glass);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border2);
    border-radius: var(--radius-md);
    padding: 18px 14px 15px;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 5px;
    transition: all 0.2s ease;
    cursor: default;
    position: relative;
    overflow: hidden;
}
.play-card::before {
    content: '';
    position: absolute;
    top: 0; left: 20%; right: 20%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
}
.play-card::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--green), transparent);
    opacity: 0;
    transition: opacity 0.2s;
}
.play-card:hover::after { opacity: 1; }
.play-card:hover {
    border-color: var(--border3);
    background: rgba(0,232,150,0.04);
    transform: translateY(-4px);
    box-shadow: var(--glow-md), var(--glow-green);
}
.play-card img {
    width: 58px; height: 58px;
    border-radius: 50%;
    object-fit: cover;
    background: var(--glass);
    border: 2px solid var(--border3);
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
.play-card .pc-name {
    font-size: 0.76rem;
    font-weight: 700;
    color: var(--text);
    line-height: 1.2;
    margin-top: 5px;
}
.play-card .pc-stat { font-size: 0.65rem; color: var(--text3); font-weight: 500; }
.play-card .pc-line {
    font-size: 1.15rem;
    font-weight: 800;
    color: var(--green);
    letter-spacing: -0.5px;
    text-shadow: 0 0 16px rgba(0,232,150,0.5);
}
.play-card .pc-tier { font-size: 0.62rem; color: var(--text4); margin-top: 2px; font-weight: 600; }

/* ── Moneyline game cards ───────────────────────────────────────────── */
.ml-sport-block { margin-bottom: 32px; }
.ml-sport-title {
    font-size: 0.58rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--text4);
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 9px;
}
.ml-sport-title img { width: 16px; height: 16px; object-fit: contain; opacity: 0.6; }

.ml-game-card {
    background: var(--glass);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--border2);
    border-radius: var(--radius-lg);
    padding: 20px 24px 18px;
    margin-bottom: 12px;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    grid-template-rows: auto auto;
    align-items: center;
    gap: 0 18px;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
}
.ml-game-card::before {
    content: '';
    position: absolute;
    top: 0; left: 10%; right: 10%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
}
.ml-game-card:hover {
    border-color: var(--border3);
    box-shadow: var(--glow-md);
    transform: translateY(-2px);
    background: rgba(79,142,247,0.04);
}

.ml-team { display: flex; align-items: center; gap: 13px; }
.ml-team.away { flex-direction: row-reverse; text-align: right; }
.ml-team img {
    width: 44px; height: 44px;
    object-fit: contain; flex-shrink: 0;
    filter: drop-shadow(0 2px 10px rgba(0,0,0,0.6));
}
.ml-team-name { font-size: 0.86rem; font-weight: 700; color: var(--text); line-height: 1.2; }
.ml-team-odds { font-size: 1.05rem; font-weight: 800; margin-top: 2px; }
.ml-odds-neg { color: var(--green); text-shadow: 0 0 12px rgba(0,232,150,0.35); }
.ml-odds-pos { color: var(--text3); }
.ml-pct { font-size: 0.61rem; color: var(--text4); margin-top: 2px; font-weight: 500; }

.ml-center {
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 58px;
}
.ml-time { font-size: 0.57rem; color: var(--text4); letter-spacing: 0.4px; }
.ml-vs { font-size: 0.62rem; font-weight: 800; color: var(--text4); letter-spacing: 3px; }
.ml-total { font-size: 0.57rem; color: var(--text4); }

/* Confidence meter */
.ml-meter-row {
    grid-column: 1 / -1;
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
}
.ml-meter-labels {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}
.ml-meter-fav { font-size: 0.7rem; font-weight: 700; }
.ml-meter-badge {
    font-size: 0.55rem;
    font-weight: 800;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 3px 11px;
    border-radius: 99px;
    border: 1px solid currentColor;
}
.ml-meter-dog { font-size: 0.65rem; color: var(--text4); font-weight: 500; }
.ml-meter-track {
    width: 100%; height: 6px;
    background: rgba(0,0,0,0.4);
    border-radius: 99px;
    overflow: hidden;
    border: 1px solid var(--border);
}
.ml-meter-fill { height: 100%; border-radius: 99px; }

/* Starting pitcher line */
.ml-pitcher {
    font-size: 0.63rem;
    color: var(--text3);
    font-weight: 600;
    margin-top: 4px;
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
}
.ml-team.away .ml-pitcher { justify-content: flex-end; }
.ml-pitcher-hand {
    font-size: 0.52rem;
    font-weight: 800;
    letter-spacing: 0.5px;
    padding: 1px 6px;
    border-radius: 4px;
    text-transform: uppercase;
}
.ml-hand-R {
    background: rgba(79,142,247,0.12);
    color: var(--accent-lt);
    border: 1px solid rgba(79,142,247,0.25);
}
.ml-hand-L {
    background: rgba(0,232,150,0.10);
    color: var(--green);
    border: 1px solid rgba(0,232,150,0.25);
}

/* Book chips — inline on card */
.ml-books-row {
    display: flex; gap: 5px; flex-wrap: wrap;
    margin-top: 6px;
}
.ml-team.away .ml-books-row { justify-content: flex-end; }
.ml-book-chip {
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border2);
    border-radius: 6px;
    padding: 3px 8px;
    display: flex; flex-direction: column; align-items: center; gap: 1px;
    transition: border-color 0.12s;
}
.ml-book-chip .bk-name { color: var(--text4); font-size: 0.48rem; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 700; }
.ml-book-chip .bk-odds { color: var(--text3); font-size: 0.65rem; font-weight: 700; }
.ml-book-chip.best-odds { border-color: rgba(0,232,150,0.35); background: rgba(0,232,150,0.06); }
.ml-book-chip.best-odds .bk-name { color: var(--green); }
.ml-book-chip.best-odds .bk-odds { color: var(--green); text-shadow: 0 0 10px rgba(0,232,150,0.3); }
</style>
""", unsafe_allow_html=True)

# ── Password gate ─────────────────────────────────────────────────────────────
def _check_password():
    if st.session_state.get("authenticated"):
        return True
    try:
        correct = st.secrets["PASSWORD"]
    except Exception:
        st.error("No PASSWORD set in .streamlit/secrets.toml")
        st.stop()

    # Premium login screen
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
    .stApp {
        background: #01030a !important;
        background-image:
            radial-gradient(ellipse 70% 60% at 50% -5%,  rgba(79,142,247,0.14) 0%, transparent 55%),
            radial-gradient(ellipse 40% 30% at 80% 80%,  rgba(0,232,150,0.05) 0%, transparent 50%),
            radial-gradient(ellipse 40% 30% at 20% 90%,  rgba(181,123,238,0.04) 0%, transparent 50%) !important;
        font-family: 'Inter', sans-serif !important;
    }
    .login-wrap {
        display: flex; flex-direction: column; align-items: center;
        justify-content: center; min-height: 60vh;
    }
    .login-card {
        background: rgba(6,11,22,0.75);
        backdrop-filter: blur(28px);
        -webkit-backdrop-filter: blur(28px);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 24px;
        padding: 52px 44px 44px;
        text-align: center;
        position: relative;
        overflow: hidden;
        box-shadow: 0 0 100px rgba(0,0,0,0.9), 0 0 60px rgba(79,142,247,0.08),
                    inset 0 1px 0 rgba(255,255,255,0.05);
    }
    .login-card::before {
        content: '';
        position: absolute;
        top: 0; left: 5%; right: 5%;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(79,142,247,0.7), transparent);
    }
    .login-glow {
        position: absolute;
        top: -80px; left: 50%;
        transform: translateX(-50%);
        width: 280px; height: 280px;
        background: radial-gradient(circle, rgba(79,142,247,0.12) 0%, transparent 65%);
        pointer-events: none;
    }
    .login-icon {
        font-size: 3rem;
        display: block;
        margin-bottom: 20px;
        animation: float 4s ease-in-out infinite;
        filter: drop-shadow(0 0 16px rgba(79,142,247,0.5));
    }
    @keyframes float {
        0%, 100% { transform: translateY(0px); }
        50%       { transform: translateY(-8px); }
    }
    .login-title {
        font-size: 2rem;
        font-weight: 900;
        color: #f0f4ff;
        letter-spacing: -0.8px;
        margin-bottom: 6px;
        font-family: 'Inter', sans-serif;
    }
    .login-title span {
        background: linear-gradient(135deg, #bfdbfe, #4f8ef7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 0 12px rgba(79,142,247,0.4));
    }
    .login-sub {
        font-size: 0.68rem;
        color: rgba(255,255,255,0.2);
        font-weight: 700;
        letter-spacing: 2.5px;
        text-transform: uppercase;
        margin-bottom: 40px;
    }
    .login-divider {
        border: none;
        border-top: 1px solid rgba(255,255,255,0.05);
        margin: 0 0 32px;
    }
    .login-footer {
        margin-top: 24px;
        font-size: 0.6rem;
        color: rgba(255,255,255,0.1);
        font-weight: 600;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }
    .stTextInput input {
        background: rgba(0,0,0,0.4) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 12px !important;
        color: #f0f4ff !important;
        font-size: 0.9rem !important;
        padding: 13px 16px !important;
        caret-color: #4f8ef7 !important;
        font-family: 'Inter', sans-serif !important;
        transition: all 0.15s ease !important;
    }
    .stTextInput input:focus {
        border-color: rgba(79,142,247,0.5) !important;
        box-shadow: 0 0 0 3px rgba(79,142,247,0.1), 0 0 24px rgba(79,142,247,0.08) !important;
    }
    .stTextInput input::placeholder { color: rgba(255,255,255,0.15) !important; }
    .stFormSubmitButton > button {
        background: linear-gradient(135deg, rgba(27,69,204,0.95), rgba(37,99,235,0.95)) !important;
        border: 1px solid rgba(79,142,247,0.4) !important;
        border-radius: 12px !important;
        color: #fff !important;
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.8px !important;
        padding: 13px !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 6px 28px rgba(79,142,247,0.3), inset 0 1px 0 rgba(255,255,255,0.12) !important;
        font-family: 'Inter', sans-serif !important;
    }
    .stFormSubmitButton > button:hover {
        box-shadow: 0 10px 40px rgba(79,142,247,0.5), inset 0 1px 0 rgba(255,255,255,0.15) !important;
        transform: translateY(-2px) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    col = st.columns([1, 1.1, 1])[1]
    with col:
        st.markdown("""
        <div class="login-card">
            <div class="login-glow"></div>
            <span class="login-icon">🎯</span>
            <div class="login-title"><span>Tank'd</span> Picks</div>
            <div class="login-sub">Private Access Only</div>
            <hr class="login-divider">
        </div>
        """, unsafe_allow_html=True)

        with st.form("login", clear_on_submit=True):
            pw = st.text_input("Password", type="password", label_visibility="collapsed",
                               placeholder="Enter your password…")
            if st.form_submit_button("Sign In  →", use_container_width=True):
                if pw == correct:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("Incorrect password — try again")

        st.markdown('<div class="login-footer">🎯 AI-Powered · Built by Jake · Est. 2025</div>', unsafe_allow_html=True)
    return False

if not _check_password():
    st.stop()

# ── Team logo mappings (ESPN CDN) ─────────────────────────────────────────────
_ESPN_NBA = {
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
}
_ESPN_MLB = {
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
}
_ESPN_WNBA = {
    "Atlanta Dream":"atl","Chicago Sky":"chi","Connecticut Sun":"conn",
    "Dallas Wings":"dal","Indiana Fever":"ind","Las Vegas Aces":"lv",
    "Los Angeles Sparks":"la","Minnesota Lynx":"min","New York Liberty":"ny",
    "Phoenix Mercury":"phx","Seattle Storm":"sea","Washington Mystics":"wsh",
    "Golden State Valkyries":"gsv","Portland Fire":"por",
}

def _team_logo(team: str, sport: str) -> str:
    """Return ESPN CDN logo URL for a team, or empty string if unknown."""
    mapping = {"NBA": _ESPN_NBA, "MLB": _ESPN_MLB, "WNBA": _ESPN_WNBA}.get(sport, {})
    abbrev = mapping.get(team)
    if not abbrev:
        return ""
    sport_path = {"NBA": "nba", "MLB": "mlb", "WNBA": "wnba"}.get(sport, "nba")
    return f"https://a.espncdn.com/i/teamlogos/{sport_path}/500/{abbrev}.png"

def _league_logo(sport: str) -> str:
    paths = {"NBA": "nba", "MLB": "mlb", "WNBA": "wnba"}
    p = paths.get(sport)
    if not p: return ""
    return f"https://a.espncdn.com/i/teamlogos/leagues/500/{p}.png"

def _top_plays_cards(df, img_col="Image_URL", name_col="Player",
                     stat_col="Stat", line_col="PP_Line", tier_col="Tier_Emoji", n=6):
    """Render a horizontal scrollable row of player cards."""
    if df is None or df.empty:
        return
    top = df.head(n)
    cards_html = '<div class="plays-row">'
    for _, row in top.iterrows():
        img_url = row.get(img_col, "") if img_col in df.columns else ""
        if not img_url or pd.isna(img_url):
            img_url = "https://a.espncdn.com/combiner/i?img=/i/headshots/nophoto.png&w=56&h=56"
        name  = str(row.get(name_col, ""))
        stat  = str(row.get(stat_col, ""))
        line  = row.get(line_col, "")
        tier  = str(row.get(tier_col, ""))
        line_str = f"{float(line):.1f}" if pd.notna(line) and line != "" else "—"
        cards_html += f"""
        <div class="play-card">
            <img src="{img_url}" onerror="this.src='https://a.espncdn.com/combiner/i?img=/i/headshots/nophoto.png&w=56&h=56'" />
            <div class="pc-name">{name}</div>
            <div class="pc-stat">{stat}</div>
            <div class="pc-line">{line_str}</div>
            <div class="pc-tier">{tier}</div>
        </div>"""
    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)

# ── Tennis match odds ────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_tennis_match_odds(api_key: str) -> list:
    """Fetch h2h match-win odds for all active tennis tournaments."""
    import requests
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
    base = "https://api.the-odds-api.com/v4/sports"
    books = "fanduel,draftkings,betmgm,caesars"

    # Discover active tennis markets
    try:
        r = requests.get(f"{base}", params={"apiKey": api_key}, timeout=10)
        all_sports = r.json() if r.status_code == 200 else []
    except Exception:
        all_sports = []

    tennis_keys = [s["key"] for s in all_sports
                   if "tennis" in s.get("key", "") and s.get("active")]

    if not tennis_keys:
        tennis_keys = ["tennis_atp_french_open", "tennis_wta_french_open"]

    matches = []
    book_labels = {"fanduel": "FD", "draftkings": "DK", "betmgm": "MGM", "caesars": "CZR"}

    def _imp(odds):
        if odds >= 0: return 100 / (odds + 100)
        return abs(odds) / (abs(odds) + 100)

    def _fmt(x):
        try:
            v = float(x)
            return f"+{int(v)}" if v >= 0 else str(int(v))
        except Exception:
            return "—"

    for sport_key in tennis_keys:
        try:
            r = requests.get(f"{base}/{sport_key}/odds", params={
                "apiKey": api_key, "regions": "us",
                "markets": "h2h", "oddsFormat": "american",
                "bookmakers": books,
            }, timeout=12)
            if r.status_code != 200:
                continue
            games = r.json()
        except Exception:
            continue

        # Build tournament label
        tour_label = sport_key.replace("tennis_", "").replace("_", " ").title()

        for g in games:
            p1 = g.get("home_team", "")
            p2 = g.get("away_team", "")
            ct = g.get("commence_time", "")
            try:
                dt = datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_ET)
                match_time = dt.strftime("%a %b %-d · %-I:%M %p ET")
            except Exception:
                match_time = "TBD"

            odds_by_player = {p1: {}, p2: {}}
            for bm in g.get("bookmakers", []):
                bk = bm.get("key", "")
                bl = book_labels.get(bk, bk.upper()[:3])
                for mkt in bm.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    for oc in mkt.get("outcomes", []):
                        nm = oc.get("name", "")
                        pr = oc.get("price")
                        if nm in odds_by_player and pr is not None:
                            odds_by_player[nm][bl] = float(pr)

            for player in [p1, p2]:
                bk_odds = odds_by_player[player]
                if not bk_odds:
                    continue
                vals = list(bk_odds.values())
                avg  = sum(vals) / len(vals)
                best = max(vals); best_bk = max(bk_odds, key=bk_odds.get)
                imp  = _imp(avg)
                opp  = p2 if player == p1 else p1
                matches.append({
                    "tournament": tour_label,
                    "player":     player,
                    "opponent":   opp,
                    "time":       match_time,
                    "avg_odds":   avg,
                    "best_odds":  best,
                    "best_book":  best_bk,
                    "win_pct":    round(imp * 100, 1),
                    "book_odds":  bk_odds,
                    "is_fav":     avg < 0,
                })

    return matches

# ── Helpers ───────────────────────────────────────────────────────────────────
def _api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        from dotenv import load_dotenv; load_dotenv()
        return os.getenv("ODDS_API_KEY", "")

def _latest_csv(pattern):
    files = sorted(glob.glob(pattern), reverse=True)
    if not files: return pd.DataFrame()
    try: return pd.read_csv(files[0])
    except: return pd.DataFrame()

def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Replace underscores in column names with spaces."""
    df = df.copy()
    df.columns = [c.replace("_", " ") for c in df.columns]
    return df

def _round_df_mlb(df: pd.DataFrame) -> pd.DataFrame:
    """MLB rounding: rolling averages (L5/L10/streak) → 2 decimals, pct columns → X.X%, true stats left as-is."""
    df = _clean_cols(df.copy())
    rolling_keywords = ["l5", "l10", "l20", "streak", "score", "edge", "proj", "line", "implied", "total", "wind", "temp"]
    pct_keywords     = ["pct", "rate", "win %", "win%", "edge pct", "edge %", "ai conf", "ha win", "conf", "accuracy", "hr5", "hr10", "con over", "con under"]
    stat_keywords    = ["ops", "avg", "era", "whip", "obp", "slg", "ops+", "ab"]
    for col in df.columns:
        col_lower = col.lower()
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if any(k in col_lower for k in stat_keywords):
            df[col] = df[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
            continue
        if any(k in col_lower for k in pct_keywords):
            df[col] = df[col].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        elif any(k in col_lower for k in rolling_keywords):
            df[col] = df[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
    return df

def _round_df(df: pd.DataFrame) -> pd.DataFrame:
    """Round numeric columns: pct columns as X.X%, everything else to 1 decimal. Remove underscores from column names."""
    df = _clean_cols(df)
    pct_keywords = [
        "pct", "win %", "win%", "hit", "rate", "implied",
        "con over", "con under", "k pct", "edge pct", "edge %",
        "ai conf", "ha win", "conf", "accuracy", "hr5", "hr10",
    ]
    for col in df.columns:
        col_lower = col.lower()
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if any(k in col_lower for k in pct_keywords):
            df[col] = df[col].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        else:
            df[col] = df[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
    return df

def _style_side(val):
    if val == "Over":  return "color:#22c55e;font-weight:600"
    if val == "Under": return "color:#ef4444;font-weight:600"
    return ""

def _style_score(val):
    try:
        v = float(val)
        if v >= 70: return "color:#22c55e;font-weight:700"
        if v >= 50: return "color:#f59e0b;font-weight:600"
    except: pass
    return ""

def _empty(msg="No data yet — click the button above to run."):
    st.markdown(f"""
    <div class="empty-state">
        <div class="empty-icon">📭</div>
        <div class="empty-text">{msg}</div>
    </div>""", unsafe_allow_html=True)

# ── NBA session (cached for the process lifetime) ─────────────────────────────
@st.cache_resource(show_spinner=False)
def _nba_session():
    try:
        from src.sports.nba.scanner import load_data, load_models, auto_refresh_data, refresh_injuries
        refresh_injuries()
        df = load_data()
        if df is not None:
            df = auto_refresh_data(df)
        return df, load_models()
    except Exception:
        return None, {}

@st.cache_data(ttl=600, show_spinner=False)
def _fetch_nba_pp_board():
    """Shared cached PP board fetch for NBA — prevents double-fetching across scanners."""
    from src.core.odds_providers.prizepicks import PrizePicksClient
    from src.sports.nba.config import STAT_MAP
    pp = PrizePicksClient(stat_map=STAT_MAP)
    for _ in range(3):
        df = pp.fetch_board(league_filter="NBA", include_alts=True)
        if not df.empty:
            return df
        import time; time.sleep(8)
    return pd.DataFrame()

# ── NBA Super Scanner ─────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _run_super_scanner():
    import time
    from src.core.odds_providers.fanduel    import FanDuelClient
    from src.core.analyzers.analyzer        import PropsAnalyzer
    from src.sports.nba.config import ODDS_API_KEY as _K, SPORT_MAP, REGIONS, ODDS_FORMAT, STAT_MAP, MODEL_QUALITY
    from src.sports.nba.scanner import get_games, get_all_projections, normalize_name
    from src.sports.nba.mappings import PP_NORMALIZATION_MAP, STAT_MAPPING, VOLATILITY_MAP

    def _ns(r):
        s, lg = str(r["Stat"]), str(r.get("League","")).upper()
        return f"1H {s}" if lg == "NBA1H" and not s.startswith("1H ") else s

    pp_df = _fetch_nba_pp_board()
    if pp_df.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "PrizePicks unavailable"

    pp_df["Stat"] = pp_df.apply(_ns, axis=1)
    pp_df["Stat"] = pp_df["Stat"].replace(PP_NORMALIZATION_MAP)

    fd = FanDuelClient(api_key=_api_key() or _K, sport_map=SPORT_MAP,
                       regions=REGIONS, odds_format=ODDS_FORMAT, stat_map=STAT_MAP)
    _, date = get_games(date_offset=0, require_scheduled=True)
    fd_df = fd.get_all_odds(target_date=date)
    if fd_df.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), f"FanDuel unavailable for {date}"

    math = PropsAnalyzer(pp_df, fd_df, league="NBA").calculate_edges()
    if math.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "No math edges found"

    df_h, models = _nba_session()
    if df_h is None or not models: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "Models not loaded"

    ai = get_all_projections(df_h, models, date_offset=0)
    if ai.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "AI projections empty"

    math["Stat"]      = math["Stat"].map(STAT_MAPPING).fillna(math["Stat"])
    math["CleanName"] = math["Player"].apply(normalize_name)
    ai["CleanName"]   = ai["Player"].apply(normalize_name)

    merged = pd.merge(math, ai, on=["CleanName","Stat"], how="inner")
    merged = merged.drop_duplicates(subset=["CleanName","Stat","Line","Side"], keep="first")

    plays = []
    for _, r in merged.iterrows():
        line, ai_proj, win = r["Line"], r["AI_Proj"], r["Implied_Win_%"]
        ai_edge = min((abs(ai_proj - line) / line) * 100, 25) if line else 0
        ai_side = "Over" if ai_proj > line else "Under"
        if r["Side"] == ai_side:
            sw    = VOLATILITY_MAP.get(r["Stat"], 1.0)
            score = ((max(0,min(10,(win-51)/5*10))*0.5) + (max(0,min(10,(ai_edge/20)*10))*0.5)) * 10 * sw
            plays.append({
                "Player":  r["Player_x"],
                "Stat":    r["Stat"],
                "Side":    r["Side"],
                "Line":    round(float(line), 3),
                "Win %":   round(float(win), 3),
                "AI Proj": round(float(ai_proj), 3),
                "Score":   round(score, 3),
                "Δ Line":  round(float(r.get("Line_Diff", 0)), 3),
                "Tier":    MODEL_QUALITY.get(r["Stat"], {}).get("tier", "-"),
                "_type":   str(r.get("OddsType","standard") or "standard").lower(),
            })

    if not plays: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "No correlated plays found"
    all_df = pd.DataFrame(plays).sort_values("Score", ascending=False)
    std = all_df[all_df["_type"].isin(["standard",""])].drop(columns=["_type"])
    gob = all_df[(all_df["_type"] == "goblin") & (all_df["Side"] == "Over")].drop(columns=["_type"])
    dem = all_df[(all_df["_type"] == "demon")  & (all_df["Side"] == "Over")].drop(columns=["_type"])
    return std, gob, dem, None

# ── NBA Odds Scanner ──────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _run_odds_scanner():
    from src.core.odds_providers.fanduel    import FanDuelClient
    from src.core.analyzers.analyzer        import PropsAnalyzer
    from src.sports.nba.config import ODDS_API_KEY as _K, SPORT_MAP, REGIONS, ODDS_FORMAT, STAT_MAP
    from src.sports.nba.scanner import get_games

    def _ns(r):
        s, lg = str(r["Stat"]), str(r.get("League","")).upper()
        return f"1H {s}" if lg == "NBA1H" and not s.startswith("1H ") else s

    pp_df = _fetch_nba_pp_board()
    if not pp_df.empty:
        pp_df["Stat"] = pp_df.apply(_ns, axis=1)

    fd    = FanDuelClient(api_key=_api_key() or _K, sport_map=SPORT_MAP,
                          regions=REGIONS, odds_format=ODDS_FORMAT, stat_map=STAT_MAP)
    _, dt = get_games(date_offset=0, require_scheduled=True)
    fd_df = fd.get_all_odds(target_date=dt)

    if pp_df.empty or fd_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "Data source unavailable"

    df = PropsAnalyzer(pp_df, fd_df, league="NBA").calculate_edges()
    if df.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "No matches found"

    df = df.sort_values("Implied_Win_%", ascending=False)
    if "OddsType" in pp_df.columns:
        om = pp_df.set_index(["Player","Stat"])["OddsType"].to_dict()
        df["OddsType"] = df.apply(lambda r: om.get((r["Player"],r["Stat"]), "standard"), axis=1)
    else:
        df["OddsType"] = "standard"

    cols = ["Player","Stat","Side","Line"]
    if "FD_Line"   in df.columns: cols.append("FD_Line")
    if "Line_Diff" in df.columns: cols.append("Line_Diff")
    cols.append("Implied_Win_%")

    rename = {"FD_Line":"FD Line","Line_Diff":"Δ Line","Implied_Win_%":"Win %"}
    std = df[df["OddsType"].isin(["standard",""])][cols].rename(columns=rename)
    gob = df[(df["OddsType"] == "goblin") & (df["Side"] == "Over")][cols].rename(columns=rename)
    dem = df[(df["OddsType"] == "demon")  & (df["Side"] == "Over")][cols].rename(columns=rename)
    return std, gob, dem, None

# ── NBA AI Projections ────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _run_ai_projections():
    from src.sports.nba.scanner import get_all_projections
    df_h, models = _nba_session()
    if df_h is None or not models: return pd.DataFrame(), "Models not loaded"
    return get_all_projections(df_h, models, date_offset=0), None

# ── MLB Scanner ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _run_mlb():
    try:
        from src.sports.mlb.scanner import _ensure_session, get_all_projections
        b, p, m = _ensure_session()
        return get_all_projections(b, p, m), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=600, show_spinner=False)
def _run_tennis():
    """Run tennis scanner once per 10 min; returns (df, error_str)."""
    # First try an already-saved scan from today
    df = _latest_csv(os.path.join(_BASE, "output", "tennis", "scans", "scan_*.csv"))
    if not df.empty:
        return df, None
    try:
        from src.sports.tennis.scanner import (
            load_data, load_models, scan_all, load_player_cache, PLAYER_CACHE_FILE)
        from src.sports.tennis.rankings import TennisRankings
        cache_exists = os.path.exists(PLAYER_CACHE_FILE)
        df_hist = None if cache_exists else load_data()
        models  = load_models()
        if (df_hist is not None or cache_exists) and models:
            rankings = TennisRankings()
            try:
                scan_all(df_hist, models, rankings)
            except (EOFError, OSError):
                pass
            df = _latest_csv(os.path.join(_BASE, "output", "tennis", "scans", "scan_*.csv"))
            return df, None
        else:
            # No trained models — fall back to raw PrizePicks board
            from src.core.odds_providers.prizepicks import PrizePicksClient
            from src.sports.tennis.config import STAT_MAP
            pp = PrizePicksClient(stat_map=STAT_MAP)
            board = pp.fetch_board(include_alts=True)
            if not board.empty:
                tennis_board = board[board["League"].str.lower().str.contains("tennis", na=False)].copy()
                if not tennis_board.empty:
                    tennis_board["AI_Edge"] = None
                    tennis_board["Tier"]    = "—"
                    out_dir = os.path.join(_BASE, "output", "tennis", "scans")
                    os.makedirs(out_dir, exist_ok=True)
                    from datetime import date
                    tennis_board.to_csv(os.path.join(out_dir, f"scan_{date.today()}.csv"), index=False)
                    return tennis_board, None
            return pd.DataFrame(), None
    except Exception as e:
        import traceback
        return pd.DataFrame(), f"{e}\n{traceback.format_exc()}"

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_moneylines_cached(api_key: str):
    """ESPN free odds first — only falls back to Odds API if ESPN returns nothing."""
    try:
        from src.core.espn_odds import get_espn_odds
        lines = get_espn_odds()
        if lines:
            return lines, None
    except Exception:
        pass
    # Fallback: The Odds API (costs requests)
    try:
        from src.core.moneylines import fetch_moneylines
        return fetch_moneylines(api_key=api_key), None
    except Exception as e:
        return [], str(e)

@st.cache_data(ttl=86400, show_spinner=False)   # refresh once per day
def _get_photo_cache() -> dict:
    try:
        from src.core.player_photos import build_photo_cache
        return build_photo_cache()
    except Exception:
        return {}

def _add_photos(df, player_col="Player"):
    """Inject Image_URL column into df using cached ESPN headshots."""
    if df is None or df.empty or player_col not in df.columns:
        return df
    photos = _get_photo_cache()
    if not photos:
        return df
    def _lookup(name):
        nl = str(name).lower().strip()
        if nl in photos:
            return photos[nl]
        parts = nl.split()
        if len(parts) >= 2:
            last = parts[-1]
            matches = [v for k, v in photos.items() if k.endswith(last)]
            if len(matches) == 1:
                return matches[0]
        return ""
    df = df.copy()
    df["Image_URL"] = df[player_col].apply(_lookup)
    return df

# ── Metrics ───────────────────────────────────────────────────────────────────
def _metrics(sport):
    path = os.path.join(_BASE, "models", sport, "model_metrics.csv")
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()

# ── Render helpers ────────────────────────────────────────────────────────────
def _show_plays(df, label, badge_color="green", hide_side=False):
    if df.empty:
        _empty()
        return
    n = len(df)
    if hide_side:
        df = df.drop(columns=["Side"], errors="ignore")
    df = _round_df(df)
    st.markdown(f'<div class="section-header">{label} <span class="badge {badge_color}">{n} plays</span></div>',
                unsafe_allow_html=True)
    style = df.style
    if not hide_side and "Side" in df.columns: style = style.map(_style_side, subset=["Side"])
    if "Score" in df.columns: style = style.map(_style_score, subset=["Score"])
    st.dataframe(style, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# NAV
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="nav-bar">
    <div class="nav-logo">🎯 &nbsp;<span>Tank'd Picks</span></div>
    <div class="nav-badge">AI · Private · v2</div>
</div>
""", unsafe_allow_html=True)

sport = st.radio("", ["🏀 NBA", "⚾ MLB", "🏀 WNBA", "🎾 Tennis", "💰 Moneylines"],
                 horizontal=True, label_visibility="collapsed")

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# NBA
# ══════════════════════════════════════════════════════════════════════════════
if sport == "🏀 NBA":
    st.markdown(f'<div class="page-title-row"><img src="{_league_logo("NBA")}" /><div class="page-title">NBA Analysis</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Super Scanner · Odds Scanner · AI Projections</div>',
                unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["⚡  Super Scanner", "📊  Odds Scanner", "🤖  AI Projections", "📈  Metrics"])

    # Super Scanner
    with tab1:
        st.markdown('<div class="alert">Finds plays where <strong>FanDuel math edge</strong> and <strong>AI projection</strong> both agree on the same side.</div>',
                    unsafe_allow_html=True)

        col1, col2 = st.columns([1, 5])
        with col1:
            run = st.button("Run Scanner", key="ss_run")
        with col2:
            if st.button("↺  Refresh", key="ss_ref"):
                st.cache_data.clear(); st.rerun()

        if run or st.session_state.get("ss_done"):
            st.session_state["ss_done"] = True
            with st.spinner("Fetching odds & running AI…"):
                std, gob, dem, err = _run_super_scanner()

            if err:
                st.error(err)
            else:
                st.markdown(f"""
                <div class="chip-row">
                    <div class="chip">
                        <div class="chip-label">Standard</div>
                        <div class="chip-value green">{len(std)}</div>
                    </div>
                    <div class="chip">
                        <div class="chip-label">Goblin</div>
                        <div class="chip-value blue">{len(gob)}</div>
                    </div>
                    <div class="chip">
                        <div class="chip-label">Demon</div>
                        <div class="chip-value" style="color:#a855f7">{len(dem)}</div>
                    </div>
                    <div class="chip">
                        <div class="chip-label">Top Score</div>
                        <div class="chip-value green">{f"{std['Score'].max():.0f}" if not std.empty else '—'}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Top plays cards
                if not std.empty:
                    st.markdown('<div class="section-header" style="margin-top:8px">🔥 Top Plays</div>', unsafe_allow_html=True)
                    _top_plays_cards(_add_photos(std), img_col="Image_URL", name_col="Player",
                                     stat_col="Stat", line_col="PP_Line", tier_col="Tier")

                _show_plays(std, "Standard Lines")
                if not gob.empty:
                    _show_plays(gob, "🟢 Goblin Lines — Easier lines, lower payout", badge_color="blue", hide_side=True)
                if not dem.empty:
                    _show_plays(dem, "😈 Demon Lines — Harder lines, higher payout", badge_color="green", hide_side=True)
        else:
            _empty()

    # Odds Scanner
    with tab2:
        st.markdown('<div class="alert">Removes FanDuel vig to get true implied probability, then compares to PrizePicks line.</div>',
                    unsafe_allow_html=True)

        col1, col2 = st.columns([1, 5])
        with col1:
            run2 = st.button("Run Scanner", key="os_run")
        with col2:
            if st.button("↺  Refresh", key="os_ref"):
                st.cache_data.clear(); st.rerun()

        if run2 or st.session_state.get("os_done"):
            st.session_state["os_done"] = True
            with st.spinner("Fetching odds…"):
                std2, gob2, dem2, err2 = _run_odds_scanner()

            if err2:
                st.error(err2)
            else:
                _show_plays(std2.head(25), "Standard Lines")
                c1, c2 = st.columns(2)
                with c1:
                    if not gob2.empty:
                        _show_plays(gob2.head(20), "🟢 Goblin Lines — Easier, lower payout", badge_color="blue", hide_side=True)
                with c2:
                    if not dem2.empty:
                        _show_plays(dem2.head(20), "😈 Demon Lines — Harder, higher payout", badge_color="green", hide_side=True)
        else:
            _empty()

    # AI Projections
    with tab3:
        st.markdown('<div class="alert">XGBoost + LightGBM ensemble projections for today\'s slate.</div>',
                    unsafe_allow_html=True)

        col1, col2 = st.columns([1, 5])
        with col1:
            run3 = st.button("Run AI", key="ai_run")
        with col2:
            if st.button("↺  Refresh", key="ai_ref"):
                st.cache_data.clear(); st.rerun()

        if run3 or st.session_state.get("ai_done"):
            st.session_state["ai_done"] = True
            with st.spinner("Generating projections…"):
                proj, err3 = _run_ai_projections()

            if err3:
                st.error(err3)
            elif proj.empty:
                st.info("No projections available.")
            else:
                c1, c2 = st.columns([2, 1])
                with c1:
                    search = st.text_input("Search player", placeholder="e.g. LeBron", key="ai_srch")
                with c2:
                    opts = ["All"] + sorted(proj["Stat"].unique().tolist())
                    stat = st.selectbox("Stat", opts, key="ai_stat")

                if search: proj = proj[proj["Player"].str.lower().str.contains(search.lower(), na=False)]
                if stat != "All": proj = proj[proj["Stat"] == stat]

                st.markdown(f'<div class="section-header">Projections <span class="badge">{len(proj)}</span></div>',
                            unsafe_allow_html=True)
                st.dataframe(_round_df(proj), use_container_width=True, hide_index=True)
        else:
            _empty()

    # Metrics
    with tab4:
        df_m = _metrics("nba")
        if df_m.empty:
            st.info("No metrics found. Train models from the CLI first.")
        else:
            st.markdown('<div class="section-header">Model Performance</div>', unsafe_allow_html=True)
            st.dataframe(df_m, use_container_width=True, hide_index=True)
            if "Last_Updated" in df_m.columns:
                st.caption(f"Last trained: {df_m['Last_Updated'].iloc[-1]}")

# ══════════════════════════════════════════════════════════════════════════════
# MLB
# ══════════════════════════════════════════════════════════════════════════════
elif sport == "⚾ MLB":
    st.markdown(f'<div class="page-title-row"><img src="{_league_logo("MLB")}" /><div class="page-title">MLB Analysis</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Super Scanner · Odds Scanner · AI Projections</div>',
                unsafe_allow_html=True)

    tab_b, tab_p, tab_m = st.tabs(["🏏  AI Scanner (B) — Batters", "⚾  AI Scanner (P) — Pitchers", "📈  Metrics"])

    def _render_mlb_section(df_section, key_prefix, is_pitcher=False):
        """Render core table + splits + matchup for a batter or pitcher subset."""
        if df_section.empty:
            _empty("No plays found for this group.")
            return

        search = st.text_input("Search player", placeholder="e.g. Judge" if not is_pitcher else "e.g. Cole",
                               key=f"{key_prefix}_srch")
        if search:
            df_section = df_section[df_section["Player"].str.lower().str.contains(search.lower(), na=False)]

        # ── Build core columns (splits inline for batters) ────────────────
        core_cols = ["Player", "Stat_Label", "Side", "PP_Line", "AI_Proj", "Edge_Pct", "L5", "L10", "Tier"]
        if not is_pitcher:
            # Add pitcher hand splits right after Tier
            for sc in ["Pitch_Hand", "OPS_vs", "AVG_vs", "K_Pct_vs"]:
                if sc in df_section.columns:
                    core_cols.append(sc)
        core_show = [c for c in core_cols if c in df_section.columns]

        # ── Prep hand labels before splitting ────────────────────────────
        if "Pitch_Hand" in df_section.columns:
            df_section = df_section.copy()
            df_section["Pitch_Hand"] = df_section["Pitch_Hand"].fillna("?").replace(
                {"R": "vs RHP", "L": "vs LHP", "S": "vs Switch"}
            )

        # ── Split standard / goblin / demon ───────────────────────────────
        if "Is_Goblin" in df_section.columns:
            has_demon = "Is_Demon" in df_section.columns
            std_rows = df_section[~df_section["Is_Goblin"] & (~df_section["Is_Demon"] if has_demon else True)]
            gob_rows = df_section[df_section["Is_Goblin"] & (df_section["Side"] == "Over")]
            dem_rows = df_section[df_section["Is_Demon"]  & (df_section["Side"] == "Over")] if has_demon else pd.DataFrame()
        else:
            std_rows = df_section
            gob_rows = pd.DataFrame()
            dem_rows = pd.DataFrame()

        # ── Chip counts ───────────────────────────────────────────────────
        st.markdown(f"""
        <div class="chip-row">
            <div class="chip"><div class="chip-label">Standard</div><div class="chip-value green">{len(std_rows)}</div></div>
            <div class="chip"><div class="chip-label">Goblin</div><div class="chip-value blue">{len(gob_rows)}</div></div>
            <div class="chip"><div class="chip-label">Demon</div><div class="chip-value" style="color:#a855f7">{len(dem_rows)}</div></div>
        </div>
        """, unsafe_allow_html=True)

        def _mlb_table(rows, label, hide_side=False):
            if rows.empty: return
            st.markdown(f'<div class="section-header">{label} <span class="badge">{len(rows)}</span></div>',
                        unsafe_allow_html=True)
            show_cols = [c for c in core_show if not (hide_side and c == "Side")]
            d = _round_df_mlb(rows[show_cols])
            s = d.style
            if not hide_side and "Side" in d.columns: s = s.map(_style_side, subset=["Side"])
            st.dataframe(s, use_container_width=True, hide_index=True)

        # Top plays cards
        if not std_rows.empty:
            label_txt = "🔥 Top Pitcher Picks" if is_pitcher else "🔥 Top Batter Picks"
            st.markdown(f'<div class="section-header" style="margin-top:8px">{label_txt}</div>', unsafe_allow_html=True)
            sort_col = "Edge_Pct" if "Edge_Pct" in std_rows.columns else (
                       "AI_Edge"  if "AI_Edge"  in std_rows.columns else std_rows.columns[0])
            top_sorted = std_rows.sort_values(sort_col, ascending=False) if sort_col in std_rows.columns else std_rows
            _top_plays_cards(_add_photos(top_sorted), img_col="Image_URL", name_col="Player",
                             stat_col="Stat_Label" if "Stat_Label" in std_rows.columns else "Stat",
                             line_col="PP_Line" if "PP_Line" in std_rows.columns else "Line",
                             tier_col="Tier" if "Tier" in std_rows.columns else std_rows.columns[0])

        _mlb_table(std_rows, "Standard Lines")
        _mlb_table(gob_rows, "🟢 Goblin Lines — Easier lines, lower payout", hide_side=True)
        _mlb_table(dem_rows, "😈 Demon Lines — Harder lines, higher payout", hide_side=True)

        # ── Pitching matchup & game context (expander) ────────────────────
        def_cols = ["Player", "Stat_Label", "OPP_PITCHER", "OPP_TEAM",
                    "DEF_ERA", "DEF_WHIP", "DEF_OPS",
                    "Game_Total", "Implied", "Wind_Speed", "Temp_F"]
        def_show = [c for c in def_cols if c in df_section.columns]
        if any(c in df_section.columns for c in ["DEF_ERA", "Game_Total"]) and len(def_show) > 2:
            ctx_label = "🏟️ Game Context & Opponent Stats" if is_pitcher else "🏟️ Pitching Matchup & Game Context"
            with st.expander(ctx_label):
                st.dataframe(_round_df_mlb(df_section[def_show].copy()), use_container_width=True, hide_index=True)

    # ── Load data once, shared between both tabs ──────────────────────────────
    col1, col2 = st.columns([1, 5])
    with col1:
        run_m = st.button("Run Scanner", key="mlb_run")
    with col2:
        if st.button("↺  Refresh", key="mlb_ref"):
            st.cache_data.clear(); st.rerun()

    if run_m or st.session_state.get("mlb_done"):
        st.session_state["mlb_done"] = True
        with st.spinner("Running MLB scanner…"):
            df_mlb, err = _run_mlb()

        if err:
            st.warning(f"Live scan error: {err}")
            df_mlb = _latest_csv(os.path.join(_BASE, "output", "mlb", "scans", "scan_*.csv"))

        if df_mlb.empty:
            st.info("No MLB data. Run Build Data → Features → Train from the CLI first.")
        else:
            batters  = df_mlb[df_mlb["Is_Pitcher"] == False].copy() if "Is_Pitcher" in df_mlb.columns else df_mlb.copy()
            pitchers = df_mlb[df_mlb["Is_Pitcher"] == True].copy()  if "Is_Pitcher" in df_mlb.columns else pd.DataFrame()

            with tab_b:
                _render_mlb_section(batters, key_prefix="bat", is_pitcher=False)
            with tab_p:
                _render_mlb_section(pitchers, key_prefix="pit", is_pitcher=True)
    else:
        with tab_b:
            _empty()
        with tab_p:
            _empty()

    with tab_m:
        df_m = _metrics("mlb")
        if df_m.empty:
            st.info("No metrics found. Train models from the CLI first.")
        else:
            st.dataframe(_round_df(df_m), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# WNBA
# ══════════════════════════════════════════════════════════════════════════════
elif sport == "🏀 WNBA":
    st.markdown(f'<div class="page-title-row"><img src="{_league_logo("WNBA")}" /><div class="page-title">WNBA Analysis</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Super Scanner · Odds Scanner · AI Projections</div>',
                unsafe_allow_html=True)

    col1, col2 = st.columns([1, 5])
    with col1:
        run_w = st.button("Run Scanner", key="wnba_run")
    with col2:
        if st.button("↺  Refresh", key="wnba_ref"):
            st.cache_data.clear(); st.rerun()

    if run_w or st.session_state.get("wnba_done"):
        st.session_state["wnba_done"] = True
        with st.spinner("Running WNBA scanner…"):
            df_w = _latest_csv(os.path.join(_BASE, "output", "wnba", "scans", "scan_*.csv"))
            if df_w.empty:
                try:
                    from src.sports.wnba.scanner import scan_wnba
                    scan_wnba()
                    df_w = _latest_csv(os.path.join(_BASE, "output", "wnba", "scans", "scan_*.csv"))
                except Exception as e:
                    st.error(str(e))

        if df_w.empty:
            st.info("No WNBA data available.")
        else:
            # ── Inject goblin/demon lines enriched with same AI data as standard ──
            try:
                from src.core.odds_providers.prizepicks import PrizePicksClient as _PPC
                _pp_w = _PPC(stat_map={}).fetch_board(league_filter='WNBA', include_alts=True)
                if not _pp_w.empty and 'OddsType' in _pp_w.columns:
                    _alt_w = _pp_w[_pp_w['OddsType'].isin(['goblin','demon'])].copy()
                    if not _alt_w.empty:
                        _alt_w = _alt_w.rename(columns={'Line':'PP_Line'})
                        _alt_w['Is_Goblin'] = _alt_w['OddsType'] == 'goblin'
                        _alt_w['Is_Demon']  = _alt_w['OddsType'] == 'demon'
                        _alt_w['Side'] = 'Over'
                        # Build AI lookup from standard rows (no duplicate cols)
                        _ai_extra = [c for c in df_w.columns
                                     if c not in ('Player','Stat','PP_Line','Is_Goblin','Is_Demon','OddsType','Side')]
                        _lookup = df_w[['Player','Stat'] + _ai_extra].drop_duplicates(['Player','Stat'])
                        # Drop any PP cols that exist in _alt_w before merge to avoid duplication
                        _alt_w = _alt_w[[c for c in _alt_w.columns if c not in _ai_extra]]
                        _alt_w = _alt_w.merge(_lookup, on=['Player','Stat'], how='left')
                        # Drop any leftover _x/_y duplicate cols
                        _alt_w = _alt_w.loc[:, ~_alt_w.columns.duplicated()]
                        # Recompute edge vs the alt line
                        if 'AI_Proj' in _alt_w.columns and 'PP_Line' in _alt_w.columns:
                            _alt_w['AI_Edge'] = pd.to_numeric(_alt_w['AI_Proj'], errors='coerce') - pd.to_numeric(_alt_w['PP_Line'], errors='coerce')
                        _gob_w = _alt_w[_alt_w['Is_Goblin']].copy()
                        _dem_w = _alt_w[_alt_w['Is_Demon']].copy()
                        # Demons only if AI projects OVER (edge > 0)
                        if 'AI_Edge' in _dem_w.columns:
                            _dem_w = _dem_w[pd.to_numeric(_dem_w['AI_Edge'], errors='coerce') > 0]
                        _to_add = pd.concat([_gob_w, _dem_w], ignore_index=True)
                        if not _to_add.empty:
                            df_w = pd.concat([df_w, _to_add], ignore_index=True)
                            df_w = df_w.loc[:, ~df_w.columns.duplicated()]
            except Exception as _ew:
                st.caption(f"⚠️ WNBA alt-line fetch skipped: {_ew}")

            search = st.text_input("Search player", key="wnba_srch")
            col_name = "Player" if "Player" in df_w.columns else df_w.columns[0]
            if search:
                df_w = df_w[df_w[col_name].str.lower().str.contains(search.lower(), na=False)]

            # Split by line type using Is_Goblin / Is_Demon flags
            if "Is_Goblin" in df_w.columns and "Is_Demon" in df_w.columns:
                wnba_std = df_w[(df_w["Is_Goblin"] == False) & (df_w["Is_Demon"] == False)]
                wnba_gob = df_w[df_w["Is_Goblin"] == True]
                wnba_dem = df_w[df_w["Is_Demon"]  == True]
            elif "Is_Goblin" in df_w.columns:
                wnba_std = df_w[df_w["Is_Goblin"] == False]
                wnba_gob = df_w[df_w["Is_Goblin"] == True]
                wnba_dem = pd.DataFrame()
            elif "OddsType" in df_w.columns:
                wnba_std = df_w[df_w["OddsType"].isin(["standard", ""])]
                wnba_gob = df_w[df_w["OddsType"] == "goblin"]
                wnba_dem = df_w[df_w["OddsType"] == "demon"]
            else:
                wnba_std = df_w
                wnba_gob = pd.DataFrame()
                wnba_dem = pd.DataFrame()

            # Chip counts row
            n_std = len(wnba_std); n_gob = len(wnba_gob); n_dem = len(wnba_dem)
            st.markdown(f"""
            <div class="chip-row">
                <div class="chip">
                    <div class="chip-label">Standard</div>
                    <div class="chip-value green">{n_std}</div>
                </div>
                <div class="chip">
                    <div class="chip-label">Goblin</div>
                    <div class="chip-value blue">{n_gob}</div>
                </div>
                <div class="chip">
                    <div class="chip-label">Demon</div>
                    <div class="chip-value" style="color:#a855f7">{n_dem}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            def _wnba_table(rows, label, hide_side=False):
                if rows is None or (hasattr(rows, "empty") and rows.empty): return
                st.markdown(f'<div class="section-header">{label} <span class="badge">{len(rows)}</span></div>',
                            unsafe_allow_html=True)
                drop_cols = [c for c in ["Is_Goblin", "Is_Demon", "OddsType", "League", "Date", "Image_URL",
                                         "Tier_Key", "REC", "TARGET"] if c in rows.columns]
                if hide_side:
                    drop_cols += ["Side"]
                d = _round_df(rows.drop(columns=drop_cols, errors="ignore"))
                # Drop columns that are entirely NaN (happen when goblin/demon merge found no match)
                d = d.dropna(axis=1, how="all")
                s = d.style
                if not hide_side and "Side" in d.columns: s = s.map(_style_side, subset=["Side"])
                st.dataframe(s, use_container_width=True, hide_index=True)

            # Top plays cards
            if not wnba_std.empty:
                st.markdown('<div class="section-header" style="margin-top:8px">🔥 Top Plays</div>', unsafe_allow_html=True)
                _top_plays_cards(_add_photos(wnba_std.sort_values("Signal", ascending=False) if "Signal" in wnba_std.columns else wnba_std),
                                 img_col="Image_URL", name_col="Player",
                                 stat_col="Stat", line_col="PP_Line", tier_col="Tier_Emoji")

            _wnba_table(wnba_std, "📋 Standard Lines")
            if not wnba_gob.empty or not wnba_dem.empty:
                _gc, _dc = st.columns(2)
                with _gc:
                    _wnba_table(wnba_gob, "🟢 Goblin Lines", hide_side=True)
                with _dc:
                    _wnba_table(wnba_dem, "😈 Demon Lines", hide_side=True)
    else:
        _empty()

# ══════════════════════════════════════════════════════════════════════════════
# Tennis
# ══════════════════════════════════════════════════════════════════════════════
elif sport == "🎾 Tennis":
    st.markdown(f'<div class="page-title-row"><div style="font-size:2rem">🎾</div><div class="page-title">Tennis Analysis</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Super Scanner · Odds Scanner · AI Projections</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 5])
    with col1:
        run_ten = st.button("Run Scanner", key="ten_run")
    with col2:
        if st.button("↺  Refresh", key="ten_ref"):
            st.cache_data.clear(); st.rerun()

    if run_ten or st.session_state.get("ten_done"):
        st.session_state["ten_done"] = True
        with st.spinner("Running Tennis scanner…"):
            df_ten, ten_err = _run_tennis()
            if ten_err:
                st.error(ten_err)

        if df_ten.empty:
            st.info("No tennis lines on PrizePicks right now — they're usually posted 1–2 days before matches.")
        else:
            # Column name normalisation — do this FIRST before injecting alts
            col_map = {
                "NAME":           "Player",
                "FLAG":           "Flag",
                "TARGET_DISPLAY": "Stat",
                "PP":             "PP_Line",
                "AI":             "AI_Proj",
                "EDGE":           "AI_Edge",
                "PCT_EDGE":       "Edge_Pct",
                "TIER":           "Tier",
                "OPPONENT":       "Opponent",
                "TIER_KEY":       "Tier_Key",
                "SURFACE":        "Surface",
                "PF_HR5":         "HR5",
                "PF_HR10":        "HR10",
                "PF_STRK":        "Streak",
                "PF_CON_O":       "Con_Over",
                "PF_CON_U":       "Con_Under",
                "PF_NET_MOV":     "Net_Move",
                "REC":            "Pick",
            }
            df_ten = df_ten.rename(columns={k: v for k, v in col_map.items() if k in df_ten.columns})
            df_ten = df_ten.loc[:, ~df_ten.columns.duplicated()]


            search = st.text_input("Search player", key="ten_srch")
            if search:
                p_col = "Player" if "Player" in df_ten.columns else df_ten.columns[0]
                df_ten = df_ten[df_ten[p_col].str.lower().str.contains(search.lower(), na=False)]

            # Determine if we have real AI projections or just raw PP board
            has_ai = ("AI_Edge" in df_ten.columns and df_ten["AI_Edge"].notna().any())

            ten_over  = df_ten[df_ten["AI_Edge"] > 0].copy() if has_ai else pd.DataFrame()
            ten_under = df_ten[df_ten["AI_Edge"] < 0].copy() if has_ai else pd.DataFrame()

            n_players = df_ten["Player"].nunique() if "Player" in df_ten.columns else "—"

            if has_ai:
                st.markdown(f"""<div class="chip-row">
                    <div class="chip"><div class="chip-label">Total Plays</div><div class="chip-value green">{len(df_ten)}</div></div>
                    <div class="chip"><div class="chip-label">Overs</div><div class="chip-value blue">{len(ten_over)}</div></div>
                    <div class="chip"><div class="chip-label">Unders</div><div class="chip-value" style="color:#f59e0b">{len(ten_under)}</div></div>
                    <div class="chip"><div class="chip-label">Players</div><div class="chip-value">{n_players}</div></div>
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div class="alert">No trained tennis models found — showing live PrizePicks board. '
                    'Run <code>train.py</code> to enable AI projections.</div>',
                    unsafe_allow_html=True)
                st.markdown(f"""<div class="chip-row">
                    <div class="chip"><div class="chip-label">Total Lines</div><div class="chip-value green">{len(df_ten)}</div></div>
                    <div class="chip"><div class="chip-label">Players</div><div class="chip-value">{n_players}</div></div>
                </div>""", unsafe_allow_html=True)

            _CLEAN_COLS = ["Tier_Key", "REC", "TARGET", "Is_Goblin", "Is_Demon", "OddsType",
                           "League", "Date", "Image_URL", "NAME", "TARGET_DISPLAY",
                           "THRESHOLD", "PP", "AI", "EDGE", "EDGE_PCT"]

            def _ten_table(rows, label, hide_side=False):
                if rows is None or (hasattr(rows, "empty") and rows.empty): return
                st.markdown(f'<div class="section-header">{label} <span class="badge">{len(rows)}</span></div>',
                            unsafe_allow_html=True)
                drop_cols = [c for c in _CLEAN_COLS if c in rows.columns]
                if hide_side: drop_cols += ["Side"]
                d = rows.drop(columns=drop_cols, errors="ignore").copy()
                # Reorder so Opponent appears right after Tier
                preferred = ["Pick", "Flag", "Player", "Stat", "PP_Line", "AI_Proj", "AI_Edge", "Edge_Pct",
                             "Tier", "Opponent", "Surface", "HR5", "HR10", "Streak",
                             "Con_Over", "Con_Under", "Net_Move"]
                ordered = [c for c in preferred if c in d.columns]
                rest    = [c for c in d.columns if c not in ordered]
                d = d[ordered + rest]
                d = _round_df(d)
                d = d.dropna(axis=1, how="all")
                st.dataframe(d.style, use_container_width=True, hide_index=True)

            if has_ai:
                if not ten_over.empty:
                    sort_col = "Edge_Pct" if "Edge_Pct" in ten_over.columns else "AI_Edge"
                    top_over = ten_over.sort_values(sort_col, ascending=False)
                    st.markdown('<div class="section-header" style="margin-top:8px">🔥 Top Over Picks</div>', unsafe_allow_html=True)
                    _top_plays_cards(_add_photos(top_over), img_col="Image_URL", name_col="Player",
                                     stat_col="Stat", line_col="PP_Line", tier_col="Tier")
                _ten_table(ten_over,  "🟢 Overs — AI projects above the line")
                _ten_table(ten_under, "🔴 Unders — AI projects below the line")
            else:
                if not df_ten.empty:
                    st.markdown('<div class="section-header" style="margin-top:8px">🎾 Today\'s Board</div>', unsafe_allow_html=True)
                    _top_plays_cards(_add_photos(df_ten), img_col="Image_URL", name_col="Player",
                                     stat_col="Stat",
                                     line_col="PP_Line" if "PP_Line" in df_ten.columns else "Line",
                                     tier_col="Tier" if "Tier" in df_ten.columns else df_ten.columns[0])
                _ten_table(df_ten, "📋 All Lines")
    else:
        _empty()

    # ── Match Win Odds — always shown, independent of scanner ─────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-header" style="font-size:0.9rem;color:#94a3b8;margin-bottom:16px">🎾 MATCH WIN ODDS</div>', unsafe_allow_html=True)

    with st.spinner("Fetching match odds…"):
        match_odds = _fetch_tennis_match_odds(_api_key())

    if not match_odds:
        st.info("No tennis match odds available right now.")
    else:
        by_tourney = {}
        for m in match_odds:
            by_tourney.setdefault(m["tournament"], []).append(m)

        def _odds_cls(is_fav):
            return "ml-odds-neg" if is_fav else "ml-odds-pos"

        def _player_card(m, is_fav):
            photo_url = m.get("photo", "")
            img_html  = (
                f'<img src="{photo_url}" style="width:56px;height:56px;border-radius:50%;object-fit:cover;background:#1e2837" onerror="this.style.display=\'none\'" />'
                if photo_url else
                '<div style="width:56px;height:56px;border-radius:50%;background:#1e2837;display:flex;align-items:center;justify-content:center;font-size:1.5rem;">🎾</div>'
            )
            odds_str   = f"+{int(m['best_odds'])}" if m['best_odds'] >= 0 else str(int(m['best_odds']))
            book_chips = "".join(
                f'<div class="ml-book-chip{" best-odds" if v == m["best_odds"] else ""}">'
                f'<span class="bk-name">{bk}</span>'
                f'<span class="bk-odds">{"+" if v >= 0 else ""}{int(v)}</span></div>'
                for bk, v in m["book_odds"].items()
            )
            fav_badge = '<span style="font-size:0.6rem;background:#052e16;color:#22c55e;padding:2px 6px;border-radius:4px;margin-left:5px">FAV</span>' if is_fav else ""
            return f"""
            <div style="display:flex;flex-direction:column;align-items:center;text-align:center;gap:7px;flex:1;padding:16px 12px">
                {img_html}
                <div style="font-size:0.85rem;font-weight:600;color:#f0f6ff;line-height:1.3">{m['player']}{fav_badge}</div>
                <div class="{_odds_cls(is_fav)}" style="font-size:1.15rem;font-weight:700">{odds_str} <span style="font-size:0.68rem;color:#475569;font-weight:400">best</span></div>
                <div style="font-size:0.7rem;color:#475569">{m['win_pct']}% win · {m['best_book']}</div>
                <div class="ml-books-row" style="justify-content:center">{book_chips}</div>
            </div>"""

        for tourney, players in by_tourney.items():
            st.markdown(f'<div class="ml-sport-title" style="margin-top:16px">🏆 {tourney}</div>', unsafe_allow_html=True)

            seen_matches = set()
            match_pairs  = []
            for m in players:
                key = tuple(sorted([m["player"], m["opponent"]]))
                if key in seen_matches: continue
                seen_matches.add(key)
                other = next((x for x in players if x["player"] == m["opponent"]), None)
                if other:
                    # sort: fav (lower avg_odds) on right, dog on left
                    fav, dog = (m, other) if m["avg_odds"] <= other["avg_odds"] else (other, m)
                    match_pairs.append((fav, dog))

            for fav_m, dog_m in match_pairs:
                st.markdown(f"""
                <div class="ml-game-card" style="grid-template-columns:1fr auto 1fr;gap:0;margin-bottom:10px">
                    {_player_card(dog_m, False)}
                    <div class="ml-center" style="padding:14px 8px;border-left:1px solid #1a2332;border-right:1px solid #1a2332;min-width:60px">
                        <div class="ml-time">{fav_m['time']}</div>
                        <div class="ml-vs" style="margin-top:8px">VS</div>
                    </div>
                    {_player_card(fav_m, True)}
                </div>
                """, unsafe_allow_html=True)

    # ── AI Match Predictor ────────────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("""
    <div class="page-title-row" style="margin-bottom:4px">
        <div class="page-title" style="font-size:1.1rem">🤖 AI Match Predictor</div>
    </div>
    <div class="page-subtitle">Select two players and surface — AI gives win probability based on 1.8M matches of historical data</div>
    """, unsafe_allow_html=True)

    _mw_model_exists = os.path.exists(
        os.path.join(_BASE, 'models', 'tennis', 'match_win_model.json'))

    if not _mw_model_exists:
        st.warning("⚙️ Match win model not trained yet. Run: `python3 -m src.sports.tennis.match_win_train`")
    else:
        try:
            from src.sports.tennis.match_predictor import get_all_players, predict_match as _predict_match
            _all_players = get_all_players()

            _mc1, _mc2, _mc3, _mc4 = st.columns([2.5, 2.5, 1.2, 1])
            with _mc1:
                _p1 = st.selectbox("Player 1", _all_players, key="mp_p1",
                                   index=_all_players.index("Novak Djokovic") if "Novak Djokovic" in _all_players else 0)
            with _mc2:
                _p2_default = "Carlos Alcaraz" if "Carlos Alcaraz" in _all_players else _all_players[1]
                _p2 = st.selectbox("Player 2", _all_players, key="mp_p2",
                                   index=_all_players.index(_p2_default))
            with _mc3:
                _surf = st.selectbox("Surface", ["Hard", "Clay", "Grass"], key="mp_surf")
            with _mc4:
                _bo   = st.selectbox("Format", ["Best of 3", "Best of 5"], key="mp_bo")

            _run_pred = st.button("⚡ Predict", key="mp_run", use_container_width=False)

            if _run_pred or st.session_state.get("mp_result"):
                if _run_pred:
                    with st.spinner("Running AI prediction…"):
                        _res = _predict_match(
                            _p1, _p2,
                            surface=_surf.lower(),
                            best_of=5 if "5" in _bo else 3
                        )
                    st.session_state["mp_result"] = _res
                else:
                    _res = st.session_state["mp_result"]

                if _res:
                    _fav = _res if _res['p1_win_pct'] >= _res['p2_win_pct'] else {
                        'p1_name': _res['p2_name'], 'p1_win_pct': _res['p2_win_pct'],
                        'p2_name': _res['p1_name'], 'p2_win_pct': _res['p1_win_pct'],
                        'p1_rank': _res['p2_rank'], 'p2_rank': _res['p1_rank'],
                        'confidence': _res['confidence'], 'found_p1': _res['found_p2'],
                        'found_p2': _res['found_p1'], 'surface': _res['surface'],
                    }

                    _conf_colors = {"HIGH": ("#22c55e", "linear-gradient(90deg,#16a34a,#22c55e)"),
                                    "MEDIUM": ("#f59e0b", "linear-gradient(90deg,#b45309,#f59e0b)"),
                                    "LOW":  ("#ef4444", "linear-gradient(90deg,#991b1b,#ef4444)")}
                    _cc, _cg = _conf_colors.get(_res['confidence'], ("#94a3b8", "#334155"))

                    _fav_pct = max(_res['p1_win_pct'], _res['p2_win_pct'])
                    _dog_pct = min(_res['p1_win_pct'], _res['p2_win_pct'])
                    _fav_name = _res['p1_name'] if _res['p1_win_pct'] >= _res['p2_win_pct'] else _res['p2_name']
                    _dog_name = _res['p2_name'] if _fav_name == _res['p1_name'] else _res['p1_name']
                    _fav_rank = (_res['p1_rank'] if _fav_name == _res['p1_name'] else _res['p2_rank']) or "—"
                    _dog_rank = (_res['p2_rank'] if _fav_name == _res['p1_name'] else _res['p1_rank']) or "—"

                    st.markdown(f"""
                    <div style="background:#080e18;border:1px solid #151f2e;border-top:3px solid {_cc};
                                border-radius:16px;padding:24px 28px;margin-top:12px">

                        <!-- Header -->
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
                            <div style="font-size:0.65rem;font-weight:700;color:#2d3f52;letter-spacing:1.5px;text-transform:uppercase">
                                AI MATCH PREDICTION · {_surf.upper()} · {_bo.upper()}
                            </div>
                            <div style="font-size:0.6rem;font-weight:800;letter-spacing:1px;text-transform:uppercase;
                                        padding:3px 10px;border-radius:99px;border:1px solid {_cc};color:{_cc}">
                                {_res['confidence']} CONFIDENCE
                            </div>
                        </div>

                        <!-- Players row -->
                        <div style="display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px;margin-bottom:22px">
                            <!-- Favourite -->
                            <div style="text-align:left">
                                <div style="font-size:0.65rem;color:#2d3f52;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px">FAVOURITE</div>
                                <div style="font-size:1.1rem;font-weight:800;color:#e2e8f0;line-height:1.2">{_fav_name}</div>
                                <div style="font-size:0.7rem;color:#334155;margin-top:2px">Rank #{_fav_rank}</div>
                                <div style="font-size:2rem;font-weight:900;color:{_cc};margin-top:8px;letter-spacing:-1px">{_fav_pct}%</div>
                                <div style="font-size:0.65rem;color:#2d3f52;font-weight:600;letter-spacing:0.5px">WIN PROBABILITY</div>
                            </div>

                            <!-- VS divider -->
                            <div style="text-align:center;padding:0 16px;border-left:1px solid #0f1825;border-right:1px solid #0f1825">
                                <div style="font-size:1rem;font-weight:900;color:#1e2837;letter-spacing:3px">VS</div>
                                <div style="font-size:0.58rem;color:#1a2332;margin-top:6px">🎾 {_surf}</div>
                            </div>

                            <!-- Underdog -->
                            <div style="text-align:right">
                                <div style="font-size:0.65rem;color:#2d3f52;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px">UNDERDOG</div>
                                <div style="font-size:1.1rem;font-weight:800;color:#94a3b8;line-height:1.2">{_dog_name}</div>
                                <div style="font-size:0.7rem;color:#334155;margin-top:2px">Rank #{_dog_rank}</div>
                                <div style="font-size:2rem;font-weight:900;color:#334155;margin-top:8px;letter-spacing:-1px">{_dog_pct}%</div>
                                <div style="font-size:0.65rem;color:#2d3f52;font-weight:600;letter-spacing:0.5px">WIN PROBABILITY</div>
                            </div>
                        </div>

                        <!-- Probability bar -->
                        <div style="margin-bottom:10px">
                            <div style="display:flex;justify-content:space-between;font-size:0.65rem;color:#2d3f52;margin-bottom:6px">
                                <span style="color:{_cc};font-weight:700">{_fav_name}</span>
                                <span>{_dog_name}</span>
                            </div>
                            <div style="background:#060c14;border-radius:99px;height:10px;overflow:hidden;position:relative">
                                <div style="width:{_fav_pct}%;height:100%;background:{_cg};border-radius:99px;
                                            box-shadow:0 0 12px rgba(34,197,94,0.3)"></div>
                            </div>
                            <div style="display:flex;justify-content:space-between;font-size:0.62rem;color:#1a2332;margin-top:4px">
                                <span>{_fav_pct}%</span>
                                <span>{_dog_pct}%</span>
                            </div>
                        </div>

                        <!-- Footer note -->
                        <div style="font-size:0.62rem;color:#1a2332;margin-top:14px;padding-top:12px;border-top:1px solid #0a1020;text-align:center">
                            Based on rankings, form, H2H, surface stats & rolling 5/20 game windows · 1.84M historical matches
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Warn if player not found in cache
                    if not _res['found_p1']:
                        st.caption(f"⚠️ '{_p1}' not found in historical data — using average stats")
                    if not _res['found_p2']:
                        st.caption(f"⚠️ '{_p2}' not found in historical data — using average stats")

        except Exception as _mp_err:
            st.error(f"Predictor error: {_mp_err}")

# ══════════════════════════════════════════════════════════════════════════════
# Moneylines
# ══════════════════════════════════════════════════════════════════════════════
elif sport == "💰 Moneylines":
    st.markdown('<div class="page-title">💰 Moneylines</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Team moneylines & game totals across NBA · MLB · WNBA</div>',
                unsafe_allow_html=True)

    col1, col2 = st.columns([1, 5])
    with col1:
        run_ml = st.button("Fetch Lines", key="ml_run")
    with col2:
        if st.button("↺  Refresh", key="ml_ref"):
            st.cache_data.clear(); st.rerun()

    if run_ml or st.session_state.get("ml_done"):
        st.session_state["ml_done"] = True
        with st.spinner("Fetching moneylines & totals…"):
            try:
                from src.core.moneylines import BOOK_LABELS
                from datetime import datetime
                from zoneinfo import ZoneInfo

                lines, _ml_err = _fetch_moneylines_cached(_api_key())
                if _ml_err:
                    st.error(_ml_err)
                if not lines:
                    st.info("No moneyline data available.")
                else:
                    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
                    df_ml = pd.DataFrame([r for r in lines if r.get("Date", today) >= today])

                    if df_ml.empty:
                        st.info("No upcoming games found.")
                    else:
                        if "Implied" in df_ml.columns and "Win %" not in df_ml.columns:
                            df_ml = df_ml.rename(columns={"Implied": "Win %"})

                        book_cols = [b for b in BOOK_LABELS.values() if b in df_ml.columns]

                        def _fmt_odds(x):
                            try:
                                v = float(x)
                                # Reject junk values — real moneylines are always |v| >= 100
                                if abs(v) < 100:
                                    return "—"
                                return f"+{int(v)}" if v >= 0 else str(int(v))
                            except Exception:
                                return "—"

                        def _ml_game_cards(sub, sport_key):
                            """Render game cards with logos for one sport."""
                            # Build unique game list (home team as anchor)
                            seen = set()
                            games = []
                            for _, row in sub.iterrows():
                                gk = tuple(sorted([row["Team"], row["Opponent"]]))
                                if gk in seen: continue
                                seen.add(gk)
                                home = row["Team"] if row.get("Home") else row["Opponent"]
                                away = row["Opponent"] if row.get("Home") else row["Team"]
                                # find away row
                                away_rows = sub[sub["Team"] == away]
                                home_row  = sub[sub["Team"] == home]
                                if away_rows.empty or home_row.empty: continue
                                games.append((home_row.iloc[0], away_rows.iloc[0]))

                            n_games = len(games)
                            league_logo = _league_logo(sport_key)
                            st.markdown(
                                f'<div class="ml-sport-title">'
                                f'<img src="{league_logo}" />'
                                f'{sport_key} &nbsp;<span style="color:#334155;font-weight:400">{n_games} games</span>'
                                f'</div>',
                                unsafe_allow_html=True
                            )

                            for home_r, away_r in games:
                                home_name  = home_r["Team"]
                                away_name  = away_r["Team"]
                                home_logo  = _team_logo(home_name, sport_key)
                                away_logo  = _team_logo(away_name, sport_key)
                                home_odds  = _fmt_odds(home_r.get("Avg Odds", ""))
                                away_odds  = _fmt_odds(away_r.get("Avg Odds", ""))

                                # Safe float conversion for win %
                                def _safe_pct(row, key="Win %"):
                                    try:
                                        v = float(row.get(key) or 0)
                                        return v if 0 < v <= 100 else None
                                    except Exception:
                                        return None

                                home_pct_v = _safe_pct(home_r)
                                away_pct_v = _safe_pct(away_r)
                                home_pct_str = f"{home_pct_v:.1f}% implied" if home_pct_v else ""
                                away_pct_str = f"{away_pct_v:.1f}% implied" if away_pct_v else ""

                                game_time  = home_r.get("Time", "")
                                total      = home_r.get("Game Total", "")
                                over_odds  = _fmt_odds(home_r.get("Over Odds", ""))
                                under_odds = _fmt_odds(home_r.get("Under Odds", ""))
                                total_str  = f"O/U {total}  ({over_odds} / {under_odds})" if total else ""

                                # Skip card if both sides have no valid odds
                                if home_odds == "—" and away_odds == "—":
                                    continue

                                def _safe_raw_odds(row, key="Avg Odds"):
                                    try: return float(row.get(key) or 0)
                                    except Exception: return 0

                                home_odds_cls = "ml-odds-neg" if _safe_raw_odds(home_r) < 0 else "ml-odds-pos"
                                away_odds_cls = "ml-odds-neg" if _safe_raw_odds(away_r) < 0 else "ml-odds-pos"

                                # ── Composite AI confidence meter ──────────────────
                                def _safe_conf(row):
                                    try: return float(row.get("AI Conf") or row.get("Win %") or 50)
                                    except Exception: return 50.0

                                _hc = _safe_conf(home_r)
                                _ac = _safe_conf(away_r)
                                # Use raw AI Conf directly — already stretched to 12-88% range.
                                # Do NOT re-normalise; that would collapse the spread back to ~50%.
                                if _hc >= _ac:
                                    _fav_name  = home_name
                                    _fav_pct   = round(_hc, 1)
                                    _dog_name  = away_name
                                    _dog_pct   = round(_ac, 1)
                                    _fav_rec   = home_r.get("Record", "")
                                    _dog_rec   = away_r.get("Record", "")
                                    _fav_pitch = home_r.get("Pitcher", "")
                                else:
                                    _fav_name  = away_name
                                    _fav_pct   = round(_ac, 1)
                                    _dog_name  = home_name
                                    _dog_pct   = round(_hc, 1)
                                    _fav_rec   = away_r.get("Record", "")
                                    _dog_rec   = home_r.get("Record", "")
                                    _fav_pitch = away_r.get("Pitcher", "")

                                # Color thresholds (raw AI Conf, 12-88% scale)
                                # 80+ = LOCK (gold), 60-79 = CONFIDENT (green),
                                # 54-59 = LEAN (yellow), <54 = TOSS-UP (red)
                                if _fav_pct >= 80:
                                    _bar_color = "linear-gradient(90deg,#b45309,#f59e0b)"
                                    _fav_color = "#f59e0b"
                                    _conf_text = "🔒 LOCK"
                                elif _fav_pct >= 60:
                                    _bar_color = "linear-gradient(90deg,#047857,#10b981)"
                                    _fav_color = "#10b981"
                                    _conf_text = "CONFIDENT"
                                elif _fav_pct >= 54:
                                    _bar_color = "linear-gradient(90deg,#92400e,#f59e0b)"
                                    _fav_color = "#d97706"
                                    _conf_text = "LEAN"
                                else:
                                    _bar_color = "linear-gradient(90deg,#7f1d1d,#ef4444)"
                                    _fav_color = "#ef4444"
                                    _conf_text = "TOSS-UP"

                                # Extra context line (record + pitcher for MLB)
                                _ctx_parts = []
                                if _fav_rec:
                                    _ctx_parts.append(_fav_rec)
                                if _fav_pitch:
                                    _ctx_parts.append(f"SP: {_fav_pitch}")
                                _ctx_line = "  ·  ".join(_ctx_parts)
                                _ctx_html = (
                                    f'<div style="font-size:0.58rem;color:#2d4a66;margin-top:6px;'
                                    f'letter-spacing:0.3px">{_ctx_line}</div>'
                                    if _ctx_line else ""
                                )
                                _meter_html = (
                                    '<div class="ml-meter-row">'
                                    '<div class="ml-meter-labels">'
                                    + f'<span class="ml-meter-fav" style="color:{_fav_color}">{_fav_name}</span>'
                                    + f'<span class="ml-meter-badge" style="color:{_fav_color};border-color:{_fav_color}33">{_conf_text} &nbsp;{_fav_pct:.0f}%</span>'
                                    + f'<span class="ml-meter-dog">{_dog_name}</span>'
                                    + '</div>'
                                    + '<div class="ml-meter-track">'
                                    + f'<div class="ml-meter-fill" style="width:{_fav_pct:.1f}%;background:{_bar_color}"></div>'
                                    + '</div>'
                                    + _ctx_html
                                    + '</div>'
                                )

                                logo_img = lambda url, nm: (
                                    f'<img src="{url}" onerror="this.style.display=\'none\'" />'
                                    if url else f'<div style="width:36px;height:36px;background:#1e2837;border-radius:50%;"></div>'
                                )

                                # Per-book chips — build as inline badge rows on the card
                                def _book_chips(row, side):
                                    """Return inline book-odds badge HTML for one team side."""
                                    chips = ""
                                    for bk in book_cols:
                                        v = row.get(bk)
                                        if v is None or (hasattr(v, '__float__') and pd.isna(v)):
                                            continue
                                        odds_str = _fmt_odds(v)
                                        if odds_str == "—":
                                            continue
                                        is_best = (v == row.get("Best Odds"))
                                        cls = "ml-book-chip best-odds" if is_best else "ml-book-chip"
                                        chips += (
                                            f'<div class="{cls}">'
                                            f'<span class="bk-name">{bk}</span>'
                                            f'<span class="bk-odds">{odds_str}</span>'
                                            f'</div>'
                                        )
                                    if not chips:
                                        return ""
                                    return f'<div class="ml-books-row">{chips}</div>'

                                away_book_html = _book_chips(away_r, "away")
                                home_book_html = _book_chips(home_r, "home")

                                # ── Starting pitcher line (MLB only) ───────
                                def _pitcher_line(row):
                                    if sport_key != "MLB":
                                        return ""
                                    name = row.get("Pitcher") or ""
                                    hand = row.get("Pitcher Hand") or ""
                                    w    = row.get("Pitcher W")
                                    l    = row.get("Pitcher L")
                                    if not name:
                                        return '<div class="ml-pitcher">SP: TBD</div>'
                                    short = name.split()[-1] if name else ""
                                    hand_badge = (
                                        f'<span class="ml-pitcher-hand ml-hand-{"L" if hand=="L" else "R"}">{hand}HP</span>'
                                        if hand else ""
                                    )
                                    record = f" &nbsp;{w}-{l}" if w is not None and l is not None else ""
                                    return f'<div class="ml-pitcher">{short}{record} &nbsp;{hand_badge}</div>'

                                away_pitcher_html = _pitcher_line(away_r)
                                home_pitcher_html = _pitcher_line(home_r)

                                _card_html = (
                                    '<div class="ml-game-card">'
                                    '<div class="ml-team away">'
                                    + logo_img(away_logo, away_name)
                                    + '<div>'
                                    + f'<div class="ml-team-name">{away_name}</div>'
                                    + f'<div class="ml-team-odds {away_odds_cls}">{away_odds}</div>'
                                    + f'<div class="ml-pct">{away_pct_str}</div>'
                                    + away_pitcher_html
                                    + away_book_html
                                    + '</div></div>'
                                    + '<div class="ml-center">'
                                    + f'<div class="ml-time">{game_time}</div>'
                                    + '<div class="ml-vs">VS</div>'
                                    + f'<div class="ml-total">{total_str}</div>'
                                    + '</div>'
                                    + '<div class="ml-team">'
                                    + logo_img(home_logo, home_name)
                                    + '<div>'
                                    + f'<div class="ml-team-name">{home_name} <span style="font-size:0.6rem;color:#1e2837;font-weight:500">HOME</span></div>'
                                    + f'<div class="ml-team-odds {home_odds_cls}">{home_odds}</div>'
                                    + f'<div class="ml-pct">{home_pct_str}</div>'
                                    + home_pitcher_html
                                    + home_book_html
                                    + '</div></div>'
                                    + _meter_html
                                    + '</div>'
                                )
                                st.markdown(_card_html, unsafe_allow_html=True)

                        for sp in ["NBA", "MLB", "WNBA"]:
                            sub = df_ml[df_ml["Sport"] == sp].copy()
                            if sub.empty: continue
                            _ml_game_cards(sub, sp)
                            st.markdown('<div style="margin-bottom:8px"></div>', unsafe_allow_html=True)

            except Exception as e:
                import traceback
                st.error(f"Error: {e}\n{traceback.format_exc()}")
    else:
        _empty()
