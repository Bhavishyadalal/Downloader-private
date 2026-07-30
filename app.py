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
    return {"status": "alive", "message": "Terabox Proxy via public API"}

@app.route('/ping')
def ping():
    return "OK", 200

@app.route('/download')
def download_proxy():
    share_url = request.args.get('url')
    if not share_url:
        return "Missing ?url= parameter", 400

    share_url = urllib.parse.unquote(share_url)

    # Use public terabox downloader API
    # terabox.how is free and doesn't require login
    api_url = f"https://terabox.how/api?url={share_url}"
    try:
        resp = requests.get(api_url, timeout=30)
        data = resp.json()
        if data.get('success'):
            dlink = data.get('direct_link')
            filename = data.get('filename', 'terabox_download.bin')
            if not dlink:
                return "Error: No direct link from API", 400
        else:
            return f"Error: {data.get('message', 'Unknown API error')}", 400
    except Exception as e:
        return f"API request failed: {str(e)}", 500

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