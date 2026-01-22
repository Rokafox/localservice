#!/usr/bin/env python3
"""
Simple Local Network File Share Service
No authentication - for local network use only
"""

import os
import shutil
import time
import queue
from flask import Flask, request, send_file, send_from_directory, jsonify, Response
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='')

# Configuration
SHARE_FOLDER = os.path.join(os.path.dirname(__file__), 'shared_files')
os.makedirs(SHARE_FOLDER, exist_ok=True)

# SSE - Store client queues for broadcasting events
client_queues = []


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
        # Remove leading/trailing slashes and normalize
        subpath = subpath.strip('/')
        target = os.path.normpath(os.path.join(SHARE_FOLDER, subpath))
    else:
        target = SHARE_FOLDER

    # Ensure the path is within SHARE_FOLDER (prevent directory traversal)
    if not target.startswith(SHARE_FOLDER):
        return None

    return target


def broadcast_change(event_type, path=''):
    """Broadcast a change event to all connected SSE clients"""
    message = f"event: {event_type}\ndata: {path}\n\n"

    # Send to all connected clients
    dead_queues = []
    for client_queue in client_queues:
        try:
            client_queue.put_nowait(message)
        except queue.Full:
            # Queue is full, mark for removal
            dead_queues.append(client_queue)

    # Remove dead queues
    for dead_queue in dead_queues:
        client_queues.remove(dead_queue)


# Serve the main page
@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('static', 'index.html')


# SSE endpoint for real-time updates
@app.route('/api/events')
def events():
    """Server-Sent Events stream for real-time file updates"""
    def event_stream():
        # Create a queue for this client
        client_queue = queue.Queue(maxsize=10)
        client_queues.append(client_queue)

        try:
            # Send initial connection message
            yield "data: connected\n\n"

            # Keep connection alive and send events
            while True:
                try:
                    # Wait for events with timeout for keep-alive
                    message = client_queue.get(timeout=30)
                    yield message
                except queue.Empty:
                    # Send keep-alive comment every 30 seconds
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            # Client disconnected
            pass
        finally:
            # Remove this client's queue
            if client_queue in client_queues:
                client_queues.remove(client_queue)

    return Response(event_stream(), mimetype='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no',
                        'Connection': 'keep-alive'
                    })


# API: List files in a directory
@app.route('/api/files/', methods=['GET'])
@app.route('/api/files/<path:subpath>', methods=['GET'])
def list_files(subpath=''):
    """List files and folders in the specified directory"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'Path not found'}), 404

    if not os.path.isdir(target_path):
        return jsonify({'error': 'Not a directory'}), 400

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
            else:
                item['size'] = ''

            items.append(item)

    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'items': items})


# API: Upload files
@app.route('/api/upload/', methods=['POST'])
@app.route('/api/upload/<path:subpath>', methods=['POST'])
def upload_files(subpath=''):
    """Upload one or more files"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'Path not found'}), 404

    if not os.path.isdir(target_path):
        return jsonify({'error': 'Not a directory'}), 400

    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    files = request.files.getlist('files')
    uploaded = []

    try:
        for file in files:
            if file.filename:
                filename = secure_filename(file.filename)
                if filename:  # Ensure filename is not empty after sanitization
                    file_path = os.path.join(target_path, filename)
                    file.save(file_path)
                    uploaded.append(filename)

        # Broadcast change event to all connected clients
        if uploaded:
            broadcast_change('file_change', subpath)

        return jsonify({
            'success': True,
            'uploaded': uploaded,
            'count': len(uploaded)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API: Download a file
@app.route('/api/download/<path:subpath>')
def download_file(subpath):
    """Download a file"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'File not found'}), 404

    if not os.path.isfile(target_path):
        return jsonify({'error': 'Not a file'}), 400

    try:
        return send_file(target_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API: Delete a file or folder
@app.route('/api/delete/<path:subpath>', methods=['DELETE'])
def delete_item(subpath):
    """Delete a file or folder"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'Item not found'}), 404

    # Don't allow deleting the root shared folder itself
    if target_path == SHARE_FOLDER:
        return jsonify({'error': 'Cannot delete root folder'}), 403

    try:
        if os.path.isfile(target_path):
            os.remove(target_path)
            # Get the parent directory for the event
            parent_path = os.path.dirname(subpath) if '/' in subpath else ''
            broadcast_change('file_change', parent_path)
            return jsonify({'success': True, 'message': 'File deleted'})
        elif os.path.isdir(target_path):
            shutil.rmtree(target_path)
            # Get the parent directory for the event
            parent_path = os.path.dirname(subpath) if '/' in subpath else ''
            broadcast_change('file_change', parent_path)
            return jsonify({'success': True, 'message': 'Folder deleted'})
        else:
            return jsonify({'error': 'Unknown item type'}), 400

    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("Local File Share Service")
    print("=" * 60)
    print(f"Shared folder: {SHARE_FOLDER}")
    print("Starting server on http://0.0.0.0:8080")
    print("Access from other devices using: http://YOUR_IP:8080")
    print("=" * 60)

    app.run(host='0.0.0.0', port=8080, debug=True)
