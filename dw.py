import os
import sys
import time
import curses
import subprocess
from updater import check_and_update

BASE_NOTES_DIR = "/storage/emulated/0/Mirror Note"
SAVE_DIR = "/storage/emulated/0/Download"


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


def read_items(platform_name):
    txt_path = os.path.join(BASE_NOTES_DIR, f"{platform_name}.txt")
    if not os.path.exists(txt_path):
        return [], txt_path
    with open(txt_path, "r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip()]
    return items, txt_path


def run_downloads_in_terminal(platform_name, fmt_type):
    """Exits curses cleanly so yt-dlp progress and logs display normally."""
    os.system("clear")
    items, txt_path = read_items(platform_name)

    print(f"[CYBER DOWNLOADER] :: {platform_name.upper()} -> {fmt_type.upper()}")
    print(f"SOURCE FILE : {txt_path}")
    print("-" * 52)

    if not os.path.exists(txt_path):
        print(f"[ERROR] File nahi mili: {txt_path}")
        return

    if not items:
        print(f"[EMPTY] '{platform_name}.txt' mein koi link ya naam nahi hai.")
        return

    os.makedirs(SAVE_DIR, exist_ok=True)
    output_template = os.path.join(SAVE_DIR, "%(title).80s.%(ext)s")

    print(f"[FOUND] Total {len(items)} item(s) to download.\n")

    for idx, item in enumerate(items, 1):
        print(f"[{idx}/{len(items)}] {item}")
        target = item if (item.startswith("http://") or item.startswith("https://")) else f"ytsearch1:{item}"

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-playlist",
            "--restrict-filenames",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "-o",
            output_template,
        ]

        if fmt_type == "mp4":
            if platform_name == "youtube":
                cmd.extend(["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "--merge-output-format", "mp4"])
            else:
                cmd.extend(["-f", "best[ext=mp4]/best", "--merge-output-format", "mp4"])
        else:
            cmd.extend([
                "-f", "bestaudio/best",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--embed-metadata",
            ])

        cmd.append(target)

        rc = subprocess.call(cmd)
        if rc == 0:
            print(f"[DONE] Saved in {SAVE_DIR}\n")
            subprocess.run(
                ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{SAVE_DIR}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            print(f"[FAILED] Item {idx} download nahi ho saka.\n")

    print("=" * 52)
    print("[COMPLETED] Sabhi downloads poore hue.")


def touch_menu_ui(stdscr):
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

    selected_platform = None  # None -> choose platform, "insta" / "youtube" -> choose mp3/mp4

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        stdscr.addstr(1, 2, "[CYBER DOWNLOADER TOUCH MENU]"[:max(1, w - 3)], curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(2, 2, ("." * max(1, w - 4))[:max(1, w - 3)], curses.color_pair(1))

        btn_regions = []
        avail_w = max(24, w - 6)
        gap = 3

        if selected_platform is None:
            insta_items, _ = read_items("insta")
            yt_items, _ = read_items("youtube")

            stdscr.addstr(4, 2, "Platform chunein (Tap button):"[:max(1, w - 3)], curses.color_pair(3) | curses.A_BOLD)
            stdscr.addstr(6, 2, f"insta.txt   : {len(insta_items)} item(s)"[:max(1, w - 3)], curses.color_pair(4))
            stdscr.addstr(7, 2, f"youtube.txt : {len(yt_items)} item(s)"[:max(1, w - 3)], curses.color_pair(4))

            row_y = max(10, min(h - 6, 11))
            bw = max(10, (avail_w - gap) // 2)
            b1 = draw_round_pill(stdscr, row_y, 3, bw, "INSTAGRAM", curses.color_pair(1))
            b2 = draw_round_pill(stdscr, row_y, 3 + bw + gap, bw, "YOUTUBE", curses.color_pair(1))
            if b1:
                btn_regions.append((b1, "pick_insta"))
            if b2:
                btn_regions.append((b2, "pick_youtube"))

            exit_y = row_y + 4
            b_exit = draw_round_pill(stdscr, exit_y, 3, max(10, avail_w // 2), "EXIT", curses.color_pair(2))
            if b_exit:
                btn_regions.append((b_exit, "exit"))

            if exit_y + 2 < h:
                stdscr.addstr(exit_y + 2, 2, "Keys: [1]=Instagram  [2]=YouTube  [x]=Exit"[:max(1, w - 3)], curses.color_pair(3))
        else:
            items, _ = read_items(selected_platform)
            stdscr.addstr(4, 2, f"Selected : {selected_platform.upper()}"[:max(1, w - 3)], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(5, 2, f"Queue    : {len(items)} item(s) in {selected_platform}.txt"[:max(1, w - 3)], curses.color_pair(4))
            stdscr.addstr(7, 2, "Format chunein (Tap button):"[:max(1, w - 3)], curses.color_pair(3) | curses.A_BOLD)

            row_y = max(9, min(h - 6, 10))
            bw = max(10, (avail_w - gap) // 2)
            b_mp3 = draw_round_pill(stdscr, row_y, 3, bw, "MP3", curses.color_pair(1))
            b_mp4 = draw_round_pill(stdscr, row_y, 3 + bw + gap, bw, "MP4", curses.color_pair(1))
            if b_mp3:
                btn_regions.append((b_mp3, "dl_mp3"))
            if b_mp4:
                btn_regions.append((b_mp4, "dl_mp4"))

            back_y = row_y + 4
            b_back = draw_round_pill(stdscr, back_y, 3, max(10, avail_w // 2), "BACK", curses.color_pair(2))
            if b_back:
                btn_regions.append((b_back, "back"))

            if back_y + 2 < h:
                stdscr.addstr(back_y + 2, 2, "Keys: [m]=MP3  [v]=MP4  [b]=Back"[:max(1, w - 3)], curses.color_pair(3))

        stdscr.refresh()

        key = stdscr.getch()
        act = None

        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, _ = curses.getmouse()
                for (x1, x2, y1, y2), region_act in btn_regions:
                    if x1 <= mx <= x2 and y1 <= my <= y2:
                        act = region_act
                        break
            except Exception:
                pass
        elif selected_platform is None:
            if key in (ord("1"), ord("i"), ord("I")):
                act = "pick_insta"
            elif key in (ord("2"), ord("y"), ord("Y")):
                act = "pick_youtube"
            elif key in (3, 27, ord("x"), ord("X"), ord("q"), ord("Q")):
                act = "exit"
        else:
            if key in (ord("1"), ord("m"), ord("M"), ord("a"), ord("A")):
                act = "dl_mp3"
            elif key in (ord("2"), ord("v"), ord("V")):
                act = "dl_mp4"
            elif key in (ord("b"), ord("B"), 27):
                act = "back"

        if act == "pick_insta":
            selected_platform = "insta"
        elif act == "pick_youtube":
            selected_platform = "youtube"
        elif act == "back":
            selected_platform = None
        elif act == "exit":
            return None
        elif act == "dl_mp3":
            return (selected_platform, "mp3")
        elif act == "dl_mp4":
            return (selected_platform, "mp4")


def main():
    check_and_update(force=False, silent=True)
    try:
        choice = curses.wrapper(touch_menu_ui)
    except KeyboardInterrupt:
        choice = None

    if choice:
        plat, fmt = choice
        run_downloads_in_terminal(plat, fmt)


if __name__ == "__main__":
    main()
