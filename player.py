import os
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

MUSIC_TXT_PATH = "/storage/emulated/0/Mirror Note/music.txt"
TEMP_CACHE_DIR = os.path.join(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp"), "mirror_note_audio_cache")

STOP_EVENT = threading.Event()
ACTIVE_DOWNLOAD_PROCS = set()
PROC_LOCK = threading.Lock()

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
    """Deletes played/temporary audio cache files so zero space remains after playback."""
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

def render_hacker_console(title, mode_label, index_label, next_status="STANDBY"):
    os.system('clear')
    display_title = (title[:38] + '...') if len(title) > 41 else title.ljust(41)

    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}  [CYBER-AUDIO TERMINAL v4.0] {CYAN}:: {mode_label.ljust(22)} {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SOURCE   : {WHITE}Mirror Note/music.txt                       {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}STORAGE  : {CYAN}ZERO-SPACE AUTO-PURGE + PRE-FETCH           {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}NEXT-UP  : {YELLOW}{next_status.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}QUEUE    : {CYAN}{index_label.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}PAYLOAD  : {GREEN}{display_title}     {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SIGNAL   : {GREEN}▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅▃▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅ {GREEN}║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{CYAN}[CONTROLS] {WHITE}Next Track: {GREEN}'q'{WHITE} | Pause/Play: {GREEN}'Space'{WHITE} | Exit: {RED}'Ctrl+C'{RESET}\n")

def fetch_title_and_url(query):
    """Resolves actual video title and direct webpage URL."""
    try:
        raw = subprocess.check_output(
            ["yt-dlp", "--no-warnings", "--no-playlist", "-j", "-f", "bestaudio/best", query],
            stderr=subprocess.DEVNULL,
            timeout=25
        ).decode("utf-8", errors="ignore").strip()

        if not raw:
            return query, query

        first_line = raw.splitlines()[0]
        data = json.loads(first_line)
        title = data.get("title") or query
        webpage_url = data.get("webpage_url") or query
        return webpage_url, title
    except Exception:
        return query, query

def download_temp_track(target_query, track_tag):
    """Downloads a single track into temp cache; caller deletes it immediately after play."""
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

def get_auto_suggestions(seed_song, played_titles, limit=8):
    """Finds related songs based on the single track in music.txt."""
    suggestions = []
    search_queries = [
        f"ytsearch{limit}:{seed_song} song",
        f"ytsearch{limit}:{seed_song} similar songs mix"
    ]

    for sq in search_queries:
        if STOP_EVENT.is_set():
            break
        try:
            raw = subprocess.check_output(
                ["yt-dlp", "--no-warnings", "--flat-playlist", "-j", sq],
                stderr=subprocess.DEVNULL,
                timeout=25
            ).decode("utf-8", errors="ignore").strip()

            for line in raw.splitlines():
                if not line.strip():
                    continue
                info = json.loads(line)
                title = (info.get("title") or "").strip()
                url = info.get("url") or info.get("webpage_url")
                if not title or not url:
                    continue
                if not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={url}"

                norm_title = title.lower()
                if norm_title not in played_titles and all(norm_title != s[1].lower() for s in suggestions):
                    suggestions.append((url, title))
                    if len(suggestions) >= limit:
                        return suggestions
        except Exception:
            continue

    return suggestions

class BackgroundPrefetcher:
    """Prepares the next track in the background while the current track plays."""
    def __init__(self, target_query, track_tag, known_title=None):
        self.target_query = target_query
        self.track_tag = track_tag
        self.known_title = known_title
        self.local_file = None
        self.resolved_title = known_title or target_query
        self.done_event = threading.Event()
        self.thread = threading.Thread(target=self._worker, daemon=True)

    def start(self):
        self.thread.start()

    def _worker(self):
        try:
            if STOP_EVENT.is_set():
                return
            url, title = fetch_title_and_url(self.target_query)
            if not self.known_title:
                self.resolved_title = title
            self.local_file = download_temp_track(url, self.track_tag)
        finally:
            self.done_event.set()

    def wait_and_get(self):
        while not self.done_event.is_set():
            if STOP_EVENT.is_set():
                return None, self.resolved_title
            time.sleep(0.15)
        return self.local_file, self.resolved_title

def play_temp_file_and_purge(local_audio_path, track_tag):
    """Plays local cached track and immediately deletes it once finished/skipped/stopped."""
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

def play_playlist():
    STOP_EVENT.clear()
    check_and_update(force=False, silent=True)
    ensure_temp_dir()
    cleanup_temp_files()

    if not os.path.exists(MUSIC_TXT_PATH):
        print(f"{RED}[ERROR] Playlist file missing: {MUSIC_TXT_PATH}{RESET}")
        return

    with open(MUSIC_TXT_PATH, "r", encoding="utf-8") as f:
        songs = [line.strip() for line in f if line.strip()]

    if not songs:
        print(f"{YELLOW}[WARN] Playlist empty. Add song names to 'Mirror Note/music.txt'{RESET}")
        return

    played_titles = set()
    track_counter = 1

    try:
        # CASE 1: Single song in music.txt -> Auto-Suggest + Background Pre-Fetch + Auto-Purge
        if len(songs) == 1:
            seed_song = songs[0]
            render_hacker_console(seed_song, "AUTO-SUGGEST SEED", "TRACK [01 / AUTO]", "LOCKING SEED...")
            print(f"{DARK_GREEN}[*] Loading first track & preparing Auto-Suggest engine...{RESET}")

            query = seed_song if seed_song.startswith("http") else f"ytsearch1:{seed_song}"
            resolved_url, actual_title = fetch_title_and_url(query)
            played_titles.add(actual_title.lower())
            played_titles.add(seed_song.lower())

            seed_tag = f"track_{track_counter}"
            track_counter += 1
            seed_file = download_temp_track(resolved_url, seed_tag)

            # First track bajne se pehle hi auto-suggestions fetch karke next track background mein lagayein
            suggestion_queue = get_auto_suggestions(actual_title, played_titles, limit=8)
            if not suggestion_queue:
                suggestion_queue = get_auto_suggestions(seed_song, played_titles, limit=8)

            prefetcher = None
            next_title_preview = "SEARCHING..."
            if suggestion_queue:
                next_url, next_title = suggestion_queue.pop(0)
                played_titles.add(next_title.lower())
                next_title_preview = f"PRE-FETCHING: {next_title[:26]}"
                prefetcher = BackgroundPrefetcher(next_url, f"track_{track_counter}", known_title=next_title)
                track_counter += 1
                prefetcher.start()

            if seed_file:
                render_hacker_console(actual_title, "AUTO-SUGGEST SEED", "TRACK [01 / AUTO]", next_title_preview)
                print(f"{GREEN}[✓] Playing now! Next track is pre-fetching in background (0-sec gap).{RESET}\n")
                ret = play_temp_file_and_purge(seed_file, seed_tag)
                if ret not in (0, 4):
                    STOP_EVENT.set()
                    kill_active_downloads()
                    cleanup_temp_files()
                    print(f"\n{RED}[!] SESSION TERMINATED. ALL TEMP SPACE FREED.{RESET}")
                    return
            else:
                cleanup_temp_files(seed_tag)

            auto_num = 2
            while not STOP_EVENT.is_set():
                if not suggestion_queue:
                    new_sugs = get_auto_suggestions(actual_title, played_titles, limit=8)
                    if not new_sugs:
                        played_titles = {actual_title.lower(), seed_song.lower()}
                        new_sugs = get_auto_suggestions(seed_song, played_titles, limit=8)
                    suggestion_queue.extend(new_sugs)

                if prefetcher is None:
                    if not suggestion_queue:
                        time.sleep(1)
                        continue
                    cur_url, cur_title = suggestion_queue.pop(0)
                    played_titles.add(cur_title.lower())
                    cur_tag = f"track_{track_counter}"
                    track_counter += 1
                    render_hacker_console(cur_title, "AUTO-SUGGESTED", f"SUGGESTED #{auto_num:02d}", "BUFFERING...")
                    cur_file = download_temp_track(cur_url, cur_tag)
                else:
                    cur_tag = prefetcher.track_tag
                    if not prefetcher.done_event.is_set():
                        render_hacker_console(prefetcher.resolved_title, "AUTO-SUGGESTED", f"SUGGESTED #{auto_num:02d}", "FINISHING CACHE...")
                    cur_file, cur_title = prefetcher.wait_and_get()

                # Agle gaane ko turant background pre-fetch par lagayein
                next_prefetcher = None
                next_preview = "QUEUEING NEXT..."
                if suggestion_queue:
                    nxt_url, nxt_title = suggestion_queue.pop(0)
                    played_titles.add(nxt_title.lower())
                    next_preview = f"READYING: {nxt_title[:30]}"
                    next_prefetcher = BackgroundPrefetcher(nxt_url, f"track_{track_counter}", known_title=nxt_title)
                    track_counter += 1
                    next_prefetcher.start()

                if cur_file:
                    render_hacker_console(cur_title, "AUTO-SUGGESTED", f"SUGGESTED #{auto_num:02d}", next_preview)
                    print(f"{GREEN}[✓] Zero-gap playback active! Played file auto-deletes right after.{RESET}\n")
                    ret = play_temp_file_and_purge(cur_file, cur_tag)
                    auto_num += 1
                    if ret not in (0, 4):
                        STOP_EVENT.set()
                        kill_active_downloads()
                        cleanup_temp_files()
                        print(f"\n{RED}[!] SESSION TERMINATED. ALL TEMP SPACE FREED.{RESET}")
                        return
                else:
                    cleanup_temp_files(cur_tag)
                    print(f"{RED}[✗] Track unavailable, jumping immediately to next...{RESET}")
                    time.sleep(0.5)

                prefetcher = next_prefetcher

        # CASE 2: Multiple songs in music.txt -> Zero-Gap Pre-Fetch + Instant Auto-Purge
        else:
            total = len(songs)
            first_query = songs[0] if songs[0].startswith("http") else f"ytsearch1:{songs[0]}"
            render_hacker_console(songs[0], "ZERO-GAP PLAYLIST", f"TRACK [01/{total:02d}]", "LOADING TRACK 1...")
            first_url, first_title = fetch_title_and_url(first_query)
            first_tag = f"track_{track_counter}"
            track_counter += 1
            cur_file = download_temp_track(first_url, first_tag)
            cur_title = first_title
            cur_tag = first_tag

            for i in range(total):
                if STOP_EVENT.is_set():
                    break

                # Next song ko background mein pre-fetch karein
                next_prefetcher = None
                next_preview = "END OF PLAYLIST"
                if i + 1 < total:
                    nxt_song = songs[i + 1]
                    nxt_query = nxt_song if nxt_song.startswith("http") else f"ytsearch1:{nxt_song}"
                    next_preview = f"PRE-FETCHING: {nxt_song[:26]}"
                    next_prefetcher = BackgroundPrefetcher(nxt_query, f"track_{track_counter}")
                    track_counter += 1
                    next_prefetcher.start()

                if cur_file:
                    render_hacker_console(cur_title, "ZERO-GAP PLAYLIST", f"TRACK [{i+1:02d}/{total:02d}]", next_preview)
                    print(f"{GREEN}[✓] Playing from temp cache. Auto-deletes immediately after play.{RESET}\n")
                    ret = play_temp_file_and_purge(cur_file, cur_tag)
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
                        render_hacker_console(songs[i + 1], "ZERO-GAP PLAYLIST", f"TRACK [{i+2:02d}/{total:02d}]", "FINISHING CACHE...")
                    cur_file, cur_title = next_prefetcher.wait_and_get()

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
    play_playlist()
