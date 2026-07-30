from flask import Flask, request, Response, stream_with_context
import requests
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
    return {"status": "alive", "message": "Terabox Proxy with multiple APIs"}

@app.route('/ping')
def ping():
    return "OK", 200

def get_dlink_via_api(share_url):
    # List of public Terabox download APIs (free, no login)
    apis = [
        {"url": f"https://teraboxdownloader.com/api?url={share_url}", "type": "json"},
        {"url": f"https://terabox-download.com/api?url={share_url}", "type": "json"},
        {"url": f"https://terabox.how/api?url={share_url}", "type": "json"},
        {"url": f"https://terabox-downloader.com/api?url={share_url}", "type": "json"}
    ]
    for api in apis:
        try:
            resp = requests.get(api["url"], timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # Different APIs return different structures
            # Try common patterns
            if data.get('success') or data.get('status') == 'success':
                dlink = data.get('direct_link') or data.get('dlink') or data.get('link')
                filename = data.get('filename') or data.get('file_name') or 'terabox_download.bin'
                if dlink:
                    return dlink, filename
            # Some APIs return a 'list' like official
            if 'list' in data and len(data['list']) > 0:
                first = data['list'][0]
                dlink = first.get('dlink')
                filename = first.get('server_filename', 'terabox_download.bin')
                if dlink:
                    return dlink, filename
            # Some return 'data' field
            if 'data' in data:
                if isinstance(data['data'], dict):
                    dlink = data['data'].get('dlink') or data['data'].get('link')
                    filename = data['data'].get('filename', 'terabox_download.bin')
                    if dlink:
                        return dlink, filename
        except Exception as e:
            app.logger.info(f"API {api['url']} failed: {str(e)}")
            continue
    return None, None

@app.route('/download')
def download_proxy():
    share_url = request.args.get('url')
    if not share_url:
        return "Missing ?url= parameter", 400

    share_url = urllib.parse.unquote(share_url)
    dlink, filename = get_dlink_via_api(share_url)
    if not dlink:
        return "Error: All APIs failed. The share may require login or is invalid.", 400

    # Stream the file from the dlink
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
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': stream_resp.headers.get('Content-Length', '')
        }
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)