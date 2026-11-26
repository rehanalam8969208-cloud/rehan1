import os
import re
import sys
import json
import time
import socket
import curses
import subprocess
import threading
from updater import check_and_update

BASE_NOTES_DIR = "/storage/emulated/0/Mirror Note"
MUSIC_TXT_PATH = os.path.join(BASE_NOTES_DIR, "music.txt")
HISTORY_TXT_PATH = os.path.join(BASE_NOTES_DIR, "history.txt")
TMP_BASE = os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")
MPV_SOCKET = os.path.join(TMP_BASE, "mpv_fast_ipc.sock")

STOP_EVENT = threading.Event()
ACTIVE_PROCS = set()
PROC_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()

SEEN_IDS = set()
SEEN_TITLES = set()
SEEN_KEYS = set()
SESSION_TRACKS = []


def ensure_history_file():
    try:
        os.makedirs(BASE_NOTES_DIR, exist_ok=True)
        if not os.path.exists(HISTORY_TXT_PATH):
            with open(HISTORY_TXT_PATH, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:
        pass


def record_to_history(song_title):
    clean_entry = (song_title or "").strip()
    if not clean_entry:
        return
    with HISTORY_LOCK:
        try:
            ensure_history_file()
            existing = []
            if os.path.exists(HISTORY_TXT_PATH):
                with open(HISTORY_TXT_PATH, "r", encoding="utf-8") as f:
                    existing = [line.strip() for line in f if line.strip()]
            filtered = [line for line in existing if line.lower() != clean_entry.lower()]
            updated = [clean_entry] + filtered[:499]
            with open(HISTORY_TXT_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(updated) + "\n")
        except Exception:
            pass


def normalize_title(title):
    cleaned = re.sub(r'\[[^\]]*\]|\([^\)]*\)', ' ', (title or '').lower())
    cleaned = re.sub(
        r'\b(official|video|audio|lyrics|lyric|hd|4k|hq|song|songs|music|remix|slowed|reverb|status|whatsapp|full)\b',
        ' ',
        cleaned
    )
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', cleaned)
    return " ".join([t for t in cleaned.split() if len(t) > 1])


def is_already_played(title, video_id=None):
    if video_id and video_id in SEEN_IDS:
        return True
    norm = normalize_title(title)
    if norm and norm in SEEN_TITLES:
        return True
    words = norm.split()
    if len(words) >= 2 and " ".join(words[:2]) in SEEN_KEYS:
        return True
    return False


def mark_played(title, video_id=None, seed_query=None):
    if video_id:
        SEEN_IDS.add(video_id)
    for raw in [title, seed_query]:
        if not raw:
            continue
        norm = normalize_title(raw)
        if norm:
            SEEN_TITLES.add(norm)
            words = norm.split()
            if len(words) >= 2:
                SEEN_KEYS.add(" ".join(words[:2]))


def add_session_track(query_or_url, title, vid_id=None):
    if not query_or_url:
        return
    for item in SESSION_TRACKS:
        if item["query"] == query_or_url or (vid_id and item.get("id") == vid_id):
            return
    SESSION_TRACKS.append({"query": query_or_url, "title": title or query_or_url, "id": vid_id})


def kill_all_child_procs():
    with PROC_LOCK:
        for p in list(ACTIVE_PROCS):
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        ACTIVE_PROCS.clear()


def send_mpv_cmd(command_list):
    if not os.path.exists(MPV_SOCKET):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.12)
        s.connect(MPV_SOCKET)
        payload = json.dumps({"command": command_list}) + "\n"
        s.sendall(payload.encode("utf-8"))
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        return resp
    except Exception:
        return None


def get_mpv_prop(prop_name, default=None):
    resp = send_mpv_cmd(["get_property", prop_name])
    if not resp:
        return default
    for line in resp.splitlines():
        try:
            data = json.loads(line)
            if data.get("error") == "success":
                return data.get("data", default)
        except Exception:
            pass
    return default


def format_sec(sec):
    if sec is None or sec < 0:
        return "00:00"
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def fast_get_stream_url(query):
    """Fast direct audio URL lookup (-g) without heavy JSON overhead."""
    if STOP_EVENT.is_set():
        return None
    proc = None
    try:
        proc = subprocess.Popen(
            [
                "yt-dlp", "--no-warnings", "--no-playlist",
                "-f", "bestaudio[ext=m4a]/bestaudio/best",
                "-g", query
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        with PROC_LOCK:
            ACTIVE_PROCS.add(proc)
        out, _ = proc.communicate(timeout=12)
        if STOP_EVENT.is_set():
            return None
        lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip().startswith("http")]
        return lines[0] if lines else None
    except Exception:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        return None
    finally:
        if proc is not None:
            with PROC_LOCK:
                ACTIVE_PROCS.discard(proc)


def get_youtube_style_next_tracks(anchor_title, seed_query, count=10):
    """Single fast flat search for non-repeating next songs."""
    clean_anchor = normalize_title(anchor_title)
    words = clean_anchor.split()
    artist_or_lead = " ".join(words[-2:]) if len(words) >= 2 else clean_anchor
    search_q = f"ytsearch{count}:{artist_or_lead or seed_query} song"

    results = []
    proc = None
    try:
        proc = subprocess.Popen(
            ["yt-dlp", "--no-warnings", "--flat-playlist", "-j", search_q],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        with PROC_LOCK:
            ACTIVE_PROCS.add(proc)
        out, _ = proc.communicate(timeout=12)
        if STOP_EVENT.is_set():
            return results

        for line in (out or "").splitlines():
            if not line.strip():
                continue
            try:
                info = json.loads(line)
            except Exception:
                continue
            title = (info.get("title") or "").strip()
            vid_id = (info.get("id") or "").strip()
            url = info.get("url") or info.get("webpage_url")
            if not title or not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"
            if is_already_played(title, vid_id):
                continue
            norm = normalize_title(title)
            if not norm or any(normalize_title(t) == norm for _, t, _ in results):
                continue
            results.append((url, title, vid_id))
            if len(results) >= count:
                break
    except Exception:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
    finally:
        if proc is not None:
            with PROC_LOCK:
                ACTIVE_PROCS.discard(proc)

    return results


class FastStreamPrefetcher:
    """Resolves next track's direct audio stream URL in background for quick NEXT switching."""
    def __init__(self, target_query, title):
        self.target_query = target_query
        self.title = title
        self.stream_url = None
        self.done_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            if not STOP_EVENT.is_set():
                self.stream_url = fast_get_stream_url(self.target_query)
        finally:
            self.done_event.set()

    def get_ready_or_fallback(self):
        # Sirf 0.4s max wait taaki NEXT dabane par delay na ho; na mile toh seedha query/url de
        self.done_event.wait(timeout=0.4)
        return self.stream_url or self.target_query


def draw_round_pill(stdscr, row_y, left_x, width, label, color_pair):
    h, w = stdscr.getmaxyx()
    if row_y >= h or left_x + width > w or left_x < 0 or width < 4:
        return None
    inner = width - 2
    pill_text = f"({label.center(inner)[:inner]})"
    try:
        stdscr.addstr(row_y, left_x, pill_text, color_pair | curses.A_BOLD)
    except curses.error:
        pass
    return (left_x, left_x + len(pill_text) - 1, max(0, row_y - 1), min(h - 1, row_y + 1))


def play_fast_ui(stdscr, playable_target, title, mode_label, queue_label, next_label):
    record_to_history(title)
    if os.path.exists(MPV_SOCKET):
        try:
            os.remove(MPV_SOCKET)
        except OSError:
            pass

    mpv_args = [
        "mpv", "--no-video", "--really-quiet", "--cache=yes", "--demuxer-max-bytes=15M"
    ]
    # Agar direct http stream URL pehle se mil chuka hai toh ytdl دوبارہ nahi chalega (aur fast start hoga)
    if playable_target.startswith("http") and "youtube.com/watch" not in playable_target and "youtu.be/" not in playable_target:
        mpv_args.append("--ytdl=no")
    else:
        mpv_args.append("--ytdl-format=bestaudio[ext=m4a]/bestaudio/best")

    mpv_args.extend([f"--input-ipc-server={MPV_SOCKET}", playable_target])

    mpv_proc = subprocess.Popen(
        mpv_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    with PROC_LOCK:
        ACTIVE_PROCS.add(mpv_proc)

    result_action = "NEXT"
    try:
        while mpv_proc.poll() is None and not STOP_EVENT.is_set():
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            paused = bool(get_mpv_prop("pause", False))
            pos = get_mpv_prop("time-pos", 0) or 0
            dur = get_mpv_prop("duration", 0) or 0

            stdscr.addstr(0, 1, f"[CYBER-FAST PLAYER] :: {mode_label}"[:max(1, w - 2)], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(1, 1, ("." * max(1, w - 2)), curses.color_pair(1))
            stdscr.addstr(3, 1, f"QUEUE   : {queue_label}"[:max(1, w - 2)], curses.color_pair(1))
            stdscr.addstr(4, 1, f"NEXT-UP : {next_label}"[:max(1, w - 2)], curses.color_pair(3))
            stdscr.addstr(6, 1, f"NOW PLAYING ({'PAUSED' if paused else 'ACTIVE'}):"[:max(1, w - 2)], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(7, 1, f"> {title}"[:max(1, w - 2)], curses.color_pair(4) | curses.A_BOLD)

            bar_y = 9
            bar_w = max(8, w - 18)
            ratio = min(1.0, max(0.0, (pos / dur))) if dur > 0 else 0
            filled = int(bar_w * ratio)
            bar_str = "=" * filled + "-" * (bar_w - filled)
            if bar_y < h:
                stdscr.addstr(bar_y, 1, f"{format_sec(pos)} [{bar_str}] {format_sec(dur)}"[:max(1, w - 2)], curses.color_pair(1))

            row1_y = max(bar_y + 3, h - 7)
            row2_y = row1_y + 3
            play_lbl = "PLAY" if paused else "PAUSE"

            btn_regions = []
            avail_w = max(24, w - 4)
            gap = 3

            r1_defs = [("prv", "PREV"), ("tog", play_lbl), ("nxt", "NEXT")]
            bw1 = max(8, (avail_w - gap * (len(r1_defs) - 1)) // len(r1_defs))
            cx = 2
            for act, lbl in r1_defs:
                box = draw_round_pill(stdscr, row1_y, cx, bw1, lbl, curses.color_pair(1))
                if box:
                    btn_regions.append((box, act))
                cx += bw1 + gap

            r2_defs = [("rew", "-10s"), ("fwd", "+10s"), ("stp", "STOP")]
            bw2 = max(8, (avail_w - gap * (len(r2_defs) - 1)) // len(r2_defs))
            cx = 2
            for act, lbl in r2_defs:
                cp = curses.color_pair(2) if act == "stp" else curses.color_pair(3)
                box = draw_round_pill(stdscr, row2_y, cx, bw2, lbl, cp)
                if box:
                    btn_regions.append((box, act))
                cx += bw2 + gap

            hint_y = row2_y + 2
            if hint_y < h:
                stdscr.addstr(hint_y, 2, "Keys: [b]=Prev  [Space]=Pause  [q]=Next  [x]=Stop"[:max(1, w - 3)], curses.color_pair(4))

            stdscr.refresh()

            key = stdscr.getch()
            action = None

            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    for (x1, x2, y1, y2), act in btn_regions:
                        if x1 <= mx <= x2 and y1 <= my <= y2:
                            action = act
                            break
                except Exception:
                    pass
            elif key in (ord(' '), ord('p'), ord('P')):
                action = "tog"
            elif key in (ord('b'), ord('B')):
                action = "prv"
            elif key in (ord('q'), ord('Q'), ord('n'), ord('N')):
                action = "nxt"
            elif key in (3, 27, ord('x'), ord('X')):
                action = "stp"
            elif key == curses.KEY_LEFT:
                action = "rew"
            elif key == curses.KEY_RIGHT:
                action = "fwd"

            if action == "tog":
                send_mpv_cmd(["cycle", "pause"])
            elif action == "rew":
                send_mpv_cmd(["seek", -10, "relative"])
            elif action == "fwd":
                send_mpv_cmd(["seek", 10, "relative"])
            elif action == "prv":
                result_action = "PREV"
                break
            elif action == "nxt":
                result_action = "NEXT"
                break
            elif action == "stp":
                STOP_EVENT.set()
                result_action = "STOP"
                break

        return result_action
    finally:
        with PROC_LOCK:
            ACTIVE_PROCS.discard(mpv_proc)
        # Turant mpv band karein taaki NEXT mein der na ho
        if mpv_proc.poll() is None:
            try:
                mpv_proc.kill()
            except Exception:
                pass
        if os.path.exists(MPV_SOCKET):
            try:
                os.remove(MPV_SOCKET)
            except OSError:
                pass


def curses_main(stdscr, history_mode=False):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(120)
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_WHITE, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)

    STOP_EVENT.clear()
    SEEN_IDS.clear()
    SEEN_TITLES.clear()
    SEEN_KEYS.clear()
    SESSION_TRACKS.clear()

    ensure_history_file()

    try:
        if history_mode:
            if not os.path.exists(HISTORY_TXT_PATH):
                return
            with open(HISTORY_TXT_PATH, "r", encoding="utf-8") as f:
                songs = [line.strip() for line in f if line.strip()]
            if not songs:
                return
            mode_title = "HISTORY PLAYBACK"
        else:
            if not os.path.exists(MUSIC_TXT_PATH):
                return
            with open(MUSIC_TXT_PATH, "r", encoding="utf-8") as f:
                songs = [line.strip() for line in f if line.strip()]
            if not songs:
                return
            mode_title = "YT AUTO-NEXT RADIO" if len(songs) == 1 else "FAST PLAYLIST"

        # Single song -> Fast start + Auto-Next Radio + PREV support
        if not history_mode and len(songs) == 1:
            seed_song = songs[0]
            first_query = seed_song if seed_song.startswith("http") else f"ytsearch1:{seed_song}"
            mark_played(seed_song, None, seed_song)
            add_session_track(first_query, seed_song)

            next_queue = get_youtube_style_next_tracks(seed_song, seed_song, count=10)
            prefetcher = None
            next_status = "Searching..."
            current_anchor = seed_song

            if next_queue:
                nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                mark_played(nxt_title, nxt_id)
                add_session_track(nxt_url, nxt_title, nxt_id)
                current_anchor = nxt_title
                next_status = nxt_title[:35]
                prefetcher = FastStreamPrefetcher(nxt_url, nxt_title)
                prefetcher.start()

            session_idx = 0
            res = play_fast_ui(stdscr, first_query, seed_song, mode_title, "TRACK [01 / AUTO]", next_status)
            if res == "STOP":
                return

            while res == "PREV" and not STOP_EVENT.is_set():
                session_idx = max(0, session_idx - 1)
                prev_obj = SESSION_TRACKS[session_idx]
                res = play_fast_ui(stdscr, prev_obj["query"], prev_obj["title"], mode_title, f"PREV #{session_idx + 1:02d}", next_status)
                if res == "STOP":
                    return

            auto_num = 2
            while not STOP_EVENT.is_set():
                if len(next_queue) < 3:
                    next_queue.extend(get_youtube_style_next_tracks(current_anchor, seed_song, count=10))

                if prefetcher is None:
                    if not next_queue:
                        time.sleep(0.3)
                        continue
                    cur_url, cur_title, cur_id = next_queue.pop(0)
                    mark_played(cur_title, cur_id)
                    add_session_track(cur_url, cur_title, cur_id)
                    cur_target = cur_url
                else:
                    cur_title = prefetcher.title
                    cur_target = prefetcher.get_ready_or_fallback()

                current_anchor = cur_title

                # Agle gaane ka stream link turant background mein nikalna shuru karein
                next_prefetcher = None
                next_status = "Queueing..."
                if next_queue:
                    nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                    mark_played(nxt_title, nxt_id)
                    add_session_track(nxt_url, nxt_title, nxt_id)
                    next_status = nxt_title[:35]
                    next_prefetcher = FastStreamPrefetcher(nxt_url, nxt_title)
                    next_prefetcher.start()

                res = play_fast_ui(stdscr, cur_target, cur_title, mode_title, f"AUTO-NEXT #{auto_num:02d}", next_status)
                auto_num += 1
                if res == "STOP":
                    return

                session_idx = len(SESSION_TRACKS) - 1
                while res == "PREV" and not STOP_EVENT.is_set():
                    session_idx = max(0, session_idx - 1)
                    prev_obj = SESSION_TRACKS[session_idx]
                    res = play_fast_ui(stdscr, prev_obj["query"], prev_obj["title"], mode_title, f"PREV #{session_idx + 1:02d}", next_status)
                    if res == "STOP":
                        return

                prefetcher = next_prefetcher

        # Multiple songs or History list -> Fast start + Pre-fetch + PREV support
        else:
            total = len(songs)
            items = [
                {"query": s if s.startswith("http") else f"ytsearch1:{s}", "title": s}
                for s in songs
            ]

            idx = 0
            prefetcher = None
            if total > 1:
                prefetcher = FastStreamPrefetcher(items[1]["query"], items[1]["title"])
                prefetcher.start()

            while 0 <= idx < total and not STOP_EVENT.is_set():
                cur_item = items[idx]
                if prefetcher is not None and prefetcher.title == cur_item["title"]:
                    cur_target = prefetcher.get_ready_or_fallback()
                else:
                    cur_target = cur_item["query"]

                next_preview = items[idx + 1]["title"][:35] if idx + 1 < total else "End of Queue"
                next_prefetcher = None
                if idx + 1 < total:
                    nxt_item = items[idx + 1]
                    next_prefetcher = FastStreamPrefetcher(nxt_item["query"], nxt_item["title"])
                    next_prefetcher.start()

                res = play_fast_ui(stdscr, cur_target, cur_item["title"], mode_title, f"TRACK [{idx+1:02d}/{total:02d}]", next_preview)
                if res == "STOP":
                    return
                if res == "PREV":
                    idx = max(0, idx - 1)
                    prefetcher = None
                    continue

                idx += 1
                prefetcher = next_prefetcher

    finally:
        STOP_EVENT.set()
        kill_all_child_procs()


if __name__ == "__main__":
    check_and_update(force=False, silent=True)
    is_history = "--history" in sys.argv
    try:
        curses.wrapper(curses_main, is_history)
    except KeyboardInterrupt:
        STOP_EVENT.set()
        kill_all_child_procs()
