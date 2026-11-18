"""Odds Roller"""

import heapq
import math
import random
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


SCRIPT_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
PRESETS = [(1, 2), (1, 6), (1, 10), (1, 100), (1, 1000), (1, 4096), (1, 10000), (1, 137000)]
AUTO_BATCH = 100_000  
NEAR_BAND = 0.10      # a miss counts as "close" if it lands within 10% of the range above the hit numbers
NEAR_KEEP = 5         # how many closest misses "Roll until hit" shows
MAX_VIEW = 3000       

# colors
BG, PANEL, BORDER = "#1b1d22", "#262931", "#3a3e4a"
FG, MUTED, LOG_BG = "#e8e8ea", "#80859a", "#121317"
GREEN = "#3ddc84"
YELLOW, ORANGE = (255, 230, 70), (255, 120, 20)


def near_band(n):
    return max(1, math.ceil(n * NEAR_BAND))


def near_color(distance, band):
    """Yellow when 1 away from the hit, fading to orange at the edge of the 'close' band."""
    t = 0.0 if band <= 1 else min(1.0, math.log(distance) / math.log(band))
    r, g, b = (round(a + (c - a) * t) for a, c in zip(YELLOW, ORANGE))
    return f"#{r:02x}{g:02x}{b:02x}"


class OddsRoller:
    def __init__(self, root):
        self.root = root
        root.title("Odds Roller")
        root.geometry("780x620")
        root.minsize(640, 520)
        root.configure(bg=BG)
        self.setup_style()

        self.rolls = 0           
        self.odds = None          
        self.band = 1             
        self.near = []            
        self.history = []         
        self.log_lines = []       
        self.auto_running = False

        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)

        # --- odds input ---
        row = ttk.Frame(main)
        row.pack(fill="x")
        ttk.Label(row, text="Odds:").pack(side="left")
        self.x_var = tk.StringVar(value="1")
        self.n_var = tk.StringVar(value="137000")
        ttk.Entry(row, textvariable=self.x_var, width=6, justify="center").pack(side="left", padx=4)
        ttk.Label(row, text="in").pack(side="left")
        ttk.Entry(row, textvariable=self.n_var, width=12, justify="center").pack(side="left", padx=4)
        self.pct_label = ttk.Label(row, foreground=MUTED)
        self.pct_label.pack(side="left", padx=8)
        self.x_var.trace_add("write", lambda *_: self.update_pct())
        self.n_var.trace_add("write", lambda *_: self.update_pct())

        presets = ttk.Frame(main)
        presets.pack(fill="x", pady=(8, 12))
        ttk.Label(presets, text="Presets:").pack(side="left", padx=(0, 4))
        for x, n in PRESETS:
            ttk.Button(presets, text=f"{x}/{n:,}",
                       command=lambda x=x, n=n: self.set_odds(x, n)).pack(side="left", padx=1)

        # --- buttons ---
        btns = ttk.Frame(main)
        btns.pack(fill="x")
        self.btn_once = ttk.Button(btns, text="Roll once  [Enter]", command=self.roll_once)
        self.btn_auto = ttk.Button(btns, text="Roll until hit", command=self.roll_until_hit)
        self.btn_stop = ttk.Button(btns, text="Stop", command=self.stop, state="disabled")
        self.btn_reset = ttk.Button(btns, text="Reset count", command=self.reset)
        for b in (self.btn_once, self.btn_auto, self.btn_stop, self.btn_reset):
            b.pack(side="left", padx=2)
        root.bind("<Return>", self.roll_once)

        # --- status ---
        self.count_label = ttk.Label(main, font=("Segoe UI", 18, "bold"))
        self.count_label.pack(anchor="w", pady=(14, 0))
        self.result = ttk.Label(main, font=("Segoe UI", 12), wraplength=740, justify="left")
        self.result.pack(anchor="w")
        self.stats = ttk.Label(main, foreground=MUTED)
        self.stats.pack(anchor="w", pady=(2, 10))

        # --- log view ---
        head = ttk.Frame(main)
        head.pack(fill="x")
        ttk.Label(head, text="Log").pack(side="left")
        ttk.Button(head, text="Create log file", command=self.create_log_file).pack(side="left", padx=(10, 2))
        ttk.Button(head, text="Clear log", command=self.clear_log).pack(side="left", padx=2)
        for text, color in (("miss", MUTED), ("close", "#ff7814"), ("very close", "#ffe646"), ("HIT", GREEN)):
            tk.Label(head, text=f"■ {text}", fg=color, bg=BG, font=("Segoe UI", 9, "bold")).pack(side="right", padx=4)

        log_frame = ttk.Frame(main)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.log_box = tk.Listbox(log_frame, font=("Consolas", 10), bg=LOG_BG, fg=FG,
                                  selectbackground=BORDER, selectforeground=FG,
                                  highlightthickness=0, borderwidth=0, activestyle="none")
        scroll = ttk.Scrollbar(log_frame, command=self.log_box.yview)
        self.log_box.config(yscrollcommand=scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.update_pct()
        self.update_count()

    def setup_style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                    bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, troughcolor=BG)
        s.configure("TButton", background=PANEL, padding=(10, 5))
        s.map("TButton", background=[("disabled", BG), ("active", BORDER)],
              foreground=[("disabled", "#555a66")])
        s.configure("TEntry", foreground=FG, insertcolor=FG)
        s.configure("Vertical.TScrollbar", background=PANEL, arrowcolor=FG)

    # ---------- odds ----------
    def parse_odds(self):
        try:
            x = int(self.x_var.get().replace(",", ""))
            n = int(self.n_var.get().replace(",", ""))
        except ValueError:
            return None
        if x < 1 or n < 1 or x > n:
            return None
        return x, n

    def update_pct(self):
        o = self.parse_odds()
        self.pct_label.config(text=f"= {o[0] / o[1] * 100:.4g}% per roll" if o else "invalid odds")

    def set_odds(self, x, n):
        self.x_var.set(str(x))
        self.n_var.set(str(n))

    def ready(self):

        o = self.parse_odds()
        if not o:
            messagebox.showerror("Odds Roller", "Enter odds like 1 in 100\n(whole numbers, first <= second).")
            return False
        if o != self.odds:
            self.odds = o
            self.band = near_band(o[1])
            self.rolls = 0
            self.near = []
        return True

    def closest(self):

        if not self.near:
            return None
        negd, no, val = max(self.near, key=lambda t: (t[0], -t[1]))
        return -negd, no, val

 
    def roll_once(self, _event=None):
        if self.auto_running or not self.ready():
            return
        x, n = self.odds
        self.rolls += 1
        value = random.randint(1, n)
        if value <= x:
            self.on_hit(value, auto=False)
            return
        d = value - x
        if d <= self.band:
            color, tag, word = near_color(d, self.band), f"close ({d:,} away)", "close!"
        else:
            color, tag, word = MUTED, "miss", "miss"
        self.result.config(text=f"Roll #{self.rolls:,}: rolled {value:,} - {word}", foreground=color)
        self.add_log([(f"{self.prefix()}roll #{self.rolls:<8,} -> {value:<8,} {tag}", color)])
        self.update_count()

    def roll_until_hit(self):
        if self.auto_running or not self.ready():
            return
        self.set_busy(True)
        self.auto_step()

    def auto_step(self):
        if not self.auto_running:
            return
        x, n = self.odds
        near = self.near
        cutoff = -near[0][0] if len(near) >= NEAR_KEEP else self.band
        rolls = self.rolls
        randint = random.randint
        for _ in range(AUTO_BATCH):
            rolls += 1
            value = randint(1, n)
            if value <= x:
                self.rolls = rolls
                self.set_busy(False)
                self.on_hit(value, auto=True)
                return
            d = value - x
            if d <= cutoff:
                if len(near) < NEAR_KEEP:
                    heapq.heappush(near, (-d, rolls, value))
                elif d < cutoff:
                    heapq.heapreplace(near, (-d, rolls, value))
                if len(near) >= NEAR_KEEP:
                    cutoff = -near[0][0]
        self.rolls = rolls
        self.show_progress("Rolling...")
        self.update_count()
        self.root.after(1, self.auto_step)

    def show_progress(self, text):
        c = self.closest()
        if c:
            d, no, val = c
            text += f"  closest miss so far: rolled {val:,} ({d:,} away) on roll #{no:,}"
            self.result.config(text=text, foreground=near_color(d, self.band))
        else:
            self.result.config(text=text, foreground=MUTED)

    def stop(self):
        if self.auto_running:
            self.set_busy(False)
            self.show_progress(f"Stopped at {self.rolls:,} rolls (no hit yet).")
            self.update_count()

    def reset(self):
        self.stop()
        self.rolls = 0
        self.near = []
        self.result.config(text="Count reset", foreground=MUTED)
        self.update_count()

    def set_busy(self, busy):
        self.auto_running = busy
        state = "disabled" if busy else "normal"
        self.btn_once.config(state=state)
        self.btn_auto.config(state=state)
        self.btn_stop.config(state="normal" if busy else "disabled")

    def on_hit(self, value, auto):
        x, n = self.odds
        taken = self.rolls
        closest = self.closest()
        near = sorted(self.near, key=lambda t: t[1])  # in the order they happened
        self.history.append((x, n, taken))
        self.rolls = 0
        self.near = []

        s = "s" if taken != 1 else ""
        longer = (1 - x / n) ** (taken - 1) * 100  # chance of needing this many rolls or more
        text = (f"HIT! Rolled {value:,} - it took {taken:,} roll{s}.  "
                f"({longer:.3g}% of people need this many or more)")
        if auto and closest:
            d, no, val = closest
            text += f"\nClosest miss: rolled {val:,} ({d:,} away) on roll #{no:,}"
        self.result.config(text=text, foreground=GREEN)
        self.update_count()

        prefix = self.prefix()
        hit_line = f"roll #{taken:<8,} -> {value:<8,} HIT after {taken:,} roll{s}"
        if auto:
            pad = " " * len(prefix)
            header = f"{prefix}roll until hit: {taken:,} roll{s}"
            if near:
                header += f", {len(near)} closest miss{'es' if len(near) != 1 else ''}:"
            entries = [(header, FG)]
            for negd, no, val in near:
                entries.append((f"{pad}roll #{no:<8,} -> {val:<8,} close ({-negd:,} away)",
                                near_color(-negd, self.band)))
            entries.append((pad + hit_line, GREEN))
        else:
            entries = [(prefix + hit_line, GREEN)]
        self.add_log(entries)

    # ---------- display ----------
    def prefix(self):
        x, n = self.odds
        return f"{datetime.now():%Y-%m-%d %H:%M:%S} | {x} in {n:,} | "

    def update_count(self):
        self.count_label.config(text=f"Rolls since last hit: {self.rolls:,}")
        o = self.odds or self.parse_odds()
        if not o:
            self.stats.config(text="")
            return
        x, n = o
        same = [r for a, b, r in self.history if (a, b) == (x, n)]
        expected = n / x
        if same:
            avg = sum(same) / len(same)
            self.stats.config(text=f"This session at {x} in {n:,}: {len(same)} hit(s), "
                                   f"avg {avg:,.1f} rolls, best {min(same):,}, worst {max(same):,} "
                                   f"(expected avg {expected:,.1f})")
        else:
            self.stats.config(text=f"Expected average: {expected:,.1f} rolls per hit")

    def add_log(self, entries):
        for text, color in entries:
            self.log_lines.append(text)
            self.log_box.insert("end", text)
            self.log_box.itemconfig(self.log_box.size() - 1, foreground=color)
        extra = self.log_box.size() - MAX_VIEW  
        if extra > 0:
            self.log_box.delete(0, extra - 1)
        self.log_box.see("end")

    # ---------- log buttons ----------
    def create_log_file(self):
        if not self.log_lines:
            messagebox.showinfo("Odds Roller", "The log is empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Create log file", initialdir=SCRIPT_DIR,
            initialfile=f"roll_log_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt",
            defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text("".join(line + "\n" for line in self.log_lines), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Odds Roller", f"Could not write log file:\n{e}")
            return
        messagebox.showinfo("Odds Roller", f"Log saved ({len(self.log_lines):,} lines):\n{path}")

    def clear_log(self):
        if not self.log_lines:
            return
        if messagebox.askyesno("Odds Roller", "Clear the log?"):
            self.log_lines.clear()
            self.log_box.delete(0, "end")


if __name__ == "__main__":
    root = tk.Tk()
    OddsRoller(root)
    root.mainloop()
