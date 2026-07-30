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

@app.route('/')
def home():
    return {"status": "alive", "message": "Terabox Proxy with cookie support"}

@app.route('/ping')
def ping():
    return "OK", 200

def get_dlink_with_cookies(share_url, cookie_dict):
    key = re.search(r'/s/([A-Za-z0-9_-]+)', share_url).group(1)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.terabox.com/"
    })
    # Set cookies
    for name, value in cookie_dict.items():
        session.cookies.set(name, value)

    # Visit share page to get fresh tokens
    page_url = f"https://www.terabox.com/s/{key}"
    try:
        session.get(page_url, timeout=15)
    except:
        pass

    # API call – should now work because we have login cookies
    api_url = f"https://www.terabox.com/api/shorturlinfo?shorturl={key}"
    try:
        resp = session.get(api_url, timeout=15)
        data = resp.json()
        if data.get("errno") == 0:
            file_list = data.get("list", [])
            if file_list:
                first = file_list[0]
                dlink = first.get("dlink")
                filename = first.get("server_filename", "terabox_download.bin")
                return dlink, filename
        else:
            return None, f"API error: {data.get('errmsg', 'unknown')}"
    except Exception as e:
        return None, f"API request failed: {str(e)}"

    return None, "No download link"

@app.route('/download')
def download_proxy():
    share_url = request.args.get('url')
    cookies_json = request.args.get('cookies')
    if not share_url:
        return "Missing ?url= parameter", 400
    if not cookies_json:
        return "Missing ?cookies= parameter – you must provide your Terabox cookies.", 400

    try:
        cookies = json.loads(urllib.parse.unquote(cookies_json))
    except:
        return "Invalid cookies format – must be JSON object", 400

    share_url = urllib.parse.unquote(share_url)
    dlink, filename_or_error = get_dlink_with_cookies(share_url, cookies)
    if not dlink:
        return f"Error: {filename_or_error}", 400

    session = requests.Session()
    try:
        stream_resp = session.get(dlink, stream=True, timeout=30)
        stream_resp.raise_for_status()
    except Exception as e:
        return f"Failed to fetch file: {str(e)}", 500

    return Response(
        stream_with_context(stream_resp.iter_content(chunk_size=8192)),
        content_type=stream_resp.headers.get('Content-Type', 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{filename_or_error}"',
            'Content-Length': stream_resp.headers.get('Content-Length', '')
        }
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)