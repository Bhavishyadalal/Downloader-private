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
    return {"status": "alive", "message": "Terabox Proxy running", "endpoints": {"/download?url=...": "Download", "/ping": "Health"}}

@app.route('/ping')
def ping():
    return "OK", 200

# ---------- Core functions ----------
def extract_dlink_from_html(html):
    # Use BeautifulSoup to find all script tags
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        if not script.string:
            continue
        content = script.string
        # Look for any assignment to window.data or similar
        if 'window.data' in content or '__INITIAL_STATE__' in content or 'dlink' in content:
            # Try to extract a JSON-like structure
            # Find a block that contains "dlink"
            dlink_match = re.search(r'"dlink"\s*:\s*"([^"]+)"', content)
            if dlink_match:
                return dlink_match.group(1).replace('\\', '')
            # Also look for "download_link"
            dl_match = re.search(r'"download_link"\s*:\s*"([^"]+)"', content)
            if dl_match:
                return dl_match.group(1).replace('\\', '')
    # Fallback: scan entire HTML
    match = re.search(r'"dlink"\s*:\s*"([^"]+)"', html)
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

    # Visit share page to get cookies and HTML
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        page_resp = session.get(page_url, timeout=15)
        page_resp.raise_for_status()
        html = page_resp.text
    except Exception as e:
        return None, None, f"Failed to load share page: {str(e)}"

    # Try API
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    data = None
    try:
        api_resp = session.get(api_url, timeout=15)
        data = api_resp.json()
    except:
        pass

    dlink = None
    filename = "terabox_download.bin"

    # First attempt: if API returned valid dlink
    if data and data.get("errno") == 0:
        file_list = data.get("list", [])
        if file_list:
            first = file_list[0]
            dlink = first.get("dlink")
            filename = first.get("server_filename", "terabox_download.bin")
    else:
        app.logger.info("API error, extracting from HTML")
        dlink = extract_dlink_from_html(html)
        if dlink:
            # Extract filename
            fname_match = re.search(r'"server_filename"\s*:\s*"([^"]+)"', html)
            if fname_match:
                filename = fname_match.group(1)
            else:
                title_match = re.search(r'<title>(.+?)</title>', html)
                if title_match:
                    filename = title_match.group(1).strip() + ".bin"
        else:
            # If still no dlink, try to construct using API data
            if data:
                # We have shareid, uk, sign, timestamp, randsk
                # Build a direct download URL
                shareid = data.get("shareid")
                uk = data.get("uk")
                sign = data.get("sign")
                timestamp = data.get("timestamp")
                randsk = data.get("randsk")
                if shareid and uk and sign and timestamp:
                    # The actual download endpoint expects these parameters
                    download_url = f"https://www.terabox.com/api/download?shareid={shareid}&uk={uk}&sign={sign}&timestamp={timestamp}&randsk={randsk}"
                    # Also need to include the session cookies
                    # We'll try to get it
                    try:
                        dl_resp = session.get(download_url, timeout=15)
                        # The response might be a redirect or JSON with the dlink
                        if dl_resp.status_code == 200:
                            # Try to parse as JSON
                            try:
                                dl_data = dl_resp.json()
                                if 'dlink' in dl_data:
                                    dlink = dl_data['dlink']
                                elif 'list' in dl_data and len(dl_data['list']) > 0:
                                    dlink = dl_data['list'][0].get('dlink')
                            except:
                                # Maybe it's a direct binary? Unlikely.
                                pass
                    except:
                        pass
            if not dlink:
                return None, None, "No download link found"

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