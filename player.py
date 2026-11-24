import os
import sys
import json
import subprocess
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

def render_hacker_console(title, mode_label, index_label):
    os.system('clear')
    display_title = (title[:38] + '...') if len(title) > 41 else title.ljust(41)

    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}  [CYBER-AUDIO TERMINAL v3.0] {CYAN}:: {mode_label.ljust(22)} {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SOURCE   : {WHITE}Mirror Note/music.txt                       {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}QUEUE    : {CYAN}{index_label.ljust(45)} {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}PAYLOAD  : {GREEN}{display_title}     {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SIGNAL   : {GREEN}▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅▃▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅ {GREEN}║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{CYAN}[CONTROLS] {WHITE}Next Track: {GREEN}'q'{WHITE} | Pause/Play: {GREEN}'Space'{WHITE} | Exit: {RED}'Ctrl+C'{RESET}\n")

def resolve_stream_and_title(query):
    """Returns (stream_url, video_title, webpage_url) for a search query or URL."""
    try:
        raw = subprocess.check_output(
            ["yt-dlp", "--no-warnings", "--no-playlist", "-j", "-f", "bestaudio/best", query],
            stderr=subprocess.DEVNULL,
            timeout=25
        ).decode("utf-8", errors="ignore").strip()

        if not raw:
            return None, query, None

        first_line = raw.splitlines()[0]
        data = json.loads(first_line)
        stream_url = data.get("url")
        title = data.get("title") or query
        webpage_url = data.get("webpage_url")
        return stream_url, title, webpage_url
    except Exception:
        return None, query, None

def get_auto_suggestions(seed_song, played_titles, limit=8):
    """Finds related songs/mix based on the single song in music.txt."""
    suggestions = []
    search_queries = [
        f"ytsearch{limit}:{seed_song} song",
        f"ytsearch{limit}:{seed_song} similar songs mix"
    ]

    for sq in search_queries:
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

def play_mpv(stream_url):
    return subprocess.run([
        "mpv",
        "--no-video",
        "--term-osd-bar",
        "--term-osd-bar-chars=━╸─",
        stream_url
    ])

def play_playlist():
    # Background auto-update check from GitHub
    check_and_update(force=False, silent=True)

    if not os.path.exists(MUSIC_TXT_PATH):
        print(f"{RED}[ERROR] Playlist file missing: {MUSIC_TXT_PATH}{RESET}")
        return

    with open(MUSIC_TXT_PATH, "r", encoding="utf-8") as f:
        songs = [line.strip() for line in f if line.strip()]

    if not songs:
        print(f"{YELLOW}[WARN] Playlist empty. Add song names to 'Mirror Note/music.txt'{RESET}")
        return

    played_titles = set()

    try:
        # Case 1: Sirf 1 hi gaana likha hai -> Auto-Suggest mode active
        if len(songs) == 1:
            seed_song = songs[0]
            render_hacker_console(seed_song, "AUTO-SUGGEST SEED", "TRACK [01 / AUTO]")
            print(f"{DARK_GREEN}[*] Single track detected. Auto-Suggest engine armed for '{seed_song}'...{RESET}")

            query = seed_song if seed_song.startswith("http") else f"ytsearch1:{seed_song}"
            stream_url, actual_title, _ = resolve_stream_and_title(query)
            played_titles.add(actual_title.lower())
            played_titles.add(seed_song.lower())

            if stream_url:
                render_hacker_console(actual_title, "AUTO-SUGGEST SEED", "TRACK [01 / AUTO]")
                print(f"{GREEN}[✓] Playing seed track. Preparing auto-suggestions...{RESET}\n")
                proc = play_mpv(stream_url)
                if proc.returncode not in (0, 4):
                    print(f"\n{RED}[!] SESSION TERMINATED BY USER.{RESET}")
                    return

            # Continuous Auto-Suggested tracks loop
            auto_num = 2
            while True:
                suggestions = get_auto_suggestions(actual_title, played_titles, limit=8)
                if not suggestions:
                    suggestions = get_auto_suggestions(seed_song, played_titles, limit=8)

                if not suggestions:
                    print(f"{YELLOW}[!] No more new suggestions found. Resetting suggestion pool...{RESET}")
                    played_titles = {actual_title.lower(), seed_song.lower()}
                    time.sleep(1.5)
                    continue

                for sug_url, sug_title in suggestions:
                    render_hacker_console(sug_title, "AUTO-SUGGESTED", f"SUGGESTED #{auto_num:02d}")
                    print(f"{CYAN}[~] Auto-Suggested from '{actual_title[:28]}'...{RESET}")
                    stream_url, resolved_title, _ = resolve_stream_and_title(sug_url)
                    played_titles.add(sug_title.lower())
                    played_titles.add(resolved_title.lower())

                    if stream_url:
                        render_hacker_console(resolved_title, "AUTO-SUGGESTED", f"SUGGESTED #{auto_num:02d}")
                        print(f"{GREEN}[✓] Stream Locked. Injecting audio into MPV...{RESET}\n")
                        proc = play_mpv(stream_url)
                        auto_num += 1
                        if proc.returncode not in (0, 4):
                            print(f"\n{RED}[!] SESSION TERMINATED BY USER.{RESET}")
                            return
                    else:
                        print(f"{RED}[✗] Failed to resolve suggested stream. Trying next...{RESET}")
                        time.sleep(1)

        # Case 2: 2 ya zyada gaane likhe hain -> Normal list playback
        else:
            for i, song in enumerate(songs, 1):
                render_hacker_console(song, "PLAYLIST STREAM", f"TRACK [{i:02d}/{len(songs):02d}]")
                print(f"{DARK_GREEN}[*] Resolving encrypted audio stream for '{song}'...{RESET}")

                query = song if song.startswith("http") else f"ytsearch1:{song}"
                stream_url, actual_title, _ = resolve_stream_and_title(query)

                if stream_url:
                    render_hacker_console(actual_title, "PLAYLIST STREAM", f"TRACK [{i:02d}/{len(songs):02d}]")
                    print(f"{GREEN}[✓] Stream Locked. Injecting audio into MPV...{RESET}\n")
                    proc = play_mpv(stream_url)
                    if proc.returncode not in (0, 4):
                        print(f"\n{RED}[!] SESSION TERMINATED BY USER.{RESET}")
                        break
                else:
                    print(f"{RED}[✗] Failed to locate stream for '{song}'. Skipping...{RESET}")
                    time.sleep(1.5)

    except KeyboardInterrupt:
        print(f"\n{RED}[!] SYSTEM INTERRUPT RECEIVED. EXITING PLAYER...{RESET}")
        sys.exit(0)

if __name__ == "__main__":
    play_playlist()
