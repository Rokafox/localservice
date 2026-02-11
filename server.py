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

# Allow unlimited upload size (no content length restriction)
app.config['MAX_CONTENT_LENGTH'] = None

# Maximum folder depth (root is 0, so max depth 5 allows 5 levels of subfolders)
MAX_FOLDER_DEPTH = 5

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


def get_folder_depth(subpath):
    """Calculate the depth of a folder path (root is 0)"""
    if not subpath or subpath == '':
        return 0
    # Remove leading/trailing slashes and count path segments
    clean_path = subpath.strip('/')
    if not clean_path:
        return 0
    return len(clean_path.split('/'))


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

    # Calculate current depth and check if at max depth
    current_depth = get_folder_depth(subpath)
    can_create_folder = current_depth < MAX_FOLDER_DEPTH

    return jsonify({
        'items': items,
        'current_depth': current_depth,
        'max_depth': MAX_FOLDER_DEPTH,
        'can_create_folder': can_create_folder
    })


# Upload chunk size: 64KB for streaming writes
UPLOAD_CHUNK_SIZE = 64 * 1024


# API: Upload files
@app.route('/api/upload/', methods=['POST'])
@app.route('/api/upload/<path:subpath>', methods=['POST'])
def upload_files(subpath=''):
    """Upload one or more files with streaming write and size verification"""
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
    errors = []

    try:
        for file in files:
            if file.filename:
                filename = secure_filename(file.filename)
                if filename:  # Ensure filename is not empty after sanitization
                    file_path = os.path.join(target_path, filename)

                    # Stream write in chunks to handle large files reliably
                    bytes_written = 0
                    try:
                        with open(file_path, 'wb') as f:
                            while True:
                                chunk = file.stream.read(UPLOAD_CHUNK_SIZE)
                                if not chunk:
                                    break
                                f.write(chunk)
                                bytes_written += len(chunk)
                            f.flush()
                            os.fsync(f.fileno())
                    except Exception as write_error:
                        # Clean up partial file on write failure
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        errors.append(f"{filename}: write failed - {str(write_error)}")
                        continue

                    # Verify the file was written completely
                    actual_size = os.path.getsize(file_path)
                    if actual_size != bytes_written:
                        os.remove(file_path)
                        errors.append(f"{filename}: size verification failed (expected {bytes_written}, got {actual_size})")
                        continue

                    uploaded.append(filename)

        # Broadcast change event to all connected clients
        if uploaded:
            broadcast_change('file_change', subpath)

        result = {
            'success': len(errors) == 0,
            'uploaded': uploaded,
            'count': len(uploaded)
        }
        if errors:
            result['errors'] = errors
            if not uploaded:
                return jsonify(result), 500

        return jsonify(result)

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


# API: Create a folder
@app.route('/api/create-folder/', methods=['POST'])
@app.route('/api/create-folder/<path:subpath>', methods=['POST'])
def create_folder(subpath=''):
    """Create a new folder in the specified directory"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'Parent directory not found'}), 404

    if not os.path.isdir(target_path):
        return jsonify({'error': 'Parent path is not a directory'}), 400

    # Get folder name from request
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Folder name is required'}), 400

    folder_name = secure_filename(data['name'])
    if not folder_name:
        return jsonify({'error': 'Invalid folder name'}), 400

    # Calculate depth of the new folder
    if subpath:
        new_folder_path = f"{subpath}/{folder_name}"
    else:
        new_folder_path = folder_name

    depth = get_folder_depth(new_folder_path)

    # Check depth limit
    if depth > MAX_FOLDER_DEPTH:
        return jsonify({
            'error': f'Maximum folder depth ({MAX_FOLDER_DEPTH}) exceeded. Cannot create folder at depth {depth}.'
        }), 400

    # Create the folder
    new_folder_full_path = os.path.join(target_path, folder_name)

    if os.path.exists(new_folder_full_path):
        return jsonify({'error': 'Folder already exists'}), 409

    try:
        os.makedirs(new_folder_full_path)
        # Broadcast change event
        broadcast_change('file_change', subpath)
        return jsonify({
            'success': True,
            'message': 'Folder created successfully',
            'name': folder_name,
            'path': new_folder_path
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API: Rename a file or folder
@app.route('/api/rename/<path:subpath>', methods=['POST'])
def rename_item(subpath):
    """Rename a file or folder"""
    target_path = get_safe_path(subpath)

    if not target_path:
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(target_path):
        return jsonify({'error': 'Item not found'}), 404

    # Don't allow renaming the root shared folder itself
    if target_path == SHARE_FOLDER:
        return jsonify({'error': 'Cannot rename root folder'}), 403

    # Get new name from request
    data = request.get_json()
    if not data or 'new_name' not in data:
        return jsonify({'error': 'New name is required'}), 400

    new_name = secure_filename(data['new_name'])
    if not new_name:
        return jsonify({'error': 'Invalid name'}), 400

    # Calculate new path
    parent_dir = os.path.dirname(target_path)
    new_path = os.path.join(parent_dir, new_name)

    # Check if new path already exists
    if os.path.exists(new_path):
        return jsonify({'error': 'An item with that name already exists'}), 409

    # If it's a folder, check depth constraints
    if os.path.isdir(target_path):
        # Get the parent path relative to SHARE_FOLDER
        parent_rel_path = os.path.relpath(parent_dir, SHARE_FOLDER)
        if parent_rel_path == '.':
            parent_rel_path = ''

        # Calculate new folder path
        if parent_rel_path:
            new_folder_rel_path = f"{parent_rel_path}/{new_name}"
        else:
            new_folder_rel_path = new_name

        depth = get_folder_depth(new_folder_rel_path)
        if depth > MAX_FOLDER_DEPTH:
            return jsonify({
                'error': f'Renaming would exceed maximum folder depth ({MAX_FOLDER_DEPTH})'
            }), 400

    try:
        os.rename(target_path, new_path)
        # Broadcast change to parent directory
        parent_rel_path = os.path.relpath(parent_dir, SHARE_FOLDER)
        if parent_rel_path == '.':
            parent_rel_path = ''
        broadcast_change('file_change', parent_rel_path)

        return jsonify({
            'success': True,
            'message': 'Item renamed successfully',
            'new_name': new_name
        })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API: Move a file or folder
@app.route('/api/move/<path:subpath>', methods=['POST'])
def move_item(subpath):
    """Move a file or folder to a different directory"""
    source_path = get_safe_path(subpath)

    if not source_path:
        return jsonify({'error': 'Invalid source path'}), 403

    if not os.path.exists(source_path):
        return jsonify({'error': 'Source item not found'}), 404

    # Don't allow moving the root shared folder itself
    if source_path == SHARE_FOLDER:
        return jsonify({'error': 'Cannot move root folder'}), 403

    # Get destination from request
    data = request.get_json()
    if not data or 'destination' not in data:
        return jsonify({'error': 'Destination path is required'}), 400

    dest_subpath = data['destination']
    dest_path = get_safe_path(dest_subpath)

    if not dest_path:
        return jsonify({'error': 'Invalid destination path'}), 403

    if not os.path.exists(dest_path):
        return jsonify({'error': 'Destination not found'}), 404

    if not os.path.isdir(dest_path):
        return jsonify({'error': 'Destination is not a directory'}), 400

    # Get the item name
    item_name = os.path.basename(source_path)
    new_path = os.path.join(dest_path, item_name)

    # Check if destination already has an item with this name
    if os.path.exists(new_path):
        return jsonify({'error': 'An item with that name already exists in the destination'}), 409

    # Check if trying to move a folder into itself
    if os.path.isdir(source_path):
        if dest_path.startswith(source_path):
            return jsonify({'error': 'Cannot move a folder into itself'}), 400

        # Check depth constraints for the new location
        new_rel_path = os.path.relpath(new_path, SHARE_FOLDER)
        depth = get_folder_depth(new_rel_path)
        if depth > MAX_FOLDER_DEPTH:
            return jsonify({
                'error': f'Moving would exceed maximum folder depth ({MAX_FOLDER_DEPTH})'
            }), 400

    try:
        shutil.move(source_path, new_path)

        # Broadcast change to both source and destination directories
        source_parent = os.path.dirname(subpath) if '/' in subpath else ''
        broadcast_change('file_change', source_parent)
        broadcast_change('file_change', dest_subpath)

        return jsonify({
            'success': True,
            'message': 'Item moved successfully',
            'new_path': os.path.relpath(new_path, SHARE_FOLDER)
        })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
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
    print("Starting server on http://0.0.0.0:40000")
    print("Access from other devices using: http://YOUR_IP:40000")
    print("=" * 60)

    app.run(host='0.0.0.0', port=40000, debug=True)
