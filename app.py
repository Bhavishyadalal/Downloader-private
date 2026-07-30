from flask import Flask, request, Response, stream_with_context
import requests
import re
import urllib.parse
import os
import json

app = Flask(__name__)

@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.terabox.com/",
}
def get_dlink_and_filename(share_url):
    match = re.search(r'/s/([A-Za-z0-9_-]+)', share_url)
    if not match:
        return None, None, "Invalid URL format"
    key = match.group(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    page_url = f"https://www.terabox.com/s/{key}"
    try:
        session.get(page_url, timeout=15)
    except Exception as e:
        return None, None, f"Failed to reach Terabox: {str(e)}"

    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    try:
        resp = session.get(api_url, timeout=15)
        data = resp.json()
    except Exception as e:
        return None, None, f"API error: {str(e)}"

    if data.get("errno") != 0:
        return None, None, f"Terabox error: {data.get('errmsg', 'unknown')}"

    file_list = data.get("list", [])
    if not file_list:
        return None, None, "No files found"

    first = file_list[0]
    dlink = first.get("dlink")
    filename = first.get("server_filename", "terabox_download.bin")
    if not dlink:
        return None, None, "No download link"

    return dlink, filename, session

@app.route('/download')
def download_proxy():
    share_url = request.args.get('url')
    if not share_url:
        return "Missing ?url= parameter", 400

    share_url = urllib.parse.unquote(share_url)
    dlink, filename, session_or_err = get_dlink_and_filename(share_url)
    if isinstance(session_or_err, str):
        return f"Error: {session_or_err}", 400

    try:
        stream_resp = session_or_err.get(dlink, stream=True, timeout=30)
        stream_resp.raise_for_status()
    except Exception as e:
        return f"Failed to fetch file: {str(e)}", 500

    return Response(
        stream_with_context(stream_resp.iter_content(chunk_size=8192)),
        content_type=stream_resp.headers.get('Content-Type', 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': stream_resp.headers.get('Content-Length', '')
        }
    )
@app.route('/ping')
def ping():
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)