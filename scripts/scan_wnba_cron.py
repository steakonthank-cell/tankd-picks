"""
Cron entry point for the WNBA scanner — WNBA had silently stopped getting
scanned (last real scan was 2026-06-29) because the cron was switched from
scan_and_send.py (which scanned MLB+NBA+WNBA) to smart_picks.py (MLB only)
without anything picking up WNBA/NBA again. This restores just the WNBA
side without re-triggering smart_picks.py's MLB scan/Discord send.

`builtins.input` is monkeypatched the same way smart_picks.py does it
(smart_picks.py:7) — src.sports.wnba.scanner.scan_wnba() ends with an
interactive `input("Press Enter to return to menu...")` meant for its CLI
menu, which raises EOFError with no stdin attached (cron). The scan+save
already completes before that call, so the patch just silences the
harmless trailing prompt.
"""
import sys
import os
import builtins

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")
builtins.input = lambda *a: ""

from src.sports.wnba.scanner import scan_wnba

if __name__ == "__main__":
    scan_wnba()
