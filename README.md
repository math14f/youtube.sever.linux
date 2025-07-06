```bash
git clone https://github.com/math14f/HackGuld-Toolkit.git
chmod +x HackGuld-Toolkit
cd HackGuld-Toolkit
sudo python3 white.hacker.tools.py




YT Channel Downloader
YT Channel Downloader is a self-hosted web application built with Flask, designed to automate the download and archiving of entire YouTube channels. It acts as a user-friendly graphical user interface (GUI) on top of the powerful command-line tool yt-dlp.

The application allows you to search for channels, add them to a download queue, automatically fetch new videos periodically, and watch your downloaded content directly in the browser via an integrated video player.

Key Features
Web-based User Interface: Manage all your downloads from a clean web interface, accessible from your local network.

Channel-based Downloads: Add an entire YouTube channel, and the system will download all of its videos.

Automatic Updates: The server periodically checks for new videos on your added channels and downloads them automatically.

Single Video Downloads: Paste a link to a single YouTube video to download it quickly.

Integrated Search: Search YouTube directly from the application to easily find and add new channels.

Local Search: Instantly search the titles of all your already-downloaded videos.

Built-in Video Player: Play your downloaded videos directly in the browser without leaving the page.

Status Dashboard: Get a clear overview of disk space, ongoing downloads, and the status of each channel (e.g., "In Progress," "Completed," "Error").

Cookie Support: Option to use a cookie file to download videos that require a login (e.g., age-restricted).

Screenshots
(Replace with links to your own screenshots for the best effect)

Homepage / Dashboard:
Shows a list of all tracked channels, their status, and a disk space overview.
![alt text](https://i.imgur.com/placeholder.png)

Channel Details & Video Player:
Shows all downloaded videos for a specific channel, with the video player active at the top.
![alt text](https://i.imgur.com/placeholder.png)

YouTube Search Results:
Shows results from a YouTube search, ready to be added to the download queue.
![alt text](https://i.imgur.com/placeholder.png)

Installation & Setup
1. Prerequisites
Before you begin, ensure you have the following installed on your server/computer:

Python 3.8+

pip (Python package installer)

yt-dlp: It is crucial that yt-dlp is installed and available in the system's PATH.

Installation Guide: yt-dlp GitHub

2. Clone the project
bash git clone <your-repository-url> cd <project-folder>

3. Install Python Dependencies
It's recommended to use a virtual environment.

bash

Create a virtual environment (optional, but recommended)
python3 -m venv venv
source venv/bin/activate # On Windows: venv\Scripts\activate

Install the required packages
pip install -r requirements.txt

requirements.txt content:
txt Flask 

4. Configuration (Important!)
Open app.py in a text editor and edit the following paths at the top of the file to match your system:

python

--- Path Configuration ---
BASE_DIR = Path(file).resolve().parent

IMPORTANT: Change this path to where you want to save your videos!
DOWNLOADS_DIR = Path("/media/devmon/T7/you")
CHANNELS_FILE = BASE_DIR / "channels.json"
DOWNLOAD_ARCHIVE_FILE = DOWNLOADS_DIR / "download_archive.txt"

OPTIONAL: Place a cookie file here to download private/age-restricted videos
COOKIE_FILE_PATH = BASE_DIR / "youtube_cookies.txt"


DOWNLOADS_DIR: This is the most important path. It must point to the directory (e.g., an external drive) where all videos will be stored. The application will create subdirectories for each channel here.

COOKIE_FILE_PATH (Optional): If you want to download age-restricted or private content, you need to export your YouTube cookies from your browser (e.g., using a browser extension like "Get cookies.txt") and save them in a file named youtube_cookies.txt in the project's root directory.

5. Run the Application
Once the configuration is complete, you can start the Flask server:

bash flask run --host=0.0.0.0 --port=5000 

The application will now be available at http://<your-server-ip>:5000.

For a more robust production setup, it is recommended to use a WSGI server such as Gunicorn or uWSGI.

How to Use the App
Search for a channel: Use the search bar in the top right ("Search YouTube...") to find a channel or video.

Add a channel: In the search results, find the desired channel and click the green Download (1080p) button. The channel will now be added to your list on the homepage, and the download process will start in the background.

Check the status: On the homepage, you can see the status of all your channels. Badges indicate if a download is "In Progress," "Completed," "Queued," or has failed.

Explore a channel: Click on a channel's name on the homepage to see a list of all the videos that have been downloaded from it.

Play a video: On the channel page, click the "Play" button next to a video to play it directly in your browser.

Download a single video: Use the "YouTube video URL..." field in the navigation bar to download a specific video. It will be saved in the correct channel folder.

Tech Stack
Backend: Python 3, Flask

Download Engine: yt-dlp

Frontend: HTML5, Bootstrap 5, Font Awesome, Jinja2

JavaScript: Vanilla JS for AJAX calls (search, start/stop downloads) and UI interactions.
