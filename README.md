# Jev Plays 2048

A small macOS helper that plays the **2048 Game** Mac app for you. Press a hotkey and it reads the live board straight out of the app, decides the best move, and presses the arrow key. Press the hotkey again to stop.

Moves are chosen in two layers:

1. **An expectimax lookahead search** (local, fast, free). It simulates several moves ahead, including every random tile that could spawn, and ranks the legal moves.
2. **Jev**, [TypeSafe](https://docs.typesafe.ai)'s System One model. It's only consulted when the search finds two or more moves too close to call. Jev picks between them based on board shape and strategy (keeping the biggest tile anchored in the bottom-left corner in a "snake" pattern).

The helper never takes over your keyboard. It only sends keys while 2048 Game is the focused app, and pauses as soon as you switch to something else.

---

## Contents

- [Requirements](#requirements)
- [Setup](#setup)
- [Usage](#usage)
- [Decision modes](#decision-modes)
- [The status widget](#the-status-widget)
- [Headless simulator](#headless-simulator)
- [Running the tests](#running-the-tests)
- [Manual diagnostic scripts](#manual-diagnostic-scripts)
- [How it works](#how-it-works)
- [Tuning](#tuning)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)

---

## Requirements

| Requirement | Notes |
| --- | --- |
| macOS | It uses the macOS Accessibility, Quartz, and AppKit APIs, so it won't run on Windows or Linux. The headless simulator and the tests are also tied to these packages through `requirements.txt`. |
| Python 3.9+ | Developed and tested on Python 3.13. Check your version with `python3 --version`. |
| **2048 Game** app | This is the free "2048 Game" app from the Mac App Store (bundle ID `com.kfir.mac2048`, tested with version 2.0.1). It must be installed in `/Applications` or anywhere else macOS can launch it from. Other 2048 apps and the browser version won't work. |
| A TypeSafe API key | You only need this for the `hybrid` (default) and `jev` modes. The `search` mode runs completely offline. Get a key from [TypeSafe](https://docs.typesafe.ai). |
| Accessibility permission | Needed to read the board, send arrow keys, and listen for the global hotkey. See [Grant Accessibility permission](#3-grant-accessibility-permission). |

Python dependencies (installed automatically by `run.sh`, listed in `requirements.txt`):

- `pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`: Python bindings for the macOS APIs.
- `python-dotenv`: loads your API key from `.env`.
- `requests`: HTTP calls to the TypeSafe API.

---

## Setup

### 1. Get the code

Put the project folder anywhere you like and open a terminal in it:

```bash
cd /path/to/2048-Jev
```

### 2. Add your TypeSafe API key

Create a file named `.env` in the project root (the same folder as `run.sh`) containing:

```bash
TYPESAFE_API_KEY=your-key-here
```

`.env` is already in `.gitignore`, so the key won't be committed. If you only plan to use `search` mode, you can skip this step.

You can also export the key in your shell instead (`export TYPESAFE_API_KEY=...`). A variable that's already set in the environment takes priority over `.env`.

### 3. Grant Accessibility permission

macOS doesn't let a program read another app's window or send it keystrokes without your permission. The permission is granted to **the app you launch the helper from**, such as Terminal, iTerm2, or Cursor/VS Code if you use its built-in terminal.

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Click **+** and add your terminal app, or turn on its switch if it's already listed.
3. **Fully quit and reopen the terminal app** (Cmd+Q, not just closing the window). The permission only takes effect for newly started processes.

If you skip this step, the helper exits right away with:

```text
Accessibility permission is required.
Open System Settings > Privacy & Security > Accessibility, enable it for your terminal app ...
```

On some macOS versions you may also need to enable the same terminal app under **Privacy & Security → Input Monitoring** for the global hotkey to work. See [Troubleshooting](#troubleshooting).

### 4. Install and launch

The easiest way is the included script:

```bash
./run.sh
```

The first time, `run.sh`:

1. Creates a virtual environment in `.venv/` if one doesn't exist.
2. Upgrades `pip` and installs everything in `requirements.txt` into it.
3. Starts the helper (`python -m jev2048.main`).

Later runs reuse `.venv/` and just re-check the dependencies, which takes a few seconds.

If you get `permission denied`, make the script executable first: `chmod +x run.sh`.

#### Manual setup (alternative)

If you'd rather set it up yourself:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m jev2048.main
```

Always run it as a module (`python -m jev2048.main`) from the project root, not as `python jev2048/main.py`. Otherwise the `jev2048` package imports won't resolve.

---

## Usage

Once the helper is running, the terminal shows:

```text
Jev 2048 helper is running. (mode: hybrid; set JEV_MODE=search|hybrid|jev to change)
Open 2048 Game, then press Ctrl+Option+J to start/stop Jev playing.
```

A **Jev** item with a pause icon also appears in the menu bar.

To play:

1. **Open 2048 Game** and start or continue a game.
2. **Click the 2048 Game window** so it's the focused app.
3. Press **Ctrl + Option + J**. A floating "Jev is playing" widget appears in the top-right corner of the screen, the menu bar icon changes to a play icon, and moves start about every 0.35 seconds.
4. Press **Ctrl + Option + J** again at any time to stop.

Behavior to expect:

- **Switching apps pauses play.** If you click away from 2048 Game, the widget shows `Paused – 2048 Game lost focus` and no keys are sent. Click back on the 2048 window and it continues on its own.
- **It stops itself at game over.** The widget shows `Game over after N moves` and then hides. Start a new game in the app and press the hotkey again to keep going.
- **2048 Game must be open.** If you press the hotkey while the app isn't running, the widget briefly shows `2048 Game isn't open`.
- **The hotkey is swallowed.** Ctrl+Option+J never reaches other apps while the helper is running.
- **You can move or resize the 2048 window.** Board reading recalibrates from the tile positions on every read.

To quit the helper completely, click the **Jev** menu bar item and choose **Quit Jev 2048** (or press `Ctrl+C` in the terminal).

---

## Decision modes

Set the mode with the `JEV_MODE` environment variable when launching:

```bash
JEV_MODE=search ./run.sh
JEV_MODE=hybrid ./run.sh   # the default
JEV_MODE=jev ./run.sh
```

| Mode | Uses the API? | What happens on each move |
| --- | --- | --- |
| `hybrid` (default) | Only for close calls | The search decides on its own when the answer is clear. Jev is asked only when the top moves are within 3% of each other in expected value and at least two of them are safe. If Jev's confidence is below 55%, the search's top move is played instead. |
| `search` | Never | Always plays the search's top move. Free, offline, and needs no API key. |
| `jev` | Every move with 2+ options | Sends every legal move to Jev, ranked by the search, and plays whatever Jev picks. Mainly useful for comparing against the other modes. It's the slowest and most expensive mode. |

In every mode:

- If only one move is legal, it's played immediately without searching or calling the API.
- A move is "safe" if, for every possible random spawn afterward (a 2 or a 4 in any empty cell), at least one legal move remains. In `hybrid` mode, if only one move is safe it's played without asking Jev.
- If the TypeSafe API is temporarily unreachable (network error, HTTP 429 or 529), the request is retried up to 3 times with exponential backoff (1s, 2s, 4s). If it still fails, the search's top move is played and the game keeps going.
- If the API rejects the request outright (missing or invalid key, HTTP 401, or any other 4xx/5xx), play stops and the widget shows `Jev error: ...`.

---

## The status widget

While playing, the floating widget's second line shows the latest move and where the decision came from:

| Widget text | Meaning |
| --- | --- |
| `Move 42 • left (78%)` | Jev chose `left` with 78% confidence. |
| `Move 42 • left (search)` | The search decided on its own (clear winner, or Jev wasn't confident enough). |
| `Move 42 • left (fallback)` | The API couldn't be reached after retries, so the search's top move was used. |
| `Move 42 • left` | `left` was the only legal move. |
| `Paused – 2048 Game lost focus` | Waiting for you to click back on the 2048 window. |
| `Game over after N moves` / `No legal moves after N moves` | The game ended. Play stops automatically. |
| `Jev error: ...` | A definitive API error, such as a bad key. Play stops. |

The widget ignores mouse clicks, so it never gets in the way of the game. It appears on every desktop Space.

---

## Headless simulator

`jev2048/simulate.py` plays full games of 2048 in memory, without the Mac app, so you can measure how well a mode performs and tune the settings with real numbers.

```bash
# 200 games in hybrid mode, Jev calls mocked (free, no network)
./.venv/bin/python -m jev2048.simulate --games 200 --mode hybrid --seed 0

# Pure search, no Jev at all
./.venv/bin/python -m jev2048.simulate --games 200 --mode search

# Real TypeSafe API calls (asks for confirmation first, uses your key and costs money)
./.venv/bin/python -m jev2048.simulate --games 30 --mode hybrid --real-jev
```

| Option | Default | Description |
| --- | --- | --- |
| `--games N` | `200` | Number of games to play. |
| `--mode` | `hybrid` | `search`, `hybrid`, or `jev`. |
| `--seed N` | `0` | Random seed for tile spawns. The same seed gives the same games, so you can compare settings fairly. |
| `--time-budget S` | `0.03` | Search time per move in seconds. Live play uses 0.15s. The lower default keeps hundreds of games reasonably fast, but it plays a bit weaker than live play. |
| `--real-jev` | off | Call the real TypeSafe API instead of the mock. Has no effect with `--mode search`. |

Without `--real-jev`, Jev is replaced by a mock that always agrees with the search's top candidate at 80% confidence. That exercises the escalation logic and timing, but it doesn't measure Jev's actual judgment.

Example report:

```text
=== 200 games, mode=hybrid ===
Win rate (reached 2048): ...
Largest tile reached, by frequency:
    2048: ...
    1024: ...
Average moves per game: ...
Time per move: p50=...ms p95=...ms
Jev calls per game: ...
Decisions by source:
  search: ...
  jev: ...
  trivial: ...
```

"Win rate" counts any game that reaches a 2048 tile. The simulation keeps playing past 2048 until no moves are left.

---

## Running the tests

The tests use Python's built-in `unittest`, so nothing extra needs to be installed. From the project root:

```bash
./.venv/bin/python -m unittest discover -s tests
```

Expected result:

```text
Ran 38 tests in 0.4s

OK
```

| File | What it covers |
| --- | --- |
| `tests/test_game.py` | Slide/merge rules, legal moves, game-over detection, tile spawning, largest-tile tracking. |
| `tests/test_search.py` | Board encoding, the bit-packed move tables matching `game.py`, the expectimax search, and spawn-survival checks. |
| `tests/test_choose_move.py` | Mode behavior, when Jev is or isn't consulted, the confidence threshold, and fallback on API failure. These use a fake API, so no key or network is needed. |

The tests don't need the 2048 app or Accessibility permission.

---

## Manual diagnostic scripts

Each module can be run on its own to check one piece in isolation. Run these from the project root with the virtual environment's Python:

| Command | What it does | Needs |
| --- | --- | --- |
| `./.venv/bin/python -m jev2048.board` | Prints the live board read from the app once per second (Ctrl+C to stop). Use this to confirm board reading works. | 2048 Game open, Accessibility permission |
| `./.venv/bin/python -m jev2048.input` | Prints whether Accessibility is granted and whether 2048 is running and focused, then sends one `left` press if it's focused. | Accessibility permission |
| `./.venv/bin/python -m jev2048.search` | Runs the search on a sample board and prints the ranked moves and how long it took. | Nothing |
| `./.venv/bin/python -m jev2048.jev` | Sends one sample board through `choose_move` and prints the decision. Depending on the mode and the board, this may call the live API. | API key for `hybrid`/`jev` |
| `./.venv/bin/python -m jev2048.ui` | Shows the floating widget for 4 seconds, then exits. | Nothing |

Tip for `jev2048.input`: the command runs instantly, so 2048 won't be focused unless you start it with a delay, for example `sleep 3 && ./.venv/bin/python -m jev2048.input`, and click the 2048 window during those 3 seconds.

---

## How it works

Each turn of the play loop (`jev2048/main.py`, `JevPlayer._play_loop`) does the following:

1. **Check focus.** If 2048 Game isn't the frontmost app, it waits 0.5 seconds and checks again.
2. **Read the board** (`board.py`). It walks the app's Accessibility tree, the same interface VoiceOver uses, to find each tile's number and screen position, and maps positions to a 4×4 grid. It reads repeatedly until two consecutive reads agree, so it doesn't catch a slide animation halfway through. It also looks for "Game over" text. Nothing is captured from screen pixels.
3. **List the legal moves** (`game.py`). Plain 2048 rules: slide, merge, and drop any move that doesn't change the board.
4. **Search** (`search.py`). A time-limited expectimax search (0.15 seconds per move by default):
   - The board is packed into one 64-bit integer, and the results for all 65,536 possible rows are precomputed at startup, so simulating a move costs only a few table lookups.
   - It alternates "player" turns (take the best move) and "chance" turns (average over every possible spawn: a 2 with 90% probability, a 4 with 10%).
   - It deepens one level at a time (iterative deepening) and keeps the deepest level that finished within the time limit.
   - Leaf positions are scored by a heuristic that rewards empty cells, available merges, rows and columns that increase or decrease steadily (monotonicity), neighboring tiles of similar size (smoothness), and keeping the largest tile in the bottom-left corner along a snake path.
   - For each move it also checks every possible next spawn to see whether the move is safe, and how many empty cells the best reply could leave in the worst case.
5. **Decide** (`jev.py`, `choose_move`). Depending on the mode, it plays the search's top move or asks Jev. A Jev request is a single TypeSafe `choice` question. It includes the current board, and for each candidate move: the resulting board, points gained, empty cells, its search rank and value relative to the best move, whether it's safe, and its worst-case empty cells. Requests go to `https://api.typesafe.ai/v1/systemone` with model `jev-latest`.
6. **Press the key** (`input.py`). It re-checks that 2048 is still focused, then posts the arrow key press.
7. **Update the widget** (`ui.py`) and wait 0.35 seconds for the game's animation to settle.

The global hotkey is a macOS event tap (`CGEventTapCreate`) that watches every key press and catches Ctrl+Option+J.

---

## Tuning

The main settings are constants at the top of each module. Edit them and restart the helper. Use the simulator with a fixed `--seed` to compare before and after.

| Setting | File | Default | Effect |
| --- | --- | --- | --- |
| `MOVE_INTERVAL` | `main.py` | `0.35` s | Pause between moves. Too low and reads can land mid-animation. |
| `PAUSED_POLL_INTERVAL` | `main.py` | `0.5` s | How often focus is re-checked while paused. |
| `HOTKEY_KEYCODE`, `HOTKEY_MODIFIERS` | `main.py` | `38` (J), Ctrl+Option | The toggle hotkey. Keycode 38 is the physical **J** key position on a US (ANSI) layout. |
| `TIME_BUDGET_S` | `search.py` | `0.15` s | Search time per move in live play. More time means deeper search and stronger play, but slower moves. |
| `PROB_CUTOFF` | `search.py` | `1e-4` | Spawn sequences less likely than this are scored with the heuristic instead of being searched deeper. |
| `Weights` | `search.py` | see file | Heuristic weights for empty cells, merges, monotonicity, smoothness, corner, and so on. |
| `MARGIN` | `jev.py` | `0.03` | In `hybrid` mode, how far ahead (relative to its value) the top move must be to skip asking Jev. Raise it to ask Jev more often. |
| `TOP_K` | `jev.py` | `3` | How many of the top safe moves are shown to Jev in `hybrid` mode. |
| `MIN_JEV_CONFIDENCE` | `jev.py` | `0.55` | In `hybrid` mode, Jev answers below this confidence are ignored in favor of the search. |
| `INSTRUCTIONS` | `jev.py` | see file | The strategy guidance sent to Jev with each question. |

The anchor corner (bottom-left, `ANCHOR = (3, 0)`) is defined in both `game.py` and `search.py`, and `search.py` also has a matching `SNAKE_RANK` table. If you change the anchor, update all three to match, along with the `anchor_corner` text in `jev.py`.

---

## Project layout

```text
2048-Jev/
├── README.md            This file
├── run.sh               One-step setup and launch script
├── requirements.txt     Python dependencies
├── .env                 Your TYPESAFE_API_KEY (you create this; git-ignored)
├── .gitignore
├── SKILL.md             Agent guidance for building with TypeSafe (not used at runtime)
├── jev2048/
│   ├── __init__.py
│   ├── main.py          Entry point: global hotkey, play loop, wiring
│   ├── board.py         Reads the live board from the 2048 Game app via Accessibility
│   ├── input.py         Sends arrow keys; focus and permission checks
│   ├── game.py          Pure 2048 rules (moves, merges, spawns, legality)
│   ├── search.py        Bit-packed expectimax search and heuristic
│   ├── jev.py           Move selection: modes, TypeSafe API client, fallback
│   ├── ui.py            Floating status widget and menu bar item
│   └── simulate.py      Headless simulator for measuring win rate
└── tests/
    ├── test_game.py
    ├── test_search.py
    └── test_choose_move.py
```

---

## Troubleshooting

**"Accessibility permission is required" even though I enabled it.**
Permission belongs to the app that launched Python. If you enabled Terminal but are running from Cursor's or VS Code's built-in terminal, enable that app instead, or as well. After changing the setting, fully quit the terminal app (Cmd+Q) and reopen it. If it still fails, remove the entry with **−**, add it again, and restart the terminal.

**"Could not create the global hotkey listener."**
The event tap was refused. Double-check Accessibility permission as above. On recent macOS versions, also enable your terminal app under **System Settings → Privacy & Security → Input Monitoring**, then restart the terminal.

**The hotkey does nothing.**
- Make sure the helper is still running in the terminal.
- The hotkey is exactly **Ctrl + Option + J**. Adding Cmd or Shift won't match.
- On non-US keyboard layouts, keycode 38 is the key in the physical position of **J** on a US keyboard, which may be labeled differently. Change `HOTKEY_KEYCODE` in `main.py` if needed.
- Check that no other app has claimed the same shortcut.

**The widget shows "Paused – 2048 Game lost focus" the whole time.**
Click inside the 2048 Game window. Keys are only sent while it's the frontmost app, and that's intentional.

**The widget shows "2048 Game isn't open".**
The helper looks for an app named "2048 Game" or with bundle ID `com.kfir.mac2048`. Install that specific app from the Mac App Store and open it before pressing the hotkey.

**Nothing happens after the widget appears, or moves seem wrong.**
Run `./.venv/bin/python -m jev2048.board` with the game open and compare the printed grid with what's on screen. If it says `No tiles found`, the game page may still be loading, so wait a moment. If the grid is shifted, try resizing the 2048 window back to its default size so the starting calibration matches. Calibration fixes itself once tiles appear in all four rows and columns.

**"Jev error: TYPESAFE_API_KEY is not set."**
Create `.env` in the project root (next to `run.sh`) with `TYPESAFE_API_KEY=...`, or run with `JEV_MODE=search` to play without the API.

**"Jev error: TypeSafe rejected the API key (401 Unauthorized)."**
The key is wrong, expired, or has extra characters. Check `.env` for stray quotes or spaces, and check that an older `TYPESAFE_API_KEY` exported in your shell isn't overriding it (`echo $TYPESAFE_API_KEY`).

**Lots of "(fallback)" moves.**
The API is being rate limited (HTTP 429), is overloaded (HTTP 529), or the network is unreachable. Play continues using the search alone. If you don't need Jev, use `JEV_MODE=search`.

**`ModuleNotFoundError: No module named 'jev2048'`.**
Run from the project root using `python -m jev2048.main`, not `python jev2048/main.py`.

**`ModuleNotFoundError: No module named 'AppKit'` / `'Quartz'` / `'dotenv'`.**
The dependencies aren't installed in the Python you're using. Run `./run.sh` once, or activate the venv (`source .venv/bin/activate`) and run `pip install -r requirements.txt`.

**Moves seem to skip or the board reads stale values.**
Increase `MOVE_INTERVAL` in `main.py` (try `0.5`). This is more likely on slower Macs, or if the game's animations are slower than usual.
