import os
import sys
import subprocess
import time

# Hacker Matrix Palette
GREEN = '\033[38;5;46m'
DARK_GREEN = '\033[38;5;28m'
CYAN = '\033[38;5;51m'
WHITE = '\033[1;37m'
RED = '\033[38;5;196m'
YELLOW = '\033[38;5;226m'
RESET = '\033[0m'

MUSIC_TXT_PATH = "/storage/emulated/0/Mirror Note/music.txt"

def render_hacker_console(song_name, current, total):
    os.system('clear')
    display_title = (song_name[:38] + '...') if len(song_name) > 41 else song_name.ljust(41)
    
    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}  [CYBER-AUDIO TERMINAL v2.6] {CYAN}:: MATRIX STREAM ACTIVE   {GREEN} ║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SOURCE   : {WHITE}Mirror Note/music.txt                       {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}QUEUE    : {CYAN}TRACK [{current:02d}/{total:02d}]                                 {GREEN}║{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}PAYLOAD  : {GREEN}{display_title}     {GREEN}║{RESET}")
    print(f"{GREEN}╠══════════════════════════════════════════════════════════╣{RESET}")
    print(f"{GREEN}║ {DARK_GREEN}SIGNAL   : {GREEN}▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅▃▂▄▆█▇▅▃▂▅▇█▆▄▂▁▃▆█▇▅ {GREEN}║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{CYAN}[CONTROLS] {WHITE}Next Track: {GREEN}'q'{WHITE} | Pause/Play: {GREEN}'Space'{WHITE} | Exit: {RED}'Ctrl+C'{RESET}\n")

def play_playlist():
    if not os.path.exists(MUSIC_TXT_PATH):
        print(f"{RED}[ERROR] Playlist file missing: {MUSIC_TXT_PATH}{RESET}")
        return

    with open(MUSIC_TXT_PATH, "r", encoding="utf-8") as f:
        songs = [line.strip() for line in f if line.strip()]

    if not songs:
        print(f"{YELLOW}[WARN] Playlist empty. Add song names to 'Mirror Note/music.txt'{RESET}")
        return

    try:
        for i, song in enumerate(songs, 1):
            render_hacker_console(song, i, len(songs))
            print(f"{DARK_GREEN}[*] Resolving encrypted audio stream for '{song}'...{RESET}")

            query = song if song.startswith("http") else f"ytsearch1:{song}"
            
            try:
                stream_url = subprocess.check_output(
                    ["yt-dlp", "--no-warnings", "-f", "bestaudio/best", "-g", query],
                    stderr=subprocess.DEVNULL
                ).decode("utf-8").strip().splitlines()[0]
            except Exception:
                stream_url = ""

            if stream_url:
                print(f"{GREEN}[✓] Stream Locked. Injecting audio into MPV...{RESET}\n")
                proc = subprocess.run([
                    "mpv",
                    "--no-video",
                    "--term-osd-bar",
                    "--term-osd-bar-chars=━╸─",
                    stream_url
                ])

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
