#!/usr/bin/env python3
"""
Simple Local Network File Share Service
No authentication - for local network use only
"""

import os
from flask import Flask, render_template_string, request, send_file, redirect, url_for, abort
from werkzeug.utils import secure_filename
import mimetypes

app = Flask(__name__)

# Configuration
SHARE_FOLDER = os.path.join(os.path.dirname(__file__), 'shared_files')
os.makedirs(SHARE_FOLDER, exist_ok=True)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Local File Share</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 30px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
        }
        .path {
            color: #666;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .upload-section {
            background: #f9f9f9;
            padding: 20px;
            border-radius: 6px;
            margin-bottom: 30px;
        }
        .upload-form {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        input[type="file"] {
            flex: 1;
            min-width: 200px;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        button {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        button:hover {
            background: #0056b3;
        }
        .file-list {
            list-style: none;
        }
        .file-item, .folder-item {
            display: flex;
            align-items: center;
            padding: 12px;
            border-bottom: 1px solid #eee;
            transition: background 0.2s;
        }
        .file-item:hover, .folder-item:hover {
            background: #f9f9f9;
        }
        .icon {
            margin-right: 12px;
            font-size: 20px;
        }
        .name {
            flex: 1;
            color: #333;
            text-decoration: none;
        }
        .folder-item .name {
            color: #007bff;
            font-weight: 500;
        }
        .size {
            color: #666;
            font-size: 13px;
            margin-right: 15px;
        }
        .download-btn {
            background: #28a745;
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            text-decoration: none;
            font-size: 13px;
        }
        .download-btn:hover {
            background: #218838;
        }
        .empty {
            text-align: center;
            color: #999;
            padding: 40px;
        }
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            color: #007bff;
            text-decoration: none;
        }
        .back-link:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 Local File Share</h1>
        <div class="path">{{ current_path or '/' }}</div>

        {% if parent_path %}
        <a href="{{ url_for('browse', subpath=parent_path) }}" class="back-link">⬅️ Back</a>
        {% endif %}

        <div class="upload-section">
            <h2 style="margin-bottom: 15px; font-size: 18px;">Upload Files</h2>
            <form method="POST" action="{{ url_for('upload', subpath=current_path or '') }}"
                  enctype="multipart/form-data" class="upload-form">
                <input type="file" name="file" multiple required>
                <button type="submit">Upload</button>
            </form>
        </div>

        <h2 style="margin-bottom: 15px; font-size: 18px;">Files and Folders</h2>

        {% if items %}
        <ul class="file-list">
            {% for item in items %}
                {% if item.is_dir %}
                <li class="folder-item">
                    <span class="icon">📁</span>
                    <a href="{{ url_for('browse', subpath=item.path) }}" class="name">{{ item.name }}</a>
                </li>
                {% else %}
                <li class="file-item">
                    <span class="icon">📄</span>
                    <span class="name">{{ item.name }}</span>
                    <span class="size">{{ item.size }}</span>
                    <a href="{{ url_for('download', subpath=item.path) }}"
                       class="download-btn">Download</a>
                </li>
                {% endif %}
            {% endfor %}
        </ul>
        {% else %}
        <div class="empty">No files yet. Upload some files to get started!</div>
        {% endif %}
    </div>
</body>
</html>
"""


def format_size(size):
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_safe_path(subpath):
    """Get safe absolute path within SHARE_FOLDER"""
    if subpath:
        # Remove leading slash and normalize
        subpath = subpath.lstrip('/')
        target = os.path.normpath(os.path.join(SHARE_FOLDER, subpath))
    else:
        target = SHARE_FOLDER

    # Ensure the path is within SHARE_FOLDER
    if not target.startswith(SHARE_FOLDER):
        abort(403)

    return target


@app.route('/')
@app.route('/browse/')
@app.route('/browse/<path:subpath>')
def browse(subpath=''):
    """Browse files and folders"""
    target_path = get_safe_path(subpath)

    if not os.path.exists(target_path):
        abort(404)

    if os.path.isfile(target_path):
        return redirect(url_for('download', subpath=subpath))

    # List directory contents
    items = []
    try:
        for entry in os.listdir(target_path):
            entry_path = os.path.join(target_path, entry)
            rel_path = os.path.relpath(entry_path, SHARE_FOLDER)

            item = {
                'name': entry,
                'path': rel_path,
                'is_dir': os.path.isdir(entry_path)
            }

            if not item['is_dir']:
                item['size'] = format_size(os.path.getsize(entry_path))

            items.append(item)

        # Sort: folders first, then files, alphabetically
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    except PermissionError:
        abort(403)

    # Calculate parent path for back button
    parent_path = None
    if subpath:
        parent_path = os.path.dirname(subpath)

    return render_template_string(
        HTML_TEMPLATE,
        items=items,
        current_path=subpath,
        parent_path=parent_path
    )


@app.route('/download/<path:subpath>')
def download(subpath):
    """Download a file"""
    target_path = get_safe_path(subpath)

    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        abort(404)

    return send_file(target_path, as_attachment=True)


@app.route('/upload/', methods=['POST'])
@app.route('/upload/<path:subpath>', methods=['POST'])
def upload(subpath=''):
    """Upload files"""
    target_path = get_safe_path(subpath)

    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        abort(404)

    if 'file' not in request.files:
        return redirect(url_for('browse', subpath=subpath))

    files = request.files.getlist('file')

    for file in files:
        if file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(target_path, filename))

    return redirect(url_for('browse', subpath=subpath))


if __name__ == '__main__':
    print("=" * 60)
    print("Local File Share Service")
    print("=" * 60)
    print(f"Shared folder: {SHARE_FOLDER}")
    print("Starting server on http://0.0.0.0:8080")
    print("Access from other devices using: http://YOUR_IP:8080")
    print("=" * 60)

    app.run(host='0.0.0.0', port=8080, debug=True)
