from flask import Flask, request, Response, stream_with_context
import requests
import re
import urllib.parse
import os
import json
import logging
from bs4 import BeautifulSoup

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
    return {
        "status": "alive",
        "message": "Terabox Proxy is running",
        "endpoints": {
            "/download?url=<terabox_link>": "Download a file",
            "/ping": "Health check"
        }
    }

@app.route('/ping')
def ping():
    return "OK", 200
def extract_dlink_from_html(html):
    # Use BeautifulSoup to find all script tags
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        if script.string:
            content = script.string
            # Look for window.data or __INITIAL_STATE__
            if 'window.data' in content or '__INITIAL_STATE__' in content:
                # Try to extract JSON object
                # Find the first { and the last } in the script
                start = content.find('{')
                end = content.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_str = content[start:end+1]
                    try:
                        data = json.loads(json_str)
                        # If it's wrapped like { data: {...} }
                        if 'data' in data and isinstance(data['data'], dict):
                            data = data['data']
                        # Now look for list
                        if 'list' in data and isinstance(data['list'], list) and len(data['list']) > 0:
                            dlink = data['list'][0].get('dlink')
                            if dlink:
                                return dlink
                        # Also check for direct dlink
                        if 'dlink' in data:
                            return data['dlink']
                    except json.JSONDecodeError:
                        # Try to extract using regex as fallback
                        match = re.search(r'"dlink"\s*:\s*"([^"]+)"', content)
                        if match:
                            return match.group(1).replace('\\', '')
    # Fallback: search entire HTML for "dlink":"..."
    match = re.search(r'"dlink"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1).replace('\\', '')
    return None

def get_dlink_and_filename(share_url):
    match = re.search(r'/s/([A-Za-z0-9_-]+)', share_url)
    if not match:
        return None, None, "Invalid URL format (missing /s/ key)"
    key = match.group(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    # First, visit the share page to get cookies and HTML
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        page_resp = session.get(page_url, timeout=15)
        page_resp.raise_for_status()
        html = page_resp.text
    except Exception as e:
        return None, None, f"Failed to load share page: {str(e)}"

    # Try the API first (fast)
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    data = None
    try:
        api_resp = session.get(api_url, timeout=15)
        data = api_resp.json()
    except:
        pass

    dlink = None
    filename = "terabox_download.bin"

    if data and data.get("errno") == 0:
        file_list = data.get("list", [])
        if file_list:
            first = file_list[0]
            dlink = first.get("dlink")
            filename = first.get("server_filename", "terabox_download.bin")
    else:
        # API returned error – fallback to HTML scraping
        app.logger.info("API returned error, trying HTML scraping")
        dlink = extract_dlink_from_html(html)
        if dlink:
            # Try to extract filename from HTML
            fname_match = re.search(r'"server_filename"\s*:\s*"([^"]+)"', html)
            if fname_match:
                filename = fname_match.group(1)
            else:
                title_match = re.search(r'<title>(.+?)</title>', html)
                if title_match:
                    filename = title_match.group(1).strip() + ".bin"
        else:
            # Still no dlink – return the API error if exists, else generic
            if data:
                return None, None, f"API error: {json.dumps(data)}"
            else:
                return None, None, "Could not extract download link from HTML"

    if not dlink:
        return None, None, "No download link found"

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