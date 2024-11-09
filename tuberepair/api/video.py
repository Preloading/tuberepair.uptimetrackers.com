import math
from pathlib import Path
import subprocess
import threading

import requests
import time
from modules import get, helpers
from flask import Blueprint, Flask, abort, request, redirect, render_template, Response, send_file
import config
from modules.logs import print_with_seperator
from modules import yt

video = Blueprint("video", __name__)

CACHE_DIR = './cache/videos'
SEGMENT_DURATION = 10  # Duration of each HLS segment in seconds
INITIAL_SEGMENTS = 3   # Number of segments to encode initially
FUTURE_SEGMENTS = 2    # Number of future segments to encode after each request

def error():
    return "",404

# featured videos
# 2 alternate routes for popular page and search results
@video.route("/feeds/api/standardfeeds/<regioncode>/<popular>")
@video.route("/feeds/api/standardfeeds/<popular>")
@video.route("/<int:res>/feeds/api/standardfeeds/<regioncode>/<popular>")
@video.route("/<int:res>/feeds/api/standardfeeds/<popular>")
def frontpage(regioncode="US", popular=None, res=''):

    # Clamp Res
    if type(res) == int:
        res = min(max(res, 144), config.RESMAX)

    url = request.url_root + str(res) 
    # trending videos categories
    # the menu got less because of youtube removing it.
    apiurl = config.URL + "/api/v1/trending?region=" + regioncode
    if popular == "most_popular_Film":
        apiurl = f"{config.URL}/api/v1/trending?type=Movies&region={regioncode}"
    if popular == "most_popular_Games":
        apiurl = f"{config.URL}/api/v1/trending?type=Gaming&region={regioncode}"
    if popular == "most_popular_Music":
        apiurl = f"{config.URL}/api/v1/trending?type=Music&region={regioncode}"    

    # fetch api from invidious
    data = get.fetch(apiurl)

    # Will be used for checking Classic
    user_agent = request.headers.get('User-Agent').lower()
    
    # Templates have the / at the end, so let's remove it.
    if url[-1] == '/':
        url = url[:-1]

    if data:

        # print logs if enabled
        if config.SPYING == True:
            print_with_seperator("Region code: " + regioncode)

        # Classic YT path
        if "youtube/1.0.0" in user_agent or "youtube v1.0.0" in user_agent:
            # get template
            return get.template('classic/featured.jinja2',{
                'data': data[:15],
                'unix': get.unix,
                'url': url
            })
        
        # Google YT
        return get.template('featured.jinja2',{
            'data': data[:config.FEATURED_VIDEOS],
            'unix': get.unix,
            'url': url
        })

    return error()

# search for videos
@video.route("/feeds/api/videos")
@video.route("/feeds/api/videos/")
@video.route("/<int:res>/feeds/api/videos")
@video.route("/<int:res>/feeds/api/videos/")
def search_videos(res=''):

    # Clamp Res
    if type(res) == int:
        res = min(max(res, 144), config.RESMAX)
    
    url = request.url_root + str(res)
    currentPage, next_page = helpers.process_start_index(request)

    user_agent = request.headers.get('User-Agent').lower()

    search_keyword = request.args.get('q')

    if not search_keyword:
        return error()
    
    # print logs if enabled
    if config.SPYING == True:
        print_with_seperator('Searched: ' + search_keyword)

    # remove space character
    search_keyword = search_keyword.replace(" ", "%20")

    # q and page is already made, so lets hand add it
    query = f'q={search_keyword}&type=video&page={currentPage}'
    
    # If we have orderby, turn it into invidious friendly parameters
    # Else ignore it
    orderby = request.args.get('orderby')
    if orderby in helpers.valid_search_orderby:
        query += f'&sort={helpers.valid_search_orderby[orderby]}'

    # If we have time, turn it into invidious friendly parameters
    # Else ignore it
    time = request.args.get('time')
    if time in helpers.valid_search_time:
        query += f'&date={helpers.valid_search_time[time]}'

    # If we have duration, turn it into invidious friendly parameters
    # Else ignore it
    duration = request.args.get('duration')
    if duration in helpers.valid_search_duration:
        query += f'&duration={helpers.valid_search_duration[duration]}'
    
    # If we have captions, turn it into invidious friendly parameters
    # Else ignore it
    # NOTE: YouTube 1.1.0 app only supports subtitles in the search
    caption = request.args.get('caption')
    if type(caption) == str and caption.lower() == 'true':
        query += '&features=subtitles'

    # Santize and stitch 
    query = query.replace('&', '&amp;')

    # search by videos
    data = get.fetch(f"{config.URL}/api/v1/search?{query}")
    # Templates have the / at the end, so let's remove it.
    if url[-1] == '/':
        url = url[:-1]

    if not data:
        next_page = None

    # classic tube check
    if "youtube/1.0.0" in user_agent or "youtube v1.0.0" in user_agent:
        return get.template('classic/search.jinja2',{
            'data': data,
            'unix': get.unix,
            'url': url,
            'next_page': next_page
        })
    else:
        return get.template('search_results.jinja2',{
            'data': data,
            'unix': get.unix,
            'url': url,
            'next_page': next_page
        })

    #return error()

# video's comments
# IDEA: filter the comments too?
@video.route("/api/videos/<videoid>/comments")
@video.route("/<int:res>/api/videos/<videoid>/comments")
def comments(videoid, res=''):
    
    # Clamp Res
    if type(res) == int:
        res = min(max(res, 144), config.RESMAX)
    
    url = request.url_root + str(res) 

    continuation_token = request.args.get('continuation') and '&amp;continuation=' + request.args.get('continuation') or ''
    # fetch invidious comments api
    data = get.fetch(f"{config.URL}/api/v1/comments/{videoid}?sortby={config.SORT_COMMENTS}{continuation_token}")

    # Templates have the / at the end, so let's remove it.
    if url[-1] == '/':
        url = url[:-1]
    if data:
        # NOTE: No comments sometimes returns {'error': 'Comments not found.'}
        if 'error' in data:
            comments = None
        else:
            comments = data['comments']
        return get.template('comments.jinja2',{
            'data': comments,
            'unix': get.unix,
            'url': url,
            'continuation': 'continuation' in data and data['continuation'] or None,
            'video_id': videoid
        })

    return error()
    
# fetches video from innertube.
@video.route("/getvideo/<video_id>")
@video.route("/<int:res>/getvideo/<video_id>")
def getvideo(video_id, res=360):
    # if res is not None or config.MEDIUM_QUALITY is False:
        
    #     # Clamp Res
    #     if type(res) == int:
    #         res = min(max(res, 144), config.RESMAX)
    
    #     # Set mimetype since videole device don't recognized it.
    #     return Response(yt.hls_video_url(video_id, res), mimetype="application/vnd.apple.mpegurl")
    
    # # 360p if enabled
    # return redirect(yt.medium_quality_video_url(video_id), 307)
    # sanity_check_path = Path(CACHE_DIR) / "helpme.3gp"
    # return send_file(sanity_check_path, as_attachment=True, mimetype="video/3gpp")
    # with open(playlist_path, 'r') as file:
    #         return Response(file.read(), mimetype="video/3gpp")
    return redirect(f"/video/{video_id}/{res}/play.m3u8", 307)

def download_youtube_video(video_id):
    """
    Download YouTube video using yt.medium_quality_video_url and save it as 'original.mp4' in the cache.
    """
    input_path = Path(CACHE_DIR) / video_id / "original.mp4"
    input_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        video_url = yt.medium_quality_video_url(video_id)
        print(f"Downloading video from: {video_url}")

        response = requests.get(video_url, stream=True)
        with open(input_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    return input_path

def get_video_length(video_path):
    """
    Get the length of the video in seconds.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True,
        text=True
    )
    return float(result.stdout.strip())

def create_master_playlist(video_id, resolution, total_segments, video_length):
    """
    Create a placeholder master playlist with the expected number of segments.
    """
    output_dir = Path(CACHE_DIR) / video_id / resolution
    playlist_path = output_dir / "master.m3u8"
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(playlist_path, 'w') as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION}\n")
        f.write("#EXT-X-PLAYLIST-TYPE:VOD\n")
        f.write(f"#EXT-X-MEDIA-SEQUENCE:0\n")
        #f.write("#EXT-X-INDEPENDENT-SEGMENTS\n")

        # List all segments expected for the video duration
        for segment in range(total_segments-1):
            #f.write("#EXT-X-DISCONTINUITY\n")
            f.write(f"#EXTINF:{format(SEGMENT_DURATION, '.3f')},\n")
            f.write(f"{segment}.ts\n")

        #Special case for the last segment
        f.write(f"#EXTINF:{format(video_length % SEGMENT_DURATION, '.3f')},\n")    
        f.write(f"{total_segments-1}.ts\n")

        # End of the playlist
        f.write("#EXT-X-ENDLIST\n")

def encode_segment(video_id, resolution, start_segment, end_segment):
    """
    Encodes specific video segments from 'original.mp4' into HLS .ts segments.
    """
    input_path = Path(CACHE_DIR) / video_id / "original.mp4"
    output_dir:Path = Path(CACHE_DIR) / video_id / resolution
    output_dir.mkdir(parents=True, exist_ok=True)

    for segment in range(start_segment, end_segment + 1):
        print(f"Encoding segment {segment} for video {video_id}")
        segment_path = output_dir / f"{segment}.ts"
        lock_file = output_dir / f"{segment}.lock"

        if segment_path.exists() or lock_file.exists():
            continue  # Skip if already encoded or locked

        lock_file.touch()  # Create lock file

        try:
            # Encode each segment individually
            subprocess.run([
                "ffmpeg", "-i", str(input_path), "-profile:v", "baseline", "-level", "3.0",
                "-ss", str(segment * SEGMENT_DURATION - 10), "-t", str(SEGMENT_DURATION),
                "-c:v", "libx264", "-c:a", "aac",
                "-output_ts_offset", str(segment * SEGMENT_DURATION - 10),
                #"-reset_timestamps", "1", "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_DURATION})",
                "-f", "mpegts", str(segment_path.as_posix())
            ])


        finally:
            lock_file.unlink()  # Remove lock file after encoding completes

@video.route('/video/<video_id>/<resolution>/play.m3u8')
def get_video(video_id, resolution):
    """
    Serve the HLS master playlist.
    """
    download_youtube_video(video_id)  # Ensure video is downloaded

    # Get video length and create placeholder master playlist
    input_path = Path(CACHE_DIR) / video_id / "original.mp4"
    video_length = get_video_length(input_path)
    total_segments = math.ceil(video_length / SEGMENT_DURATION)

    create_master_playlist(video_id, resolution, total_segments, video_length)
    playlist_path = Path(CACHE_DIR) / video_id / resolution / "master.m3u8"
    

    if playlist_path.exists():
        return send_file(playlist_path, as_attachment=True, mimetype="video/mpegurl")
        # with open(playlist_path, 'r') as file:
            
        #     #return Response(file.read(), mimetype="application/vnd.apple.mpegurl")
    else:
        abort(404, "Failed to create master playlist")

@video.route('/video/<video_id>/<resolution>/<int:segment>.ts')
def get_segment(video_id, resolution, segment):
    """
    Serve or encode individual video segments for HLS on-demand, 
    and start encoding future segments.
    """
    output_dir = Path(CACHE_DIR) / video_id / resolution
    segment_path = output_dir / f"{segment}.ts"

    # If segment doesn’t exist, start encoding it on-demand in a separate thread
    if not segment_path.exists():
        # Start encoding the requested segment immediately
        threading.Thread(target=encode_segment, args=(video_id, resolution, segment, segment)).start()

    # Start encoding future segments asynchronously
    future_start = segment + 1
    future_end = future_start + FUTURE_SEGMENTS - 1
    threading.Thread(target=encode_segment, args=(video_id, resolution, future_start, future_end)).start()

    # Wait for the requested segment to be fully encoded and available
    while not segment_path.exists():
        time.sleep(0.5)  # Check every 500ms

    # Once the segment is available, serve it
    return send_file(segment_path, as_attachment=True, mimetype="video/MP2T")

@video.route("/feeds/api/videos/<video_id>/related")
@video.route("/<int:res>/feeds/api/videos/<video_id>/related")
def get_suggested(video_id, res=''):

    data = get.fetch(f"{config.URL}/api/v1/videos/{video_id}")

    url = request.url_root + str(res)
    user_agent = request.headers.get('User-Agent')
    # Templates have the / at the end, so let's remove it.
    if url[-1] == '/':
        url = url[:-1]

    if data:
        if 'error' in data:
            data = None
        else:
            data = data['recommendedVideos']
        # classic tube check
        if "YouTube v1.0.0" in user_agent:
            return get.template('classic/search.jinja2',{
                'data': data,
                'unix': get.unix,
                'url': url,
                'next_page': None
            })

        return get.template('search_results.jinja2',{
            'data': data,
            'unix': get.unix,
            'url': url,
            'next_page': None
        })
    return error()