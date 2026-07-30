from flask import Flask, request, Response, stream_with_context
import requests
import re
import urllib.parse
import os
import json
import logging

app = Flask(__name__)

# Enable logging to see errors in Render logs
logging.basicConfig(level=logging.INFO)

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
@app.route('/')
def home():
    return {
        "status": "alive",
        "message": "Terabox Proxy is running",
        "endpoints": {
            "/download?url=<terabox_link>": "Download a file",
            "/ping": "Health check"
        }
    }
def get_dlink_and_filename(share_url):
    match = re.search(r'/s/([A-Za-z0-9_-]+)', share_url)
    if not match:
        return None, None, "Invalid URL format (missing /s/ key)"
    key = match.group(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    # First visit the share page to get cookies and session
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        session.get(page_url, timeout=15)
    except Exception as e:
        return None, None, f"Failed to reach Terabox share page: {str(e)}"

    # Now call the API
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    try:
        resp = session.get(api_url, timeout=15)
        # Try to parse JSON, but sometimes it returns HTML (e.g., 404)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            # If not JSON, return raw text for debugging
            return None, None, f"API returned non-JSON (maybe HTML): {resp.text[:200]}"
    except Exception as e:
        return None, None, f"API request failed: {str(e)}"

    # Log the full response for debugging (visible in Render logs)
    app.logger.info(f"API response: {json.dumps(data, indent=2)}")

    if data.get("errno") != 0:
        # Return the full error object so we can see what's wrong
        err_details = json.dumps(data)
        return None, None, f"Terabox API error: {err_details}"

    file_list = data.get("list", [])
    if not file_list:
        return None, None, "No files found in this share"

    first = file_list[0]
    dlink = first.get("dlink")
    filename = first.get("server_filename", "terabox_download.bin")
    if not dlink:
        return None, None, "No download link in API response"

    return dlink, filename, session

@app.route('/download')
def download_proxy():
    share_url = request.args.get('url')
    if not share_url:
        return "Missing ?url= parameter", 400

    share_url = urllib.parse.unquote(share_url)
    dlink, filename, session_or_err = get_dlink_and_filename(share_url)
    if isinstance(session_or_err, str):
        # Return error as plain text for the frontend to show
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