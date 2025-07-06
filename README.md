# YT Channel Downloader

YT Channel Downloader is a self-hosted web application built with Flask, designed to automate the download and archiving of entire YouTube channels. It acts as a user-friendly graphical user interface (GUI) on top of the powerful command-line tool `yt-dlp`.

The application allows you to search for channels, add them to a download queue, automatically fetch new videos periodically, and watch your downloaded content directly in the browser via an integrated video player.

## Key Features

-   **Web-based User Interface**: Manage all your downloads from a clean web interface, accessible from your local network.
-   **Channel-based Downloads**: Add an entire YouTube channel, and the system will download all of its videos.
-   **Automatic Updates**: The server periodically checks for new videos on your added channels and downloads them automatically.
-   **Single Video Downloads**: Paste a link to a single YouTube video to download it quickly.
-   **Integrated Search**: Search YouTube directly from the application to easily find and add new channels.
-   **Local Search**: Instantly search the titles of all your already-downloaded videos.
-   **Built-in Video Player**: Play your downloaded videos directly in the browser without leaving the page.
-   **Status Dashboard**: Get a clear overview of disk space, ongoing downloads, and the status of each channel (e.g., "In Progress," "Completed," "Error").
-   **Cookie Support**: Option to use a cookie file to download videos that require a login (e.g., age-restricted).

## Screenshots

*(Replace with links to your own screenshots for the best effect)*

**Homepage / Dashboard:**
*Shows a list of all tracked channels, their status, and a disk space overview.*
![Dashboard](https://i.imgur.com/placeholder.png "Dashboard with channel overview")

**Channel Details & Video Player:**
*Shows all downloaded videos for a specific channel, with the video player active at the top.*
![Channel Page](https://i.imgur.com/placeholder.png "Channel page with video player")

**YouTube Search Results:**
*Shows results from a YouTube search, ready to be added to the download queue.*
![Search Results](https://i.imgur.com/placeholder.png "YouTube search results in the app")

## Installation & Setup

### 1. Prerequisites

Before you begin, ensure you have the following installed on your server/computer:

-   **Python 3.8+**
-   **pip** (Python package installer)
-   **yt-dlp**: It is *crucial* that `yt-dlp` is installed and available in the system's `PATH`.
    -   Installation Guide: [yt-dlp GitHub](https://github.com/yt-dlp/yt-dlp#installation)

### 2. Clone the project

```bash
git clone <your-repository-url>
cd <project-folder>
