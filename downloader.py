import os
import sys
import subprocess
import time
from updater import check_and_update

# Hacker Matrix Color Palette
GREEN = '\033[38;5;46m'
DARK_GREEN = '\033[38;5;28m'
CYAN = '\033[38;5;51m'
WHITE = '\033[1;37m'
RED = '\033[38;5;196m'
YELLOW = '\033[38;5;226m'
RESET = '\033[0m'

BASE_DIR = "/storage/emulated/0/Mirror Note"

def banner(platform, fmt):
    os.system('clear')
    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}  [ROOT@TERMUX] :: {platform.upper()} {fmt.upper()} EXTRACTION ENGINE  {GREEN}   ║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{DARK_GREEN}  >> SOURCE: Mirror Note/{platform}.txt | MODE: STEALTH{RESET}\n")

def download_media(platform_name, format_type):
    check_and_update(force=False, silent=True)

    file_path = os.path.join(BASE_DIR, f"{platform_name}.txt")
    output_template = "/storage/emulated/0/Download/%(title).80s.%(ext)s"

    if not os.path.exists(file_path):
        print(f"{RED}[ERROR] Target .txt file not found: {file_path}{RESET}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip()]

    if not items:
        print(f"{YELLOW}[WARN] Queue is empty in '{platform_name}.txt'. Add links or song names first.{RESET}")
        return

    print(f"{CYAN}[*] {len(items)} TARGET(S) LOCKED FROM '{platform_name}.txt'.{RESET}\n")

    for i, item in enumerate(items, 1):
        print(f"{DARK_GREEN}┌──────────────────────────────────────────────────────────┐{RESET}")
        print(f"{DARK_GREEN}│ {GREEN}[TARGET {i}/{len(items)}] {WHITE}FORMAT: {format_type.upper()}{RESET}")
        print(f"{DARK_GREEN}│ {CYAN}PAYLOAD: {WHITE}{item[:45]}{'...' if len(item) > 45 else ''}{RESET}")
        print(f"{DARK_GREEN}└──────────────────────────────────────────────────────────┘{RESET}")

        if item.startswith("http://") or item.startswith("https://"):
            target = item
        else:
            target = f"ytsearch1:{item}"

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-playlist",
            "--restrict-filenames",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "-o", output_template
        ]

        if format_type == "mp4":
            if platform_name == "youtube":
                cmd.extend(["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "--merge-output-format", "mp4"])
            else:
                cmd.extend(["-f", "best[ext=mp4]/best", "--merge-output-format", "mp4"])
        elif format_type == "mp3":
            cmd.extend([
                "-f", "bestaudio/best",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--embed-metadata"
            ])

        cmd.append(target)

        try:
            print(f"{GREEN}[>] Executing stream capture...{RESET}")
            process = subprocess.run(cmd)
            if process.returncode == 0:
                print(f"{GREEN}[✓] PAYLOAD CAPTURED SUCCESSFULLY! Saved to /Download/{RESET}\n")
                subprocess.run(
                    ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file:///storage/emulated/0/Download"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                print(f"{RED}[✗] FAILED TO EXTRACT TARGET {i}. (Tip: Run 'pip install -U yt-dlp' if link is private/expired){RESET}\n")
        except Exception as e:
            print(f"{RED}[CRITICAL ERROR] {str(e)}{RESET}\n")

        time.sleep(1)

    print(f"{GREEN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{GREEN}║ {WHITE}   [✓] ALL OPERATIONS COMPLETED. CHECK DOWNLOADS.     {GREEN}   ║{RESET}")
    print(f"{GREEN}╚══════════════════════════════════════════════════════════╝{RESET}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"{RED}Usage: python downloader.py <youtube|insta> <mp3|mp4>{RESET}")
        sys.exit(1)

    platform_name = sys.argv[1]
    format_type = sys.argv[2]

    banner(platform_name, format_type)
    download_media(platform_name, format_type)
