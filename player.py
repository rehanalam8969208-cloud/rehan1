import os
import re
import sys
import json
import glob
import shutil
import subprocess
import threading
import time
from updater import check_and_update

# Hacker Matrix Palette
GREEN = '\033[38;5;46m'
DARK_GREEN = '\033[38;5;28m'
CYAN = '\033[38;5;51m'
WHITE = '\033[1;37m'
RED = '\033[38;5;196m'
YELLOW = '\033[38;5;226m'
RESET = '\033[0m'

BASE_NOTES_DIR = "/storage/emulated/0/Mirror Note"
MUSIC_TXT_PATH = os.path.join(BASE_NOTES_DIR, "music.txt")
HISTORY_TXT_PATH = os.path.join(BASE_NOTES_DIR, "history.txt")
TEMP_CACHE_DIR = os.path.join(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp"), "mirror_note_audio_cache")

STOP_EVENT = threading.Event()
ACTIVE_DOWNLOAD_PROCS = set()
PROC_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()

SEEN_IDS = set()
SEEN_TITLES = set()
SEEN_KEYS = set()

def ensure_history_file():
    try:
        os.makedirs(BASE_NOTES_DIR, exist_ok=True)
        if not os.path.exists(HISTORY_TXT_PATH):
            with open(HISTORY_TXT_PATH, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:
        pass

def record_to_history(song_title):
    """Automatically saves every played song at the top of Mirror Note/history.txt without duplicates."""
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

            # Purana duplicate hata kar latest bajaye gaye gaane ko sabse upar rakhein
            filtered = [line for line in existing if line.lower() != clean_entry.lower()]
            updated = [clean_entry] + filtered[:499]  # Max 500 recent songs history

            with open(HISTORY_TXT_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(updated) + "\n")
        except Exception:
            pass

def normalize_title(title):
    cleaned = re.sub(r'\[[^\]]*\]|\([^\)]*\)', ' ', (title or '').lower())
    cleaned = re.sub(r'\b(official|video|audio|lyrics|lyric|hd|4k|hq|song|songs|music|remix|slowed|reverb|status|whatsapp|full)\b', ' ', cleaned)
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', cleaned)
    tokens = [t for t in cleaned.split() if len(t) > 1]
    return " ".join(tokens)

def is_already_played(title, video_id=None):
    if video_id and video_id in SEEN_IDS:
        return True
    norm = normalize_title(title)
    if norm and norm in SEEN_TITLES:
        return True
    words = norm.split()
    if len(words) >= 2:
        key_pair = " ".join(words[:2])
        if key_pair in SEEN_KEYS:
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

def render_hacker_console(title, mode_label, index_label, next_status="STANDBY", source_label="Mirror Note/music.txt"):
    os.system('clear')
    display_title = (title[:38] + '...') if len(title) > 41 else title.ljust(41)

    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}  [CYBER-AUDIO TERMINAL v4.5] {CYAN}:: {mode_label.ljust(22)} {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SOURCE   : {WHITE}{source_label.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}HISTORY  : {CYAN}AUTO-LOGGING -> Mirror Note/history.txt       {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}NEXT-UP  : {YELLOW}{next_status.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}QUEUE    : {CYAN}{index_label.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}PAYLOAD  : {GREEN}{display_title}     {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SIGNAL   : {GREEN}▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅▃▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅ {GREEN}║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{CYAN}[CONTROLS] {WHITE}Next: {GREEN}'q'{WHITE} | Pause: {GREEN}'Space'{WHITE} | History Mode: {GREEN}'H'{WHITE} | Exit: {RED}'Ctrl+C'{RESET}\n")

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
        title = data.get("title") or query
        webpage_url = data.get("webpage_url") or query
        vid_id = data.get("id")
        return webpage_url, title, vid_id
    except Exception:
        return query, query, None

def download_temp_track(target_query, track_tag):
    if STOP_EVENT.is_set():
        return None

    ensure_temp_dir()
    cleanup_temp_files(track_tag)
    out_template = os.path.join(TEMP_CACHE_DIR, f"{track_tag}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "-o", out_template,
        target_query
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
        valid_files = [f for f in matches if not f.endswith(".part") and not f.endswith(".ytdl")]
        return valid_files[0] if valid_files else None
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
        f"ytsearch{count}:best {clean_anchor[:25]} songs"
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
                if not norm:
                    continue

                if any(normalize_title(t) == norm for _, t, _ in results):
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

def play_temp_file_and_purge(local_audio_path, track_tag, song_title_for_history):
    # Gaana bajte hi history.txt mein save karein
    record_to_history(song_title_for_history)
    try:
        proc = subprocess.run([
            "mpv",
            "--no-video",
            "--term-osd-bar",
            "--term-osd-bar-chars=━╸─",
            local_audio_path
        ])
        return proc.returncode
    finally:
        cleanup_temp_files(track_tag)

def play_list_tracks(songs, mode_title, source_label):
    track_counter = 1
    total = len(songs)
    first_query = songs[0] if songs[0].startswith("http") else f"ytsearch1:{songs[0]}"
    render_hacker_console(songs[0], mode_title, f"TRACK [01/{total:02d}]", "LOADING TRACK 1...", source_label)
    first_url, first_title, _ = fetch_track_meta(first_query)
    first_tag = f"track_{track_counter}"
    track_counter += 1
    cur_file = download_temp_track(first_url, first_tag)
    cur_title = first_title
    cur_tag = first_tag

    for i in range(total):
        if STOP_EVENT.is_set():
            break

        next_prefetcher = None
        next_preview = "END OF QUEUE"
        if i + 1 < total:
            nxt_song = songs[i + 1]
            nxt_query = nxt_song if nxt_song.startswith("http") else f"ytsearch1:{nxt_song}"
            next_preview = f"PRE-FETCHING: {nxt_song[:26]}"
            next_prefetcher = BackgroundPrefetcher(nxt_query, f"track_{track_counter}")
            track_counter += 1
            next_prefetcher.start()

        if cur_file:
            render_hacker_console(cur_title, mode_title, f"TRACK [{i+1:02d}/{total:02d}]", next_preview, source_label)
            print(f"{GREEN}[✓] Playing & saved to history.txt (Temp space auto-purges after play).{RESET}\n")
            ret = play_temp_file_and_purge(cur_file, cur_tag, cur_title)
            if ret not in (0, 4):
                STOP_EVENT.set()
                kill_active_downloads()
                cleanup_temp_files()
                print(f"\n{RED}[!] SESSION TERMINATED. ALL TEMP SPACE FREED.{RESET}")
                break
        else:
            cleanup_temp_files(cur_tag)
            print(f"{RED}[✗] Failed to load '{cur_title}'. Moving to next...{RESET}")
            time.sleep(0.8)

        if next_prefetcher is not None:
            cur_tag = next_prefetcher.track_tag
            if not next_prefetcher.done_event.is_set():
                render_hacker_console(songs[i + 1], mode_title, f"TRACK [{i+2:02d}/{total:02d}]", "FINISHING CACHE...", source_label)
            cur_file, cur_title, _ = next_prefetcher.wait_and_get()

def play_playlist(history_mode=False):
    STOP_EVENT.clear()
    SEEN_IDS.clear()
    SEEN_TITLES.clear()
    SEEN_KEYS.clear()

    check_and_update(force=False, silent=True)
    ensure_history_file()
    ensure_temp_dir()
    cleanup_temp_files()

    try:
        # HISTORY MODE ('H' ya 'h' command se chalne par)
        if history_mode:
            if not os.path.exists(HISTORY_TXT_PATH):
                print(f"{RED}[ERROR] History file missing: {HISTORY_TXT_PATH}{RESET}")
                return

            with open(HISTORY_TXT_PATH, "r", encoding="utf-8") as f:
                history_songs = [line.strip() for line in f if line.strip()]

            if not history_songs:
                print(f"{YELLOW}[WARN] History abhi khali hai! Pehle 'play' se kuch gaane bajayein.{RESET}")
                return

            play_list_tracks(history_songs, "HISTORY PLAYBACK", "Mirror Note/history.txt")
            return

        # NORMAL / AUTO-NEXT MODE ('play' command se chalne par)
        if not os.path.exists(MUSIC_TXT_PATH):
            print(f"{RED}[ERROR] Playlist file missing: {MUSIC_TXT_PATH}{RESET}")
            return

        with open(MUSIC_TXT_PATH, "r", encoding="utf-8") as f:
            songs = [line.strip() for line in f if line.strip()]

        if not songs:
            print(f"{YELLOW}[WARN] Playlist empty. Add song names to 'Mirror Note/music.txt'{RESET}")
            return

        track_counter = 1

        # CASE 1: 1 song in music.txt -> YouTube Auto-Next Radio + Auto-History
        if len(songs) == 1:
            seed_song = songs[0]
            render_hacker_console(seed_song, "YT AUTO-NEXT RADIO", "TRACK [01 / AUTO]", "LOCKING FIRST TRACK...", "Mirror Note/music.txt")
            print(f"{DARK_GREEN}[*] Starting YouTube-style non-repeating radio from '{seed_song}'...{RESET}")

            query = seed_song if seed_song.startswith("http") else f"ytsearch1:{seed_song}"
            resolved_url, actual_title, actual_id = fetch_track_meta(query)
            mark_played(actual_title, actual_id, seed_song)

            seed_tag = f"track_{track_counter}"
            track_counter += 1
            seed_file = download_temp_track(resolved_url, seed_tag)

            next_queue = get_youtube_style_next_tracks(actual_title, seed_song, count=10)
            prefetcher = None
            next_status = "FINDING NEXT SONG..."
            current_anchor = actual_title

            if next_queue:
                nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                mark_played(nxt_title, nxt_id)
                current_anchor = nxt_title
                next_status = f"NEXT: {nxt_title[:32]}"
                prefetcher = BackgroundPrefetcher(nxt_url, f"track_{track_counter}", known_title=nxt_title, known_id=nxt_id)
                track_counter += 1
                prefetcher.start()

            if seed_file:
                render_hacker_console(actual_title, "YT AUTO-NEXT RADIO", "TRACK [01 / AUTO]", next_status, "Mirror Note/music.txt")
                print(f"{GREEN}[✓] Playing now & logged to history.txt! Next unique song pre-fetching...{RESET}\n")
                ret = play_temp_file_and_purge(seed_file, seed_tag, actual_title)
                if ret not in (0, 4):
                    STOP_EVENT.set()
                    kill_active_downloads()
                    cleanup_temp_files()
                    print(f"\n{RED}[!] SESSION TERMINATED. TEMP SPACE FREED.{RESET}")
                    return
            else:
                cleanup_temp_files(seed_tag)

            auto_num = 2
            while not STOP_EVENT.is_set():
                if len(next_queue) < 3:
                    more_tracks = get_youtube_style_next_tracks(current_anchor, seed_song, count=10)
                    next_queue.extend(more_tracks)

                if prefetcher is None:
                    if not next_queue:
                        time.sleep(1)
                        continue
                    cur_url, cur_title, cur_id = next_queue.pop(0)
                    mark_played(cur_title, cur_id)
                    current_anchor = cur_title
                    cur_tag = f"track_{track_counter}"
                    track_counter += 1
                    render_hacker_console(cur_title, "YT AUTO-NEXT RADIO", f"AUTO-NEXT #{auto_num:02d}", "BUFFERING...", "Mirror Note/music.txt")
                    cur_file = download_temp_track(cur_url, cur_tag)
                else:
                    cur_tag = prefetcher.track_tag
                    if not prefetcher.done_event.is_set():
                        render_hacker_console(prefetcher.resolved_title, "YT AUTO-NEXT RADIO", f"AUTO-NEXT #{auto_num:02d}", "FINISHING CACHE...", "Mirror Note/music.txt")
                    cur_file, cur_title, cur_id = prefetcher.wait_and_get()
                    mark_played(cur_title, cur_id)
                    current_anchor = cur_title

                next_prefetcher = None
                next_preview = "QUEUEING NEXT..."
                if next_queue:
                    nxt_url, nxt_title, nxt_id = next_queue.pop(0)
                    mark_played(nxt_title, nxt_id)
                    next_preview = f"NEXT: {nxt_title[:32]}"
                    next_prefetcher = BackgroundPrefetcher(nxt_url, f"track_{track_counter}", known_title=nxt_title, known_id=nxt_id)
                    track_counter += 1
                    next_prefetcher.start()

                if cur_file:
                    render_hacker_console(cur_title, "YT AUTO-NEXT RADIO", f"AUTO-NEXT #{auto_num:02d}", next_preview, "Mirror Note/music.txt")
                    print(f"{GREEN}[✓] Playing & saved to history.txt! Previous space already purged.{RESET}\n")
                    ret = play_temp_file_and_purge(cur_file, cur_tag, cur_title)
                    auto_num += 1
                    if ret not in (0, 4):
                        STOP_EVENT.set()
                        kill_active_downloads()
                        cleanup_temp_files()
                        print(f"\n{RED}[!] SESSION TERMINATED. TEMP SPACE FREED.{RESET}")
                        return
                else:
                    cleanup_temp_files(cur_tag)
                    print(f"{RED}[✗] Unavailable track, skipping to next...{RESET}")
                    time.sleep(0.5)

                prefetcher = next_prefetcher

        # CASE 2: Multiple songs in music.txt -> Normal Zero-Gap Playlist + Auto-History
        else:
            play_list_tracks(songs, "ZERO-GAP PLAYLIST", "Mirror Note/music.txt")

    except KeyboardInterrupt:
        STOP_EVENT.set()
        kill_active_downloads()
        cleanup_temp_files()
        print(f"\n{RED}[!] SYSTEM INTERRUPT RECEIVED. TEMP CACHE PURGED (0 BYTES LEFT).{RESET}")
        sys.exit(0)
    finally:
        STOP_EVENT.set()
        kill_active_downloads()
        cleanup_temp_files()

if __name__ == "__main__":
    is_history = "--history" in sys.argv
    play_playlist(history_mode=is_history)
