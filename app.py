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
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.terabox.com/",
}

@app.route('/')
def home():
    return {"status": "alive", "message": "Terabox Proxy running", "endpoints": {"/download?url=...": "Download", "/ping": "Health"}}

@app.route('/ping')
def ping():
    return "OK", 200

# ---------- Core ----------
def get_dlink_and_filename(share_url):
    match = re.search(r'/s/([A-Za-z0-9_-]+)', share_url)
    if not match:
        return None, None, "Invalid URL format"
    key = match.group(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    # Visit share page to get cookies
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        session.get(page_url, timeout=15)
    except Exception as e:
        return None, None, f"Failed to reach Terabox: {str(e)}"

    # Try API
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    data = None
    try:
        api_resp = session.get(api_url, timeout=15)
        data = api_resp.json()
        app.logger.info(f"API response: {json.dumps(data)}")
    except Exception as e:
        return None, None, f"API request failed: {str(e)}"

    # If API returned a valid list
    if data and data.get("errno") == 0:
        file_list = data.get("list", [])
        if file_list:
            first = file_list[0]
            dlink = first.get("dlink")
            filename = first.get("server_filename", "terabox_download.bin")
            if dlink:
                return dlink, filename, session

    # If errno is -3 or any other error, try the download API using the metadata
    if data and data.get("shareid") and data.get("uk"):
        shareid = data.get("shareid")
        uk = data.get("uk")
        sign = data.get("sign")
        timestamp = data.get("timestamp")
        randsk = data.get("randsk")
        # Build the download API call
        dl_url = f"https://www.terabox.com/api/download?shareid={shareid}&uk={uk}&sign={sign}&timestamp={timestamp}&randsk={randsk}"
        try:
            dl_resp = session.get(dl_url, timeout=15)
            dl_data = dl_resp.json()
            app.logger.info(f"Download API response: {json.dumps(dl_data)}")
            if dl_data.get("errno") == 0:
                file_list = dl_data.get("list", [])
                if file_list:
                    first = file_list[0]
                    dlink = first.get("dlink")
                    filename = first.get("server_filename", "terabox_download.bin")
                    if dlink:
                        return dlink, filename, session
        except Exception as e:
            return None, None, f"Download API failed: {str(e)}"

    # Last resort: try to extract dlink from HTML (if we have it)
    try:
        html_resp = session.get(page_url, timeout=15)
        html = html_resp.text
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup.find_all('script'):
            if script.string and ('window.data' in script.string or '__INITIAL_STATE__' in script.string):
                match = re.search(r'"dlink"\s*:\s*"([^"]+)"', script.string)
                if match:
                    dlink = match.group(1).replace('\\', '')
                    if dlink:
                        filename = "terabox_download.bin"
                        fname_match = re.search(r'"server_filename"\s*:\s*"([^"]+)"', script.string)
                        if fname_match:
                            filename = fname_match.group(1)
                        return dlink, filename, session
    except:
        pass

    return None, None, "No download link found – the share may require a captcha or is private."

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