import os
import subprocess

import ffmpeg
from modules import get, helpers
from flask import Blueprint, Flask, request, redirect, render_template, Response, send_file
import config
from modules.logs import print_with_seperator
from modules import yt

video = Blueprint("video", __name__)
ffmpeg_processes = list()

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
def getvideo(video_id, res=None):
    if res is not None or config.MEDIUM_QUALITY is False:
        
        # Clamp Res
        if type(res) == int:
            res = min(max(res, 144), config.RESMAX)
    
        # Set mimetype since videole device don't recognized it.
        return Response(yt.hls_video_url(video_id, res), mimetype="application/vnd.apple.mpegurl")
    
    # 360p if enabled
    #yt.hls_video_url(video_id, res)
    return redirect(f"/convert/{video_id}", 307)
    #return send_file("./cache/videos/ios_video2.mp4", as_attachment=True)

def convert_video(input_url, output_path):
    # FFmpeg conversion for iPhone 3G compatibility
    result = subprocess.run([
        'ffmpeg',
        '-i', input_url,
        '-r', '24',         # Set frame rate
        '-vcodec', 'libx264',
        '-profile:v', 'baseline',
        '-movflags', '+faststart',
        '-c:a', 'copy',     # Copy audio codec
        '-b:v', '500k',
        '-minrate', '500k',
        '-maxrate', '500k',
        '-bufsize', '1000k',
        '-g', '48',
        '-keyint_min', '48',
        '-vf', 'scale=-1:360',
        output_path
    ])

    #     # FFmpeg conversion for iPhone 3G compatibility
    # result = subprocess.run([
    #     'ffmpeg',
    #     '-i', input_url,
    #     '-r', '24',         # Set frame rate
    #     '-c:v', 'mpeg4',  # Video codec
    #     #'-preset', 'fast',
    #     '-crf', '5',
    #     '-c:a', 'copy',     # Audio codec
    #     #'-s', '640x320',    # Output resolution for iPhone 3G
    #     # '-vcodec', 'libx264',
    #     # '-profile:v', 'baseline',
    #     # '-level', '3.0',
    #     # '-acodec', 'aac',
    #     # '-movflags', '+faststart',
    #     # '-b:v', '500k',     # Adjust if needed
    #     # '-maxrate', '500k',
    #     # '-bufsize', '1000k',
    #     # '-g', '30',         # Set GOP size
    #     # '-bf', '0',         # Disable B-frames
    #     # '-keyint_min', '30',# Keyframe interval
    #     # '-s', '480x320',    # Output resolution for iPhone 3G
    #     output_path
    # ])
    # ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #result.stdout
    # ffmpeg.input(input_url).output(
    #     output_path,
    #     vcodec='libx264',
    #     profile='baseline',
    #     level='3.0',
    #     acodec='aac',
    #     movflags='+faststart',
    #     video_bitrate='500k',     # Adjust if needed
    #     maxrate='500k',
    #     bufsize='1000k',
    #     g=30,                     # Set GOP size
    #     bf=0,                     # Disable B-frames
    #     keyint_min=30,            # Keyframe interval
    #     s='480x320'               # Output resolution for iPhone 3G
    # ).run()


@video.route('/convert/<video_id>')
def convert_and_stream(video_id):
    # Path setup
    output_path = f'./cache/videos/{video_id}.mp4'
    input_url = yt.medium_quality_video_url(video_id)

    # Convert if not already cached
    if not os.path.exists(output_path):
        convert_video(input_url, output_path)

    # Serve with HTTP 206
    return partial_content_response(output_path)

def partial_content_response(path):
    file_size = os.path.getsize(path)
    range_header = request.headers.get('Range', None)
    if not range_header:
        # If no Range header, serve the entire file
        return send_file(path, as_attachment=True)

    start, end = range_header.replace('bytes=', '').split('-')
    start = int(start)
    end = int(end) if end else file_size - 1
    length = end - start + 1

    with open(path, 'rb') as f:
        f.seek(start)
        data = f.read(length)

    headers = {
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(length),
        'Content-Type': 'video/mp4'
    }

    return Response(data, status=206, headers=headers)

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