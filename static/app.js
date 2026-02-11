// Global state
let currentPath = '';
let eventSource = null;
let canCreateFolder = true;

// Initialize the app
document.addEventListener('DOMContentLoaded', () => {
    loadFiles();
    setupUploadForm();
    setupCreateFolderButton();
    setupSSE();
});

// Load and display files
async function loadFiles(path = '') {
    currentPath = path;
    const fileList = document.getElementById('fileList');
    const pathDisplay = document.getElementById('currentPath');

    // Update path display
    pathDisplay.textContent = '/' + path;

    // Update breadcrumb
    updateBreadcrumb(path);

    // Show loading
    fileList.innerHTML = '<div class="loading">Loading...</div>';

    try {
        const response = await fetch(`/api/files/${path}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load files');
        }

        // Update folder creation capability
        canCreateFolder = data.can_create_folder;
        updateCreateFolderButton();

        displayFiles(data.items);
    } catch (error) {
        fileList.innerHTML = `<div class="error">Error loading files: ${error.message}</div>`;
    }
}

// Display files and folders
function displayFiles(items) {
    const fileList = document.getElementById('fileList');

    if (items.length === 0) {
        fileList.innerHTML = '<div class="empty">No files yet. Upload some files to get started!</div>';
        return;
    }

    fileList.innerHTML = '';

    // Sort: folders first, then files
    items.sort((a, b) => {
        if (a.is_dir && !b.is_dir) return -1;
        if (!a.is_dir && b.is_dir) return 1;
        return a.name.localeCompare(b.name);
    });

    items.forEach(item => {
        const div = document.createElement('div');
        div.className = item.is_dir ? 'folder-item' : 'file-item';

        const icon = document.createElement('span');
        icon.className = 'icon';
        icon.textContent = item.is_dir ? '📁' : '📄';

        const name = document.createElement('span');
        name.className = 'name';
        name.textContent = item.name;

        if (item.is_dir) {
            name.onclick = () => loadFiles(item.path);
        }

        div.appendChild(icon);
        div.appendChild(name);

        if (!item.is_dir) {
            const size = document.createElement('span');
            size.className = 'size';
            size.textContent = item.size;
            div.appendChild(size);
        }

        // Actions
        const actions = document.createElement('div');
        actions.className = 'actions';

        if (!item.is_dir) {
            const downloadBtn = document.createElement('a');
            downloadBtn.className = 'btn-download';
            downloadBtn.textContent = 'Download';
            downloadBtn.href = `/api/download/${item.path}`;
            downloadBtn.download = item.name;
            actions.appendChild(downloadBtn);
        }

        const renameBtn = document.createElement('button');
        renameBtn.className = 'btn-rename';
        renameBtn.textContent = 'Rename';
        renameBtn.onclick = () => renameItem(item.path, item.name);
        actions.appendChild(renameBtn);

        const moveBtn = document.createElement('button');
        moveBtn.className = 'btn-move';
        moveBtn.textContent = 'Move';
        moveBtn.onclick = () => moveItem(item.path, item.name);
        actions.appendChild(moveBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn-delete';
        deleteBtn.textContent = 'Delete';
        deleteBtn.onclick = () => deleteItem(item.path, item.name, item.is_dir);
        actions.appendChild(deleteBtn);

        div.appendChild(actions);
        fileList.appendChild(div);
    });
}

// Update breadcrumb navigation
function updateBreadcrumb(path) {
    const breadcrumb = document.getElementById('breadcrumb');
    breadcrumb.innerHTML = '';

    const homeLink = document.createElement('a');
    homeLink.href = '#';
    homeLink.textContent = 'Home';
    homeLink.onclick = (e) => {
        e.preventDefault();
        loadFiles('');
    };
    breadcrumb.appendChild(homeLink);

    if (path) {
        const parts = path.split('/');
        let currentPathBuild = '';

        parts.forEach((part, index) => {
            currentPathBuild += (index > 0 ? '/' : '') + part;
            const pathLink = document.createElement('a');
            pathLink.href = '#';
            pathLink.textContent = part;
            const pathToLoad = currentPathBuild;
            pathLink.onclick = (e) => {
                e.preventDefault();
                loadFiles(pathToLoad);
            };
            breadcrumb.appendChild(pathLink);
        });
    }
}

// Setup create folder button
function setupCreateFolderButton() {
    const createFolderBtn = document.getElementById('createFolderBtn');
    createFolderBtn.onclick = createFolder;
}

// Update create folder button state
function updateCreateFolderButton() {
    const createFolderBtn = document.getElementById('createFolderBtn');
    if (canCreateFolder) {
        createFolderBtn.disabled = false;
        createFolderBtn.title = 'Create a new folder';
    } else {
        createFolderBtn.disabled = true;
        createFolderBtn.title = 'Maximum folder depth reached';
    }
}

// Create a new folder
async function createFolder() {
    const folderName = prompt('Enter folder name:');

    if (!folderName) return;

    // Basic validation
    if (folderName.trim() === '') {
        alert('Folder name cannot be empty');
        return;
    }

    try {
        const response = await fetch(`/api/create-folder/${currentPath}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name: folderName })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to create folder');
        }

        // Reload current directory
        loadFiles(currentPath);

    } catch (error) {
        alert(`Failed to create folder: ${error.message}`);
    }
}

// Format bytes to human-readable size
function formatSize(bytes) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let unitIndex = 0;
    let size = bytes;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return size.toFixed(1) + ' ' + units[unitIndex];
}

// Format seconds to human-readable time
function formatTime(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
}

// Current upload XHR (for cancel support)
let currentUploadXhr = null;

// Setup upload form
function setupUploadForm() {
    const form = document.getElementById('uploadForm');
    const fileInput = document.getElementById('fileInput');
    const progress = document.getElementById('uploadProgress');

    form.onsubmit = (e) => {
        e.preventDefault();

        const files = fileInput.files;
        if (files.length === 0) return;

        const formData = new FormData();
        let totalSize = 0;
        for (let file of files) {
            formData.append('files', file);
            totalSize += file.size;
        }

        // Show progress bar
        progress.className = 'upload-progress';
        progress.innerHTML =
            '<div class="progress-info">' +
                '<span class="progress-text">Uploading ' + files.length + ' file(s)...</span>' +
                '<span class="progress-percent">0%</span>' +
            '</div>' +
            '<div class="progress-bar-track">' +
                '<div class="progress-bar-fill" style="width: 0%"></div>' +
            '</div>' +
            '<div class="progress-details">' +
                '<span class="progress-transferred">0 B / ' + formatSize(totalSize) + '</span>' +
                '<span class="progress-speed"></span>' +
            '</div>' +
            '<button type="button" class="btn-cancel-upload" onclick="cancelUpload()">Cancel</button>';

        const xhr = new XMLHttpRequest();
        currentUploadXhr = xhr;
        const startTime = Date.now();

        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
                const percent = Math.round((event.loaded / event.total) * 100);
                const elapsed = (Date.now() - startTime) / 1000;
                const speed = elapsed > 0 ? event.loaded / elapsed : 0;
                const remaining = speed > 0 ? (event.total - event.loaded) / speed : 0;

                progress.querySelector('.progress-bar-fill').style.width = percent + '%';
                progress.querySelector('.progress-percent').textContent = percent + '%';
                progress.querySelector('.progress-transferred').textContent =
                    formatSize(event.loaded) + ' / ' + formatSize(event.total);

                if (elapsed > 0.5) {
                    let speedText = formatSize(speed) + '/s';
                    if (percent < 100) {
                        speedText += ' - ' + formatTime(remaining) + ' remaining';
                    }
                    progress.querySelector('.progress-speed').textContent = speedText;
                }

                if (percent === 100) {
                    progress.querySelector('.progress-text').textContent = 'Processing on server...';
                    progress.querySelector('.progress-speed').textContent = '';
                    const cancelBtn = progress.querySelector('.btn-cancel-upload');
                    if (cancelBtn) cancelBtn.style.display = 'none';
                }
            }
        };

        xhr.onload = () => {
            currentUploadXhr = null;
            if (xhr.status >= 200 && xhr.status < 300) {
                let data;
                try { data = JSON.parse(xhr.responseText); } catch(e) { data = {}; }
                const count = data.count || files.length;
                progress.innerHTML =
                    '<div class="progress-info">' +
                        '<span class="progress-text">Successfully uploaded ' + count + ' file(s)</span>' +
                    '</div>' +
                    '<div class="progress-bar-track">' +
                        '<div class="progress-bar-fill complete" style="width: 100%"></div>' +
                    '</div>';
                progress.className = 'upload-progress success';
                fileInput.value = '';
                setTimeout(() => {
                    progress.className = 'upload-progress hidden';
                    loadFiles(currentPath);
                }, 2000);
            } else {
                let errorMsg = 'Upload failed';
                try {
                    const data = JSON.parse(xhr.responseText);
                    errorMsg = data.error || errorMsg;
                } catch(e) {}
                progress.innerHTML =
                    '<div class="progress-info">' +
                        '<span class="progress-text">' + errorMsg + '</span>' +
                    '</div>';
                progress.className = 'upload-progress error';
            }
        };

        xhr.onerror = () => {
            currentUploadXhr = null;
            progress.innerHTML =
                '<div class="progress-info">' +
                    '<span class="progress-text">Upload failed: Network error</span>' +
                '</div>';
            progress.className = 'upload-progress error';
        };

        xhr.onabort = () => {
            currentUploadXhr = null;
            progress.innerHTML =
                '<div class="progress-info">' +
                    '<span class="progress-text">Upload cancelled</span>' +
                '</div>';
            progress.className = 'upload-progress error';
            setTimeout(() => {
                progress.className = 'upload-progress hidden';
            }, 2000);
        };

        xhr.open('POST', '/api/upload/' + currentPath);
        xhr.send(formData);
    };
}

// Cancel ongoing upload
function cancelUpload() {
    if (currentUploadXhr) {
        currentUploadXhr.abort();
    }
}

// Delete a file or folder
async function deleteItem(path, name, isDir) {
    const itemType = isDir ? 'folder' : 'file';
    const confirmMsg = isDir
        ? `Are you sure you want to delete the folder "${name}" and all its contents?`
        : `Are you sure you want to delete "${name}"?`;

    if (!confirm(confirmMsg)) return;

    try {
        const response = await fetch(`/api/delete/${path}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Delete failed');
        }

        // Reload current directory
        loadFiles(currentPath);

    } catch (error) {
        alert(`Failed to delete ${itemType}: ${error.message}`);
    }
}

// Rename a file or folder
async function renameItem(path, currentName) {
    const newName = prompt(`Rename "${currentName}" to:`, currentName);

    if (!newName || newName === currentName) return;

    // Basic validation
    if (newName.trim() === '') {
        alert('Name cannot be empty');
        return;
    }

    try {
        const response = await fetch(`/api/rename/${path}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ new_name: newName })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Rename failed');
        }

        // Reload current directory
        loadFiles(currentPath);

    } catch (error) {
        alert(`Failed to rename: ${error.message}`);
    }
}

// Move a file or folder
async function moveItem(path, name) {
    // First, fetch the folder structure to let user choose destination
    try {
        const folders = await getFolderList();

        // Create a selection dialog
        let message = `Move "${name}" to:\n\n`;
        message += '0. / (Root)\n';
        folders.forEach((folder, index) => {
            message += `${index + 1}. ${folder.path}\n`;
        });
        message += '\nEnter the number of the destination folder:';

        const choice = prompt(message);

        if (choice === null) return; // User cancelled

        const choiceNum = parseInt(choice);

        if (isNaN(choiceNum) || choiceNum < 0 || choiceNum > folders.length) {
            alert('Invalid selection');
            return;
        }

        // Get destination path
        const destination = choiceNum === 0 ? '' : folders[choiceNum - 1].path;

        // Don't move to the same location
        const currentParent = path.includes('/') ? path.substring(0, path.lastIndexOf('/')) : '';
        if (destination === currentParent) {
            alert('Item is already in that location');
            return;
        }

        // Perform the move
        const response = await fetch(`/api/move/${path}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ destination: destination })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Move failed');
        }

        // Reload current directory
        loadFiles(currentPath);

    } catch (error) {
        alert(`Failed to move: ${error.message}`);
    }
}

// Get list of all folders for move operation
async function getFolderList(path = '', folders = []) {
    try {
        const response = await fetch(`/api/files/${path}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load folders');
        }

        // Add folders from this directory
        for (const item of data.items) {
            if (item.is_dir) {
                folders.push({ name: item.name, path: item.path });
                // Recursively get subfolders
                await getFolderList(item.path, folders);
            }
        }

        return folders;
    } catch (error) {
        console.error('Error loading folders:', error);
        return folders;
    }
}

// Setup Server-Sent Events for real-time updates
function setupSSE() {
    // Close existing connection if any
    if (eventSource) {
        eventSource.close();
    }

    // Create new EventSource connection
    eventSource = new EventSource('/api/events');

    eventSource.onopen = () => {
        console.log('SSE connection established');
    };

    eventSource.onmessage = (event) => {
        if (event.data === 'connected') {
            console.log('SSE connected');
            return;
        }
    };

    // Listen for file_change events
    eventSource.addEventListener('file_change', (event) => {
        const changedPath = event.data;

        // Reload if the change is in the current directory
        // or if we're in the root and any change occurs
        if (changedPath === currentPath ||
            (currentPath === '' && changedPath === '') ||
            changedPath.startsWith(currentPath)) {
            console.log(`File change detected in: ${changedPath || 'root'}, reloading...`);
            loadFiles(currentPath);
        }
    });

    eventSource.onerror = (error) => {
        console.error('SSE error:', error);
        eventSource.close();

        // Attempt to reconnect after 5 seconds
        console.log('Attempting to reconnect in 5 seconds...');
        setTimeout(() => {
            setupSSE();
        }, 5000);
    };
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (eventSource) {
        eventSource.close();
    }
});
