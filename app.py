from flask import Flask, request, Response, stream_with_context
import requests
import re
import urllib.parse
import os
import json
import logging

app = Flask(__name__)
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
    return {"status":"alive","message":"Terabox Proxy running","endpoints":{"/download?url=...":"Download file","/ping":"Health check"}}

@app.route('/ping')
def ping():
    return "OK", 200
def extract_dlink_from_html(html):
    # Look for window.data = {...} or window.__INITIAL_STATE__
    # Typical pattern: "dlink":"https://..."
    match = re.search(r'"dlink"\s*:\s*"([^"]+)"', html)
    if match:
        dlink = match.group(1).replace('\\', '')
        return dlink
    # Also look for "download_link":"..."
    match = re.search(r'"download_link"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1).replace('\\', '')
    return None

def get_dlink_and_filename(share_url):
    match = re.search(r'/s/([A-Za-z0-9_-]+)', share_url)
    if not match:
        return None, None, "Invalid URL format"
    key = match.group(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    # First visit the share page – this gives us cookies and HTML
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        page_resp = session.get(page_url, timeout=15)
        page_resp.raise_for_status()
        html = page_resp.text
    except Exception as e:
        return None, None, f"Failed to load share page: {str(e)}"

    # Try API first (fast)
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    try:
        api_resp = session.get(api_url, timeout=15)
        data = api_resp.json()
    except:
        data = None

    dlink = None
    filename = "terabox_download.bin"

    if data and data.get("errno") == 0:
        file_list = data.get("list", [])
        if file_list:
            first = file_list[0]
            dlink = first.get("dlink")
            filename = first.get("server_filename", "terabox_download.bin")
    else:
        # API failed – fallback to HTML scraping
        app.logger.info("API returned error, trying HTML scraping")
        dlink = extract_dlink_from_html(html)
        if dlink:
            # Try to extract filename from HTML as well
            fname_match = re.search(r'"server_filename"\s*:\s*"([^"]+)"', html)
            if fname_match:
                filename = fname_match.group(1)
            else:
                # Fallback filename from title
                title_match = re.search(r'<title>(.+?)</title>', html)
                if title_match:
                    filename = title_match.group(1).strip() + ".bin"
        else:
            # If still no dlink, return the API error or a generic message
            err_msg = "No download link found. This link may require captcha or login."
            if data:
                err_msg = f"API error: {json.dumps(data)}"
            return None, None, err_msg

    if not dlink:
        return None, None, "Could not extract download link"

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)