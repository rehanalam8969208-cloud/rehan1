#!/bin/bash

NEON_GREEN="\e[38;5;46m"
DARK_GREEN="\e[38;5;28m"
CYAN="\e[38;5;51m"
WHITE="\e[1;37m"
RED="\e[38;5;196m"
RESET="\e[0m"

clear
echo -e "${NEON_GREEN}  ██████╗██╗   ██╗██████╗ ███████╗██████╗     ████████╗ ██████╗  ██████╗ ██╗     "
echo -e "${NEON_GREEN} ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ╚══██╔══╝██╔═══██╗██╔═══██╗██║     "
echo -e "${NEON_GREEN} ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝       ██║   ██║   ██║██║   ██║██║     "
echo -e "${NEON_GREEN} ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗       ██║   ██║   ██║██║   ██║██║     "
echo -e "${NEON_GREEN} ╚██████╗   ██║   ██████╔╝███████╗██║  ██║       ██║   ╚██████╔╝╚██████╔╝███████╗"
echo -e "${NEON_GREEN}  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝       ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝"
echo -e "${DARK_GREEN} ════════════════════════════════════════════════════════════════════════════════ ${RESET}"
echo -e "${WHITE}              [ SYSTEM INITIALIZING :: MEDIA & AUDIO TERMINAL ]                  ${RESET}"
echo -e "${DARK_GREEN} ════════════════════════════════════════════════════════════════════════════════ ${RESET}\n"

echo -e "${CYAN}[*] Requesting Storage Access Permission...${RESET}"
termux-setup-storage
sleep 2

echo -e "${NEON_GREEN}[+] Updating Termux & Installing Core Dependencies (Python, FFmpeg, MPV, Git)...${RESET}"
pkg update -y
pkg upgrade -y
pkg install python ffmpeg mpv git -y

echo -e "${NEON_GREEN}[+] Installing Latest yt-dlp & Audio Libraries...${RESET}"
pip install --upgrade pip
pip install -U yt-dlp mutagen

echo -e "${CYAN}[*] Configuring '/storage/emulated/0/Mirror Note' Workspace (.txt format)...${RESET}"
mkdir -p "/storage/emulated/0/Mirror Note"
touch "/storage/emulated/0/Mirror Note/youtube.txt"
touch "/storage/emulated/0/Mirror Note/insta.txt"
touch "/storage/emulated/0/Mirror Note/music.txt"

echo -e "${NEON_GREEN}[+] Injecting Cyber Aliases & Auto-Sync into ~/.bashrc...${RESET}"
touch ~/.bashrc
sed -i '/alias imp3/d' ~/.bashrc
sed -i '/alias imp4/d' ~/.bashrc
sed -i '/alias ymp3/d' ~/.bashrc
sed -i '/alias ymp4/d' ~/.bashrc
sed -i '/alias play/d' ~/.bashrc
sed -i '/alias sync/d' ~/.bashrc
sed -i '/alias upload/d' ~/.bashrc

REPO_DIR=$(pwd)
echo "alias ymp4=\"python '$REPO_DIR/downloader.py' youtube mp4\"" >> ~/.bashrc
echo "alias ymp3=\"python '$REPO_DIR/downloader.py' youtube mp3\"" >> ~/.bashrc
echo "alias imp4=\"python '$REPO_DIR/downloader.py' insta mp4\"" >> ~/.bashrc
echo "alias imp3=\"python '$REPO_DIR/downloader.py' insta mp3\"" >> ~/.bashrc
echo "alias play=\"python '$REPO_DIR/player.py'\"" >> ~/.bashrc
echo "alias sync=\"python '$REPO_DIR/updater.py' --force\"" >> ~/.bashrc

echo -e "\n${NEON_GREEN}╔════════════════════════════════════════════════════╗${RESET}"
echo -e "${NEON_GREEN}║ ${WHITE}  [✓] INSTALLATION COMPLETE - SYSTEM READY         ${NEON_GREEN}║${RESET}"
echo -e "${NEON_GREEN}╚════════════════════════════════════════════════════╝${RESET}"
echo -e "${CYAN}[!] Run this command to activate shortcuts now: ${NEON_GREEN}source ~/.bashrc${RESET}\n"
