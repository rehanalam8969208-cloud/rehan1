import os
import re
import sys
import json
import glob
import time
import socket
import shutil
import curses
import subprocess
import threading
from updater import check_and_update

BASE_NOTES_DIR = "/storage/emulated/0/Mirror Note"
MUSIC_TXT_PATH = os.path.join(BASE_NOTES_DIR, "music.txt")
HISTORY_TXT_PATH = os.path.join(BASE_NOTES_DIR, "history.txt")
TMP_BASE = os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")
TEMP_CACHE_DIR = os.path.join(TMP_BASE, "mirror_note_audio_cache")
MPV_SOCKET = os.path.join(TMP_BASE, "mpv_touch_ipc.sock")

STOP_EVENT = threading.Event()
ACTIVE_DOWNLOAD_PROCS = set()
PROC_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()

SEEN_IDS = set()
SEEN_TITLES = set()
SEEN_KEYS = set()
SESSION_TRACKS = []  # List of dicts: {"url": ..., "title": ..., "id": ...}


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
    cleaned = re.sub(r'\b(official|video|audio|lyrics|lyric|hd|4k|hq|song|songs|music|remix|slowed|reverb|status|whatsapp|full)\b', ' ', cleaned)
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


def add_session_track(url, title, vid_id=None):
    if not url:
        return
    for item in SESSION_TRACKS:
        if item["url"] == url or (vid_id and item.get("id") == vid_id):
            return
    SESSION_TRACKS.append({"url": url, "title": title or url, "id": vid_id})


def ensure_temp_dir():
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)


def kill_active_downloads():
    with PROC_LOCK:
        for p in list(ACTIVE_DOWNLOAD_PROCS):
            try:
                p.terminate()
                p.kill()
            except Exception:
                pass
        ACTIVE_DOWNLOAD_PROCS.clear()


def cleanup_temp_files(specific_prefix=None):
    if not os.path.exists(TEMP_CACHE_DIR):
        return
    try:
        if specific_prefix:
            for p in glob.glob(os.path.join(TEMP_CACHE_DIR, f"{specific_prefix}*")):
                try:
                    os.remove(p)
                except OSError:
                    pass
        else:
            for entry in os.listdir(TEMP_CACHE_DIR):
                full_path = os.path.join(TEMP_CACHE_DIR, entry)
                try:
                    if os.path.isfile(full_path) or os.path.islink(full_path):
                        os.remove(full_path)
                    elif os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                except OSError:
                    pass
    except Exception:
        pass


def send_mpv_cmd(command_list):
    if not os.path.exists(MPV_SOCKET):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
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


def fetch_track_meta(query):
    try:
        raw = subprocess.check_output(
            ["yt-dlp", "--no-warnings", "--no-playlist", "-j", "-f", "bestaudio/best", query],
            stderr=subprocess.DEVNULL,
            timeout=25
        ).decode("utf-8", errors="ignore").strip()
        if not raw:
            return query, query, None
        data = json.loads(raw.splitlines()[0])
        return data.get("webpage_url") or query, data.get("title") or query, data.get("id")
    except Exception:
        return query, query, None


def download_temp_track(target_query, track_tag):
    if STOP_EVENT.is_set():
        return None
    ensure_temp_dir()
    cleanup_temp_files(track_tag)
    out_template = os.path.join(TEMP_CACHE_DIR, f"{track_tag}.%(ext)s")
    cmd = [
        "yt-dlp", "--no-warnings", "--no-playlist",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "-o", out_template, target_query
    ]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with PROC_LOCK:
            ACTIVE_DOWNLOAD_PROCS.add(proc)
        while proc.poll() is None:
            if STOP_EVENT.is_set():
                proc.terminate()
                cleanup_temp_files(track_tag)
                return None
            time.sleep(0.2)
        if proc.returncode != 0 or STOP_EVENT.is_set():
            cleanup_temp_files(track_tag)
            return None
        matches = glob.glob(os.path.join(TEMP_CACHE_DIR, f"{track_tag}.*"))
        valid = [f for f in matches if not f.endswith(".part") and not f.endswith(".ytdl")]
        return valid[0] if valid else None
    except Exception:
        cleanup_temp_files(track_tag)
        return None
    finally:
        if proc is not None:
            with PROC_LOCK:
                ACTIVE_DOWNLOAD_PROCS.discard(proc)


def get_youtube_style_next_tracks(anchor_title, seed_query, count=10):
    clean_anchor = normalize_title(anchor_title)
    words = clean_anchor.split()
    artist_or_lead = " ".join(words[-2:]) if len(words) >= 2 else clean_anchor
    queries = [
        f"ytsearch{count}:{artist_or_lead} hits",
        f"ytsearch{count}:{seed_query} playlist",
        f"ytsearch{count}:top {artist_or_lead} songs",
    ]
    results = []
    for q in queries:
        if STOP_EVENT.is_set():
            break
        try:
            raw = subprocess.check_output(
                ["yt-dlp", "--no-warnings", "--flat-playlist", "-j", q],
                stderr=subprocess.DEVNULL,
                timeout=25
            ).decode("utf-8", errors="ignore").strip()
            for line in raw.splitlines():
                if not line.strip():
                    continue
                info = json.loads(line)
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
                    return results
        except Exception:
            continue
    return results


class BackgroundPrefetcher:
    def __init__(self, target_query, track_tag, known_title=None, known_id=None):
        self.target_query = target_query
        self.track_tag = track_tag
        self.known_title = known_title
        self.known_id = known_id
        self.local_file = None
        self.resolved_title = known_title or target_query
        self.resolved_id = known_id
        self.done_event = threading.Event()
        self.thread = threading.Thread(target=self._worker, daemon=True)

    def start(self):
        self.thread.start()

    def _worker(self):
        try:
            if STOP_EVENT.is_set():
                return
            url, title, vid_id = fetch_track_meta(self.target_query)
            if not self.known_title:
                self.resolved_title = title
            if vid_id:
                self.resolved_id = vid_id
            self.local_file = download_temp_track(url, self.track_tag)
        finally:
            self.done_event.set()

    def wait_and_get(self):
        while not self.done_event.is_set():
            if STOP_EVENT.is_set():
                return None, self.resolved_title, self.resolved_id
            time.sleep(0.15)
        return self.local_file, self.resolved_title, self.resolved_id


def draw_button_box(stdscr, top_y, left_x, width, label, color_pair):
    """Draws a crisp, readable 3-line touch button block."""
    h, w = stdscr.getmaxyx()
    if top_y + 2 >= h or left_x + width >= w or left_x < 0:
        return None
    inner = max(1, width - 2)
    centered = label.center(inner)[:inner]
    try:
        stdscr.addstr(top_y, left_x, "+" + "-" * inner + "+", color_pair)
        stdscr.addstr(top_y + 1, left_x, "|" + centered + "|", color_pair | curses.A_BOLD)
        stdscr.addstr(top_y + 2, left_x, "+" + "-" * inner + "+", color_pair)
    except curses.error:
        pass
    return (left_x, left_x + width - 1, top_y, top_y + 2)


def play_with_touch_ui(stdscr, local_audio_path, track_tag, title, mode_label, queue_label, next_label):
    """Plays cached audio in mpv with clear, large touch buttons including PREV."""
    record_to_history(title)
    if os.path.exists(MPV_SOCKET):
        try:
            os.remove(MPV_SOCKET)
        except OSError:
            pass

    mpv_proc = subprocess.Popen(
        [
            "mpv", "--no-video", "--really-quiet",
            f"--input-ipc-server={MPV_SOCKET}",
            local_audio_path
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    for _ in range(20):
        if os.path.exists(MPV_SOCKET) or mpv_proc.poll() is not None:
            break
        time.sleep(0.05)

    try:
        while mpv_proc.poll() is None and not STOP_EVENT.is_set():
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            paused = bool(get_mpv_prop("pause", False))
            pos = get_mpv_prop("time-pos", 0) or 0
            dur = get_mpv_prop("duration", 0) or 0

            stdscr.addstr(0, 1, f"[CYBER-TOUCH PLAYER] :: {mode_label}"[:max(1, w - 2)], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(1, 1, ("-" * max(1, w - 2)), curses.color_pair(2))
            stdscr.addstr(3, 1, f"QUEUE   : {queue_label}"[:max(1, w - 2)], curses.color_pair(3))
            stdscr.addstr(4, 1, f"NEXT-UP : {next_label}"[:max(1, w - 2)], curses.color_pair(4))
            stdscr.addstr(6, 1, f"NOW PLAYING ({'PAUSED' if paused else 'PLAYING'}):"[:max(1, w - 2)], curses.color_pair(2) | curses.A_BOLD)
            stdscr.addstr(7, 1, f"> {title}"[:max(1, w - 2)], curses.color_pair(1) | curses.A_BOLD)

            # Progress Bar
            bar_y = max(9, min(h - 10, 10))
            bar_w = max(8, w - 18)
            ratio = min(1.0, max(0.0, (pos / dur))) if dur > 0 else 0
            filled = int(bar_w * ratio)
            bar_str = "#" * filled + "-" * (bar_w - filled)
            stdscr.addstr(bar_y, 1, f"{format_sec(pos)} [{bar_str}] {format_sec(dur)}"[:max(1, w - 2)], curses.color_pair(1))

            # Clear 2-Row Touch Control Panel near Bottom
            row1_y = max(bar_y + 2, h - 8)
            row2_y = row1_y + 3
            play_lbl = "PLAY" if paused else "PAUSE"

            btn_regions = []
            avail_w = max(24, w - 2)

            # Row 1: PREV | PAUSE/PLAY | NEXT
            r1_defs = [("prv", "PREV"), ("tog", play_lbl), ("nxt", "NEXT")]
            gap = 1
            bw1 = max(7, (avail_w - gap * (len(r1_defs) - 1)) // len(r1_defs))
            cx = 1
            for act, lbl in r1_defs:
                box = draw_button_box(stdscr, row1_y, cx, bw1, lbl, curses.color_pair(7))
                if box:
                    btn_regions.append((box, act))
                cx += bw1 + gap

            # Row 2: -10s | +10s | STOP
            r2_defs = [("rew", "-10s"), ("fwd", "+10s"), ("stp", "STOP")]
            bw2 = max(7, (avail_w - gap * (len(r2_defs) - 1)) // len(r2_defs))
            cx = 1
            for act, lbl in r2_defs:
                cp = curses.color_pair(5) if act == "stp" else curses.color_pair(7)
                box = draw_button_box(stdscr, row2_y, cx, bw2, lbl, cp)
                if box:
                    btn_regions.append((box, act))
                cx += bw2 + gap

            hint_y = min(h - 1, row2_y + 3)
            if hint_y < h:
                stdscr.addstr(hint_y, 1, "Tap buttons or keys: [b]=Prev [Space]=Pause [q]=Next [x]=Stop"[:max(1, w - 2)], curses.color_pair(3))

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
            elif key == curses.KEY_LEFT:
                action = "rew"
            elif key == curses.KEY_RIGHT:
                action = "fwd"
            elif key in (3, 27, ord('x'), ord('X')):
                action = "stp"

            if action == "tog":
                send_mpv_cmd(["cycle", "pause"])
            elif action == "rew":
                send_mpv_cmd(["seek", -10, "relative"])
            elif action == "fwd":
                send_mpv_cmd(["seek", 10, "relative"])
            elif action == "prv":
                send_mpv_cmd(["quit"])
                return "PREV"
            elif action == "nxt":
                send_mpv_cmd(["quit"])
                return "NEXT"
            elif action == "stp":
                STOP_EVENT.set()
                send_mpv_cmd(["quit"])
                return "STOP"

        return "NEXT"
    finally:
        if mpv_proc.poll() is None:
            mpv_proc.terminate()
            try:
                mpv_proc.wait(timeout=1)
            except Exception:
                mpv_proc.kill()
        if os.path.exists(MPV_SOCKET):
            try:
                os.remove(MPV_SOCKET)
            except OSError:
                pass
        cleanup_temp_files(track_tag)


def play_specific_session_track(stdscr, track_obj, track_counter, mode_title, queue_label, next_label):
    tag = f"track_{track_counter}"
    local_file = download_temp_track(track_obj["url"], tag)
    if not local_file:
        cleanup_temp_files(tag)
        return "NEXT"
    return play_with_touch_ui(stdscr, local_file, tag, track_obj["title"], mode_title, queue_label, next_label)


def curses_main(stdscr, history_mode=False):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(200)
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_GREEN)

    STOP_EVENT.clear()
    SEEN_IDS.clear()
    SEEN_TITLES.clear()
    SEEN_KEYS.clear()
    SESSION_TRACKS.clear()

    ensure_history_file()
    ensure_temp_dir()
    cleanup_temp_files()

    def show_loading(msg):
        stdscr.erase()
        _, w = stdscr.getmaxyx()
        stdscr.addstr(1, 1, "[CYBER-TOUCH PLAYER] INITIALIZING..."[:max(1, w - 2)], curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(3, 1, msg[:max(1, w - 2)], curses.color_pair(3))
        stdscr.refresh()

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
            mode_title = "YT AUTO-NEXT RADIO" if len(songs) == 1 else "ZERO-GAP PLAYLIST"

        track_counter = 1

        # Single song -> YouTube Auto-Next Radio with PREV support
        if not history_mode and len(songs) == 1:
            seed_song = songs[0]
            show_loading(f"Loading seed track: {seed_song}...")
            query = seed_song if seed_song.startswith("http") else f"ytsearch1:{seed_song}"
            resolved_url, actual_title, actual_id = fetch_track_meta(query)
            mark_played(actual_title, actual_id, seed_song)
            add_session_track(resolved_url, actual_title, actual_id)

            seed_tag = f"track_{track_counter}"
            track_counter += 1
            seed_file = download_temp_track(resolved_url, seed_tag)

            next_queue = get_youtube_style_next_tracks(actual_title, seed_song, count=10)
            prefetcher = None
            next_status = "Searching..."
            current_anchor = actual_title

            if next_queue:
                nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                mark_played(nxt_title, nxt_id)
                add_session_track(nxt_url, nxt_title, nxt_id)
                current_anchor = nxt_title
                next_status = nxt_title[:35]
                prefetcher = BackgroundPrefetcher(nxt_url, f"track_{track_counter}", known_title=nxt_title, known_id=nxt_id)
                track_counter += 1
                prefetcher.start()

            session_idx = 0
            if seed_file:
                res = play_with_touch_ui(stdscr, seed_file, seed_tag, actual_title, mode_title, "TRACK [01 / AUTO]", next_status)
                if res == "STOP":
                    return
                while res == "PREV" and not STOP_EVENT.is_set():
                    session_idx = max(0, session_idx - 1)
                    prev_obj = SESSION_TRACKS[session_idx]
                    res = play_specific_session_track(stdscr, prev_obj, track_counter, mode_title, f"PREV #{session_idx + 1:02d}", next_status)
                    track_counter += 1
                    if res == "STOP":
                        return

            auto_num = 2
            while not STOP_EVENT.is_set():
                if len(next_queue) < 3:
                    next_queue.extend(get_youtube_style_next_tracks(current_anchor, seed_song, count=10))

                if prefetcher is None:
                    if not next_queue:
                        time.sleep(1)
                        continue
                    cur_url, cur_title, cur_id = next_queue.pop(0)
                    mark_played(cur_title, cur_id)
                    add_session_track(cur_url, cur_title, cur_id)
                    current_anchor = cur_title
                    cur_tag = f"track_{track_counter}"
                    track_counter += 1
                    show_loading(f"Caching next track: {cur_title}...")
                    cur_file = download_temp_track(cur_url, cur_tag)
                else:
                    cur_tag = prefetcher.track_tag
                    if not prefetcher.done_event.is_set():
                        show_loading(f"Finishing cache: {prefetcher.resolved_title}...")
                    cur_file, cur_title, cur_id = prefetcher.wait_and_get()
                    mark_played(cur_title, cur_id)
                    current_anchor = cur_title

                next_prefetcher = None
                next_preview = "Queueing..."
                if next_queue:
                    nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                    mark_played(nxt_title, nxt_id)
                    add_session_track(nxt_url, nxt_title, nxt_id)
                    next_preview = nxt_title[:35]
                    next_prefetcher = BackgroundPrefetcher(nxt_url, f"track_{track_counter}", known_title=nxt_title, known_id=nxt_id)
                    track_counter += 1
                    next_prefetcher.start()

                if cur_file:
                    session_idx = len(SESSION_TRACKS) - 1
                    res = play_with_touch_ui(stdscr, cur_file, cur_tag, cur_title, mode_title, f"AUTO-NEXT #{auto_num:02d}", next_preview)
                    auto_num += 1
                    if res == "STOP":
                        return
                    while res == "PREV" and not STOP_EVENT.is_set():
                        session_idx = max(0, session_idx - 1)
                        prev_obj = SESSION_TRACKS[session_idx]
                        res = play_specific_session_track(stdscr, prev_obj, track_counter, mode_title, f"PREV #{session_idx + 1:02d}", next_preview)
                        track_counter += 1
                        if res == "STOP":
                            return
                else:
                    cleanup_temp_files(cur_tag)

                prefetcher = next_prefetcher

        # Playlist or History with PREV support
        else:
            total = len(songs)
            resolved_list = []
            for s in songs:
                u, t, vid = fetch_track_meta(s if s.startswith("http") else f"ytsearch1:{s}")
                resolved_list.append({"url": u, "title": t, "id": vid})

            idx = 0
            first_tag = f"track_{track_counter}"
            track_counter += 1
            show_loading(f"Loading track 1/{total}: {resolved_list[0]['title']}...")
            cur_file = download_temp_track(resolved_list[0]["url"], first_tag)
            cur_tag = first_tag

            while 0 <= idx < total and not STOP_EVENT.is_set():
                next_prefetcher = None
                next_preview = "End of Queue"
                if idx + 1 < total:
                    nxt_item = resolved_list[idx + 1]
                    next_preview = nxt_item["title"][:35]
                    next_prefetcher = BackgroundPrefetcher(nxt_item["url"], f"track_{track_counter}", known_title=nxt_item["title"], known_id=nxt_item["id"])
                    track_counter += 1
                    next_prefetcher.start()

                if cur_file:
                    res = play_with_touch_ui(stdscr, cur_file, cur_tag, resolved_list[idx]["title"], mode_title, f"TRACK [{idx+1:02d}/{total:02d}]", next_preview)
                    if res == "STOP":
                        return
                    if res == "PREV":
                        if next_prefetcher is not None:
                            cleanup_temp_files(next_prefetcher.track_tag)
                        idx = max(0, idx - 1)
                        prev_tag = f"track_{track_counter}"
                        track_counter += 1
                        show_loading(f"Loading previous track: {resolved_list[idx]['title']}...")
                        cur_file = download_temp_track(resolved_list[idx]["url"], prev_tag)
                        cur_tag = prev_tag
                        continue
                else:
                    cleanup_temp_files(cur_tag)

                idx += 1
                if idx >= total:
                    break

                if next_prefetcher is not None:
                    cur_tag = next_prefetcher.track_tag
                    if not next_prefetcher.done_event.is_set():
                        show_loading(f"Finishing cache: {resolved_list[idx]['title']}...")
                    cur_file, _, _ = next_prefetcher.wait_and_get()
                else:
                    new_tag = f"track_{track_counter}"
                    track_counter += 1
                    show_loading(f"Loading track {idx+1}/{total}: {resolved_list[idx]['title']}...")
                    cur_file = download_temp_track(resolved_list[idx]["url"], new_tag)
                    cur_tag = new_tag

    finally:
        STOP_EVENT.set()
        kill_active_downloads()
        cleanup_temp_files()


if __name__ == "__main__":
    check_and_update(force=False, silent=True)
    is_history = "--history" in sys.argv
    try:
        curses.wrapper(curses_main, is_history)
    except KeyboardInterrupt:
        STOP_EVENT.set()
        kill_active_downloads()
        cleanup_temp_files()
