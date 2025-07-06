import os
import json
import subprocess
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, flash, redirect, url_for
from pathlib import Path
import logging
import shutil
import time
from threading import Lock, Timer
from urllib.parse import urlparse, parse_qs

# --- Logging Setup ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Sti Konfiguration ---
BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = Path("/media/devmon/T7/you")
CHANNELS_FILE = BASE_DIR / "channels.json"
DOWNLOAD_ARCHIVE_FILE = DOWNLOADS_DIR / "download_archive.txt"
COOKIE_FILE_PATH = BASE_DIR / "youtube_cookies.txt"

# --- Global Cache & Tasks ---
channel_video_cache = {}
cache_timestamps = {}
download_tasks = {} # Key: url, Value: {'status': str, 'process': Popen|None, 'thread': Thread|None, 'type': 'channel'|'single', 'name_hint': str, 'start_time': float}
download_lock = Lock()

# --- Globals for Periodic Update ---
UPDATE_INTERVAL_SECONDS = 3600 * 3
update_timer = None
update_lock = Lock()

# --- Sikre Download Mappe ---
try:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logging.info(f"Download mappe sikret/oprettet: {DOWNLOADS_DIR}")
except Exception as e:
    logging.error(f"FATAL: Kunne ikke oprette/tilgå download mappe {DOWNLOADS_DIR}: {e}", exc_info=True); exit(1)

# --- Hjælpefunktioner (load_channels_data, save_channels_data, get_channel_videos) ---
# UÆNDREDE
def load_channels_data():
    if not CHANNELS_FILE.exists(): return {}
    try:
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Fejl ved indlæsning af {CHANNELS_FILE}: {e}"); return {}
def save_channels_data(channels):
    try:
        with open(CHANNELS_FILE, 'w', encoding='utf-8') as f: json.dump(channels, f, indent=4, ensure_ascii=False)
    except IOError as e: logging.error(f"Fejl ved skrivning til {CHANNELS_FILE}: {e}")
def get_channel_videos(channel_id):
    channel_path = DOWNLOADS_DIR / channel_id; videos = []
    logging.debug(f"Optimeret check af videoer i: {channel_path}")
    if not channel_path.is_dir(): logging.warning(f"Kanalmappe findes ikke: {channel_path}"); return []
    try: all_files = list(channel_path.iterdir())
    except OSError as e: logging.error(f"I/O Fejl ved læsning af mappeindhold af {channel_path}: {e}"); return []
    video_file_map = {}; valid_video_suffixes = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv'}
    for item in all_files:
        if item.is_file() and item.suffix.lower() in valid_video_suffixes: video_file_map[item.stem] = item.name
    logging.debug(f"Fandt {len(video_file_map)} potentielle videofiler via optimeret scan.")
    for item in all_files:
        if item.is_file() and item.suffix == '.json' and item.name.endswith('.info.json'):
            try:
                with open(item, 'r', encoding='utf-8') as f: info = json.load(f)
                video_id = info.get('id')
                if not video_id:
                    if item.stem == channel_id: logging.debug(f"Ignorerer kanal-ID info-fil: {item.name}")
                    else: logging.warning(f"Mangler video ID i info-fil: {item}"); continue
                video_filename = video_file_map.get(video_id)
                if video_filename: videos.append({'id': video_id, 'title': info.get('title', 'Ukendt titel'), 'thumbnail': info.get('thumbnail'), 'upload_date': info.get('upload_date', '00000000'), 'filename': video_filename, 'channel_id': channel_id})
                else:
                    if item.stem != channel_id: logging.debug(f"Ingen videofil fundet i map for info: {item.name}")
            except (json.JSONDecodeError, IOError, KeyError) as e: logging.warning(f"Kunne ikke læse/parse info-fil {item}: {e}")
            except OSError as e: logging.error(f"I/O Fejl ved læsning af info-fil {item}: {e}"); continue
            except Exception as e: logging.error(f"Uventet fejl ved behandling af fil {item}: {e}", exc_info=True)
    videos.sort(key=lambda v: v.get('upload_date', '0'), reverse=True); logging.debug(f"Fandt {len(videos)} videoer for kanal {channel_id} efter optimeret check."); return videos

# --- run_yt_dlp_download med FORBEDRET thumbnail fallback ---
def run_yt_dlp_download(target_url, task_type, channel_id_hint=None, name_hint=None, video_id_hint=None):
    """Kører yt-dlp download for kanal/video - FAST 1080p MAKS."""
    global download_tasks, channel_video_cache, cache_timestamps, download_lock
    task_key = target_url
    effective_name = name_hint or task_key
    quality_desc = "1080p max"
    logging.info(f"Download tråd starter for {task_type} ({quality_desc}): {effective_name} ({task_key})")

    format_string = 'bestvideo[height<=?1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=?1080][ext=mp4]/best[height<=?1080]'
    logging.info(f"Bruger FAST formatstreng: {format_string}")

    if task_type == 'channel':
        output_path = DOWNLOADS_DIR / (channel_id_hint or "unknown_channel") / '%(id)s.%(ext)s'
        final_channel_id = channel_id_hint
    elif task_type == 'single' and channel_id_hint and video_id_hint:
        output_path = DOWNLOADS_DIR / channel_id_hint / f'{video_id_hint}.%(ext)s'
        final_channel_id = channel_id_hint
    else:
        logging.error(f"Ugyldig kombination for enkelt video: channel_id={channel_id_hint}, video_id={video_id_hint}")
        output_path = DOWNLOADS_DIR / "singles" / '%(id)s.%(ext)s'
        final_channel_id = None
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = ['yt-dlp', '--no-warnings', '--ignore-errors', '--download-archive', str(DOWNLOAD_ARCHIVE_FILE), '--write-info-json', '-f', format_string, '--restrict-filenames', '-o', str(output_path), '-N', '8', '--sleep-interval', '10', '--max-sleep-interval', '30']
    if COOKIE_FILE_PATH.is_file(): logging.info(f"Bruger cookie-fil: {COOKIE_FILE_PATH}"); command.extend(['--cookies', str(COOKIE_FILE_PATH)])
    else: logging.warning(f"Cookie-fil IKKE fundet: {COOKIE_FILE_PATH}")
    command.append(target_url)

    logging.info(f"Kører kommando: {' '.join(command)}")
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        with download_lock:
            if task_key in download_tasks: download_tasks[task_key]['process'] = process; download_tasks[task_key]['status'] = f"I gang ({quality_desc}): {effective_name}"
            else: download_tasks[task_key] = {'status': f"I gang ({quality_desc}): {effective_name}", 'process': process, 'thread': threading.current_thread(), 'type': task_type, 'name_hint': name_hint, 'start_time': time.time()}
        logging.debug(f"Venter på yt-dlp ({task_type}) proces for {task_key}..."); stdout, stderr = process.communicate(); logging.debug(f"yt-dlp ({task_type}) proces for {task_key} afsluttet med kode: {process.returncode}")
        if stderr: logging.info(f"[yt-dlp stderr][{task_key}]:\n{stderr[:1000]}...")

        if process.returncode == 0: # SUCCES
            status_msg = f"Færdig ({quality_desc}): {effective_name}"
            if final_channel_id: # Ryd cache
                if final_channel_id in channel_video_cache: del channel_video_cache[final_channel_id]; logging.info(f"Cache ryddet for {final_channel_id}.")
                if final_channel_id in cache_timestamps: del cache_timestamps[final_channel_id]
            logging.info(f"Download ({task_type}, {quality_desc}) for {task_key} fuldført.")

            # --- FORBEDRET LOGIK TIL OPDATERING AF KANALINFO ---
            if task_type == 'channel' and final_channel_id:
                 channels = load_channels_data()
                 channel_updated = False
                 if final_channel_id in channels:
                     # Opdater navn hvis det mangler
                     current_name = channels[final_channel_id].get('name')
                     if (not current_name or current_name == f"Kanal {final_channel_id}") and name_hint:
                         channels[final_channel_id]['name'] = name_hint
                         logging.info(f"Opdaterede kanalnavn for {final_channel_id} til '{name_hint}'.")
                         channel_updated = True

                     # Opdater thumbnail hvis det mangler (None eller tom streng)
                     if not channels[final_channel_id].get('thumbnail'):
                         logging.info(f"Thumbnail mangler for {final_channel_id}. Søger i .info.json...")
                         found_thumbnail = None
                         try:
                             # Gennemgå alle .info.json filer i mappen
                             info_files_path = DOWNLOADS_DIR / final_channel_id
                             if info_files_path.is_dir():
                                 for info_file in info_files_path.glob('*.info.json'):
                                     if info_file.stem == final_channel_id: continue # Spring over 'kanal_id.info.json'
                                     try:
                                         with open(info_file, 'r', encoding='utf-8') as f: info_data = json.load(f)
                                         thumbnail_url = info_data.get('thumbnail')
                                         if thumbnail_url: # Fandt en URL
                                             found_thumbnail = thumbnail_url
                                             logging.info(f"Fandt thumbnail '{found_thumbnail}' i {info_file.name}.")
                                             break # Brug den første vi finder
                                     except Exception as e_inner: logging.warning(f"Kunne ikke læse/parse {info_file.name}: {e_inner}")
                             else:
                                  logging.warning(f"Kanalmappe {info_files_path} findes ikke til thumbnail søgning.")
                         except Exception as e_outer: logging.error(f"Fejl ved søgning efter info filer for {final_channel_id}: {e_outer}")

                         if found_thumbnail:
                             channels[final_channel_id]['thumbnail'] = found_thumbnail
                             channel_updated = True
                             logging.info(f"Opdaterede thumbnail for {final_channel_id}.")
                         else:
                             logging.warning(f"Kunne IKKE finde thumbnail for {final_channel_id} i nogen .info.json fil.")

                     # Gem kun hvis der var ændringer
                     if channel_updated:
                         save_channels_data(channels)
            # --- SLUT FORBEDRET LOGIK ---

        else: # FEJL
            stderr_lower = stderr.lower()
            if "sign in to confirm" in stderr_lower or "authentication" in stderr_lower: status_msg = f"Login påkrævet ({quality_desc}): Fejl for {effective_name}"; logging.error(f"DL Fejl (Login): {task_key}. Opdatér cookies. Kode: {process.returncode}")
            elif "rate-limited" in stderr_lower: status_msg = f"Rate Limited ({quality_desc}): DL pauset for {effective_name}"; logging.warning(f"DL Fejl (Rate Limit): {task_key}. Kode: {process.returncode}")
            else: status_msg = f"Fejl ({quality_desc}) for {effective_name} (kode: {process.returncode})"; logging.error(f"DL Fejl (Ukendt): {task_key}. Kode: {process.returncode}"); logging.error(f"stderr:\n{stderr}")

    except FileNotFoundError: status_msg = "Fejl: yt-dlp ikke fundet."; logging.error(f"FATAL FEJL: 'yt-dlp' ikke fundet.", exc_info=True)
    except Exception as e: status_msg = f"Kritisk fejl ({quality_desc}) for {effective_name}."; logging.error(f"Uventet undtagelse under DL for {task_key}: {e}", exc_info=True)
    finally: # Ryd op
        with download_lock:
            if task_key in download_tasks: download_tasks[task_key]['process'] = None; download_tasks[task_key]['status'] = status_msg; download_tasks[task_key]['thread'] = None; logging.debug(f"DL task afsluttet for {task_key}. Status: {status_msg}")
            else: logging.warning(f"Task key {task_key} ikke fundet ved afslutning.")


# --- Periodisk Opdatering Funktioner ---
def check_and_update_all_channels():
    global update_lock, download_tasks
    if not update_lock.acquire(blocking=False): logging.info("Periodisk opdatering sprunget over: Aktiv."); schedule_next_update(); return
    try:
        logging.info("Starter periodisk opdateringstjek (1080p max)..."); channels = load_channels_data(); channels_triggered = 0
        for channel_id, data in channels.items():
            channel_url = data.get('url'); channel_name = data.get('name', channel_id)
            if not channel_url: logging.warning(f"Skipping channel {channel_id}: Mangler URL."); continue
            task_key = channel_url
            with download_lock: current_task = download_tasks.get(task_key); is_active = current_task and current_task.get('process') is not None
            if is_active: logging.debug(f"Skipping auto-update for {channel_name}: Aktiv.")
            else:
                logging.info(f"Trigger automatisk opdatering for: {channel_name} ({channel_id})")
                with download_lock: download_tasks[task_key] = {'status': f"Auto-tjek startet: {channel_name}", 'process': None, 'thread': None, 'type': 'channel', 'name_hint': channel_name, 'start_time': time.time()}
                thread = threading.Thread(target=run_yt_dlp_download, args=(channel_url, 'channel', channel_id, channel_name), daemon=True) # Ingen quality param her
                with download_lock:
                     if task_key in download_tasks: download_tasks[task_key]['thread'] = thread
                thread.start()
                channels_triggered += 1; time.sleep(1)
        logging.info(f"Periodisk opdatering færdig. Startede {channels_triggered} kanal-opdateringer.")
    except Exception as e: logging.error(f"Fejl under periodisk opdatering: {e}", exc_info=True)
    finally: update_lock.release(); logging.debug("Update lock frigivet."); schedule_next_update()

def schedule_next_update():
    global update_timer
    if update_timer: update_timer.cancel()
    update_timer = Timer(UPDATE_INTERVAL_SECONDS, check_and_update_all_channels); update_timer.daemon = True; update_timer.start()
    logging.info(f"Næste auto kanalopdatering planlagt om {UPDATE_INTERVAL_SECONDS / 60:.1f} minutter.")

# --- Flask Routes ---
# (/, search_youtube, download_channel, stop_download, download_single, view_channel, serve_video, search_local)
# Funktionerne er UÆNDREDE fra den allersidste version i dit tidligere svar,
# bortset fra at kald til run_yt_dlp_download nu ikke sender quality param.
# Indsæt de uændrede routes her...

@app.route('/')
def index():
    channels_data = load_channels_data(); channels_list = []; total_videos_count_overall = 0
    for cid, data in channels_data.items():
        with download_lock: task = download_tasks.get(data.get('url'))
        data_copy = data.copy(); data_copy['task'] = task
        channel_path = DOWNLOADS_DIR / cid; video_count = 0; data_copy['error_reading'] = False
        if channel_path.is_dir():
            try: video_count = sum(1 for item in channel_path.iterdir() if item.is_file() and item.suffix.lower() in ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv']); total_videos_count_overall += video_count
            except OSError as e: logging.error(f"Kunne ikke læse {channel_path}: {e}"); data_copy['error_reading'] = True
        data_copy['video_count'] = video_count; channels_list.append(data_copy)
    channels_list.sort(key=lambda c: c.get('name', '').lower())
    disk_total_gb = disk_used_gb = disk_free_gb = percent_used = 'N/A'
    try:
        usage = shutil.disk_usage(DOWNLOADS_DIR); bytes_in_gb = 1024**3
        disk_total_gb = round(usage.total / bytes_in_gb, 1); disk_used_gb = round(usage.used / bytes_in_gb, 1); disk_free_gb = round(usage.free / bytes_in_gb, 1)
        if disk_total_gb > 0: percent_used = round((disk_used_gb / disk_total_gb) * 100)
        else: percent_used = 0
        logging.debug(f"Disk Usage ({DOWNLOADS_DIR}): Total={disk_total_gb}GB, Used={disk_used_gb}GB, Free={disk_free_gb}GB")
    except Exception as e: logging.error(f"Fejl ved diskpladsberegning: {e}", exc_info=True)
    with download_lock: single_tasks = {k: v for k, v in download_tasks.items() if v.get('type') == 'single'}
    return render_template('index.html', channels=channels_list, total_videos=total_videos_count_overall, disk_total=disk_total_gb, disk_used=disk_used_gb, disk_free=disk_free_gb, disk_percent_used=percent_used, single_tasks=single_tasks)

@app.route('/search_youtube')
def search_youtube():
    query = request.args.get('query', '').strip(); html_response = '<p class="text-danger">Ukendt fejl.</p>'
    if not query: logging.warning("Tom søgeforespørgsel."); return '<p class="text-warning">Indtast søgning.</p>'
    logging.info(f"YouTube søgning: '{query}'"); search_query = f"ytsearch10:{query}"
    command = ['yt-dlp', '--dump-json', '--flat-playlist', '--skip-download', '--no-warnings', '--match-filter', '!is_live', search_query]
    logging.debug(f"Kommando: {' '.join(command)}"); results = []; process = None
    try:
        logging.debug(f"Starter Popen for: {command}"); process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        logging.debug(f"Venter på communicate() for '{query}'..."); stdout, stderr = process.communicate(timeout=60); logging.debug(f"communicate() afsluttet for '{query}'. Kode: {process.returncode}")
        if stderr: logging.info(f"yt-dlp stderr for '{query}':\n{stderr[:500]}...")
        if process.returncode == 0:
            logging.debug(f"yt-dlp succes for '{query}'. Behandler stdout.")
            if not stdout: logging.warning(f"yt-dlp returkode 0, men tom stdout for '{query}'."); html_response = '<p class="text-muted">Ingen resultater fundet.</p>'
            else:
                logging.debug(f"Parsing stdout: {stdout[:500]}..."); lines = stdout.strip().split('\n')
                for i, line in enumerate(lines):
                    if not line: continue
                    try:
                        data = json.loads(line); logging.debug(f"Linje {i+1} parset.")
                        if data.get('id'): results.append({'id': data.get('id'), 'title': data.get('title', 'Ukendt Titel'), 'thumbnail': data.get('thumbnail'), 'url': data.get('webpage_url'), 'channel_id': data.get('channel_id'), 'channel_name': data.get('channel'), 'channel_url': data.get('channel_url'), 'type': 'video', 'proxy_thumbnail': data.get('thumbnail')}); logging.debug(f"Linje {i+1}: Gyldigt resultat (ID: {data.get('id')}).")
                        else: logging.debug(f"Linje {i+1}: Springes over (mangler ID).")
                    except json.JSONDecodeError as json_err: logging.error(f"JSON Fejl linje {i+1} for '{query}': {json_err}\nLinje: {line}")
                logging.info(f"Fandt {len(results)} gyldige videoresultater for '{query}'.");
                if not results: html_response = '<p class="text-muted">Ingen gyldige resultater fundet.</p>'
                else: html_response = render_template('_search_results.html', results=results)
        else: logging.error(f"yt-dlp søgning fejlede for '{query}' (kode {process.returncode}). stderr:\n{stderr}"); html_response = f'<p class="text-danger">yt-dlp søgning fejlede (kode {process.returncode}). Tjek logs.</p><pre>{stderr}</pre>'
    except subprocess.TimeoutExpired:
        logging.error(f"yt-dlp søgning timed out (>60s) for '{query}'.");
        if process:
            try: process.kill(); logging.debug(f"Popen process for '{query}' killed after timeout.")
            except Exception as kill_err: logging.error(f"Fejl ved kill efter timeout: {kill_err}")
        html_response = '<p class="text-danger">Søgning timed out.</p>'
    except FileNotFoundError: logging.error("FATAL FEJL: 'yt-dlp' kommando ikke fundet.", exc_info=True); html_response = '<p class="text-danger">Fejl: yt-dlp ikke fundet.</p>'
    except Exception as e: logging.error(f"Uventet fejl under yt-dlp søgning for '{query}': {e}", exc_info=True); html_response = f'<p class="text-danger">Intern serverfejl. Tjek logs.</p><pre>{e}</pre>'
    return html_response

@app.route('/download_channel', methods=['POST'])
def download_channel():
    channel_url = request.form.get('channel_url'); channel_id = request.form.get('channel_id'); channel_name = request.form.get('channel_name'); channel_thumbnail = request.form.get('channel_thumbnail')
    if not channel_url or not channel_id: logging.warning("Download kanal forsøgt uden url/id."); return jsonify({"error": "Mangler channel_url/id"}), 400
    task_key = channel_url
    with download_lock: current_task = download_tasks.get(task_key); is_active = current_task and current_task.get('process') is not None
    if is_active: logging.info(f"Download for {channel_id} er allerede aktiv."); return jsonify({"message": f"Download for {channel_name or channel_id} kører allerede.", "status": "running"}), 202
    channels = load_channels_data(); new_channel = channel_id not in channels
    if new_channel: channels[channel_id] = {"id": channel_id, "name": channel_name or channel_id, "url": channel_url, "thumbnail": channel_thumbnail or None}; logging.info(f"Tilføjer ny kanal: {channel_id} - {channel_name or channel_id}")
    else:
        if not channels[channel_id].get('name') and channel_name: channels[channel_id]['name'] = channel_name
        if not channels[channel_id].get('thumbnail') and channel_thumbnail: channels[channel_id]['thumbnail'] = channel_thumbnail
        channels[channel_id]['url'] = channel_url; logging.info(f"Genstarter/køsætter DL for eksisterende kanal: {channel_id}")
    save_channels_data(channels);
    logging.info(f"Starter download tråd for kanal (1080p max): {channel_name or channel_id} ({channel_id})")
    thread = threading.Thread(target=run_yt_dlp_download, args=(channel_url, 'channel', channel_id, channel_name), daemon=True)
    with download_lock: download_tasks[task_key] = {'status': f"Sat i kø (1080p): {channel_name or channel_id}", 'process': None, 'thread': thread, 'type': 'channel', 'name_hint': channel_name, 'start_time': time.time()}
    thread.start()
    return jsonify({"message": f"Download (1080p max) af '{channel_name or channel_id}' sat i kø.", "status": "started"}), 202

@app.route('/stop_download', methods=['POST'])
def stop_download():
    url_to_stop = request.form.get('url')
    if not url_to_stop: return jsonify({"error": "Mangler URL at stoppe"}), 400
    logging.info(f"Modtaget stop anmodning for: {url_to_stop}"); stopped = False; message = "Download ikke fundet eller kører ikke."
    with download_lock:
        task = download_tasks.get(url_to_stop)
        if task and task.get('process'):
            proc = task['process']; name = task.get('name_hint', url_to_stop)
            logging.warning(f"Forsøger at stoppe process {proc.pid} for {name}...");
            try: proc.terminate(); task['status'] = f"Stopper... {name}"; stopped = True; message = f"Stop-signal sendt til {name}."
            except ProcessLookupError: logging.warning(f"Process {proc.pid} for {name} væk."); task['process'] = None; task['status'] = f"Stoppet (proces væk): {name}"; message = f"DL for {name} var stoppet."; stopped = True
            except Exception as e: logging.error(f"Fejl ved stop af process {proc.pid}: {e}", exc_info=True); message = f"Fejl ved stop: {e}"; task['status'] = f"Fejl ved stop: {name}"
        elif task: message = f"Download for {task.get('name_hint', url_to_stop)} kører ikke."
        else: message = f"Ingen task fundet for URL: {url_to_stop}"
    return jsonify({"message": message, "stopped": stopped}), 200 if stopped else 404

@app.route('/download_single', methods=['POST'])
def download_single():
    video_url = request.form.get('video_url', '').strip()
    if not video_url: flash("Du skal angive en video URL.", "warning"); return redirect(url_for('index'))
    logging.info(f"Modtaget enkelt video download (1080p max): {video_url}")
    task_key = video_url
    with download_lock: current_task = download_tasks.get(task_key); is_active = current_task and current_task.get('process') is not None
    if is_active: flash(f"Download for denne video kører allerede ({current_task['status']}).", "info"); return redirect(url_for('index'))
    logging.debug(f"Henter video/kanal info for: {video_url}")
    command_info = ['yt-dlp', '--no-warnings', '--print', '%(channel_id)s;%(id)s;%(title)s', '--skip-download', video_url]
    channel_id = None; video_id = None; video_title = video_url
    try:
        process_info = subprocess.Popen(command_info, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        stdout_info, stderr_info = process_info.communicate(timeout=20)
        if process_info.returncode == 0 and stdout_info:
            parts = stdout_info.strip().split(';', 2)
            if len(parts) >= 2: channel_id = parts[0] if parts[0] != 'NA' else None; video_id = parts[1] if parts[1] != 'NA' else None;
            if len(parts) > 2: video_title = parts[2]
            logging.info(f"Info hentet: KanalID={channel_id}, VideoID={video_id}, Titel={video_title}")
        else: logging.error(f"Kunne ikke hente info for {video_url}. Kode: {process_info.returncode}"); logging.error(f"yt-dlp info stderr: {stderr_info}"); flash(f"Kunne ikke hente info. Fejl: {stderr_info}", "danger"); return redirect(url_for('index'))
    except Exception as e: logging.error(f"Fejl ved hentning af info for {video_url}: {e}", exc_info=True); flash(f"Fejl ved hentning af info: {e}", "danger"); return redirect(url_for('index'))
    if not channel_id or not video_id: flash(f"Kunne ikke bestemme kanal/video ID. Kan ikke gemme korrekt.", "danger"); return redirect(url_for('index'))
    channels = load_channels_data()
    if channel_id not in channels: channels[channel_id] = {"id": channel_id, "name": f"Kanal {channel_id}", "url": None, "thumbnail": None}; save_channels_data(channels); logging.info(f"Tilføjet midlertidig kanal info for {channel_id}")
    logging.info(f"Starter download tråd for enkelt video (1080p max): {video_title} ({video_id}) i kanal {channel_id}")
    thread = threading.Thread(target=run_yt_dlp_download, args=(video_url, 'single', channel_id, video_title, video_id), daemon=True)
    with download_lock: download_tasks[task_key] = {'status': f"Sat i kø (1080p): {video_title}", 'process': None, 'thread': thread, 'type': 'single', 'name_hint': video_title, 'start_time': time.time()}
    thread.start()
    flash(f"Download (1080p max) af '{video_title}' er sat i kø.", "success")
    return redirect(url_for('index'))

@app.route('/channel/<channel_id>')
def view_channel(channel_id):
    global channel_video_cache, cache_timestamps
    channels = load_channels_data(); channel_info = channels.get(channel_id)
    if not channel_info: logging.warning(f"Ukendt kanal ID: {channel_id}"); abort(404, f"Kanal ID '{channel_id}' ikke registreret.")
    channel_url = channel_info.get('url');
    with download_lock: task = download_tasks.get(channel_url) if channel_url else None
    channel_info['task'] = task
    channel_path = DOWNLOADS_DIR / channel_id; videos = None; cache_status = "Miss"; cache_hit = False
    cached_videos = channel_video_cache.get(channel_id); cached_timestamp = cache_timestamps.get(channel_id)
    if cached_videos is not None and cached_timestamp is not None:
        try:
            dir_mtime = channel_path.stat().st_mtime
            if dir_mtime <= cached_timestamp: videos = cached_videos; cache_status = f"Hit (Valid @ {time.strftime('%H:%M:%S', time.localtime(cached_timestamp))})"; cache_hit = True; logging.info(f"Cache hit for {channel_id}.")
            else: cache_status = f"Hit (Stale)"; logging.info(f"Cache for {channel_id} forældet. Henter frisk."); videos = None; del channel_video_cache[channel_id]; del cache_timestamps[channel_id]
        except (FileNotFoundError, OSError) as e: logging.error(f"Fejl ved cache check for {channel_path}: {e}. Rydder cache."); cache_status = "Miss (Stat/FNF Error)"; videos = None;
        if videos is None and channel_id in channel_video_cache: del channel_video_cache[channel_id];
        if videos is None and channel_id in cache_timestamps: del cache_timestamps[channel_id]
    if videos is None:
        logging.info(f"Henter video liste fra disk for {channel_id} ({cache_status})..."); videos = get_channel_videos(channel_id)
        if videos is not None: channel_video_cache[channel_id] = videos; cache_timestamps[channel_id] = time.time(); cache_status += f" -> Cached @ {time.strftime('%H:%M:%S', time.localtime(cache_timestamps[channel_id]))}"; logging.info(f"Liste for {channel_id} ({len(videos)}) gemt/opdateret i cache.")
        else: logging.error(f"Kunne ikke hente liste for {channel_id} til cache."); videos = []; cache_status += " -> Failed fetch"
    if not channel_path.is_dir(): channel_info.setdefault('warning', "Mappe ikke fundet.")
    elif not videos:
        current_status_str = task['status'] if task else ''; current_status = current_status_str.lower()
        if any(s in current_status for s in ["i gang", "i kø", "starter"]): channel_info.setdefault('warning', "DL i gang, ingen videoer færdige.")
        elif "rate limited" in current_status: channel_info.setdefault('warning', "DL pauset (Rate Limited).")
        elif "login påkrævet" in current_status: channel_info.setdefault('warning', "DL fejlede (Login påkrævet).")
        elif "færdig" in current_status: channel_info.setdefault('warning', "DL færdig, ingen videoer fundet.")
        elif "fejl" in current_status: channel_info.setdefault('warning', "DL fejlede tidligere.")
        else: channel_info.setdefault('warning', "Ingen videoer fundet.")
    return render_template('channel.html', channel=channel_info, videos=videos, download_tasks=download_tasks, cache_status=cache_status, cache_hit=cache_hit)

@app.route('/downloads/<path:filepath>')
def serve_video(filepath):
    logging.debug(f"Forsøger at servere fil: {filepath}")
    try:
        absolute_path = DOWNLOADS_DIR.resolve().joinpath(filepath).resolve(); absolute_path.relative_to(DOWNLOADS_DIR.resolve())
        if not absolute_path.is_file(): logging.warning(f"Fil ikke fundet: {absolute_path}"); abort(404)
        directory = absolute_path.parent; filename = absolute_path.name; logging.info(f"Serverer: {filename} fra {directory}"); return send_from_directory(directory, filename, as_attachment=False)
    except ValueError: logging.error(f"Sikkerhedsfejl - Ugyldig sti: {filepath}"); abort(403)
    except FileNotFoundError: logging.warning(f"Fil ikke fundet ved send: {filepath}"); abort(404)
    except Exception as e: logging.error(f"Fejl ved servering af {filepath}: {e}", exc_info=True); abort(500)

@app.route('/search_local')
def search_local():
    query = request.args.get('query', '').lower().strip(); matching_videos = []
    if not query: return jsonify([])
    logging.info(f"Lokal søgning: '{query}'"); channels = load_channels_data()
    for channel_id, channel_data in channels.items():
        videos_in_channel = None;
        if channel_id in channel_video_cache: videos_in_channel = channel_video_cache[channel_id]; logging.debug(f"Lokal søgning: Cache hit for {channel_id}")
        else:
            videos_in_channel = get_channel_videos(channel_id)
            if videos_in_channel is not None: channel_video_cache[channel_id] = videos_in_channel; cache_timestamps[channel_id] = time.time()
        if videos_in_channel:
            for video in videos_in_channel:
                if query in video.get('title', '').lower(): video_copy = video.copy(); video_copy['channel_name'] = channel_data.get('name', channel_id); matching_videos.append(video_copy)
    matching_videos.sort(key=lambda v: v.get('title', '').lower()); logging.info(f"Lokal søgning fandt {len(matching_videos)} for '{query}'."); return jsonify(matching_videos)


if __name__ == '__main__':
    print("--- YT Downloader ---")
    is_debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ['1', 'true', 't']
    print(f"Flask Debug Mode: {is_debug_mode}")
    print(f"Download mappe: {DOWNLOADS_DIR}")
    print(f"Kanal datafil: {CHANNELS_FILE}")
    print(f"Download arkiv: {DOWNLOAD_ARCHIVE_FILE}")
    print(f"Cookie fil: {COOKIE_FILE_PATH} (Eksisterer: {COOKIE_FILE_PATH.is_file()})")
    print(f"Web interface kører på: http://0.0.0.0:5000")
    if not is_debug_mode or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        initial_delay = 10
        print(f"Starter automatisk opdateringstjek om {initial_delay} sekunder...")
        def start_initial_timer(): global update_timer; update_timer = Timer(initial_delay, check_and_update_all_channels); update_timer.daemon = True; update_timer.start()
        timer_thread = threading.Thread(target=start_initial_timer, daemon=True); timer_thread.start()
    else: print("Skipping auto update timer start i reloader process.")
    app.run(debug=is_debug_mode, host='0.0.0.0', port=5000, threaded=True)
