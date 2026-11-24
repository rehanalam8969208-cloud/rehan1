import os
import sys
import subprocess
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(REPO_DIR, ".last_update_check")
CHECK_INTERVAL = 300  # Har 5 minute mein background check

def refresh_aliases():
    bashrc_path = os.path.expanduser("~/.bashrc")
    aliases = [
        f'alias ymp4="python \'{REPO_DIR}/downloader.py\' youtube mp4"',
        f'alias ymp3="python \'{REPO_DIR}/downloader.py\' youtube mp3"',
        f'alias imp4="python \'{REPO_DIR}/downloader.py\' insta mp4"',
        f'alias imp3="python \'{REPO_DIR}/downloader.py\' insta mp3"',
        f'alias play="python \'{REPO_DIR}/player.py\'"',
        f'alias sync="python \'{REPO_DIR}/updater.py\' --force"'
    ]
    try:
        lines = []
        if os.path.exists(bashrc_path):
            with open(bashrc_path, "r", encoding="utf-8") as f:
                skip_keys = ("alias ymp4=", "alias ymp3=", "alias imp4=", "alias imp3=", "alias play=", "alias sync=", "alias upload=")
                lines = [line for line in f if not any(k in line for k in skip_keys)]
        with open(bashrc_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
            for a in aliases:
                f.write(a + "\n")
    except Exception:
        pass

def should_check():
    if not os.path.exists(CACHE_FILE):
        return True
    try:
        last_time = float(open(CACHE_FILE, "r").read().strip())
        return (time.time() - last_time) >= CHECK_INTERVAL
    except Exception:
        return True

def mark_checked():
    try:
        with open(CACHE_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

def check_and_update(force=False, silent=True):
    git_dir = os.path.join(REPO_DIR, ".git")
    if not os.path.exists(git_dir):
        if not silent:
            print("\033[38;5;226m[!] Git repository (.git) nahi mila. Auto-update ke liye repo ko git clone karein.\033[0m")
        return False

    if not force and not should_check():
        return False

    mark_checked()

    try:
        # Local untracked cache/pyc files ke conflicts se bachne ke liye fetch + reset/pull
        subprocess.run(["git", "-C", REPO_DIR, "fetch", "--quiet"], timeout=12, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local_head = subprocess.check_output(["git", "-C", REPO_DIR, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        remote_head = subprocess.check_output(["git", "-C", REPO_DIR, "rev-parse", "@{u}"], stderr=subprocess.DEVNULL).decode().strip()

        if local_head != remote_head:
            if not silent:
                print("\033[38;5;51m[*] Naya GitHub update mila! Downloading & applying...\033[0m")
            subprocess.run(["git", "-C", REPO_DIR, "pull", "--ff-only", "--quiet"], timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            refresh_aliases()
            if not silent:
                print("\033[38;5;46m[✓] Repository auto-updated to latest version!\033[0m")
            return True
        else:
            refresh_aliases()
            if not silent:
                print("\033[38;5;46m[✓] Aapka toolkit pehle se hi latest version par hai.\033[0m")
            return False
    except Exception:
        if not silent:
            print("\033[38;5;226m[!] Update check skip hua (network ya git remote check karein).\033[0m")
        return False

if __name__ == "__main__":
    is_force = "--force" in sys.argv
    check_and_update(force=is_force, silent=not is_force)
