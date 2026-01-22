// Global state
let currentPath = '';
let eventSource = null;

// Initialize the app
document.addEventListener('DOMContentLoaded', () => {
    loadFiles();
    setupUploadForm();
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

// Setup upload form
function setupUploadForm() {
    const form = document.getElementById('uploadForm');
    const fileInput = document.getElementById('fileInput');
    const progress = document.getElementById('uploadProgress');

    form.onsubmit = async (e) => {
        e.preventDefault();

        const files = fileInput.files;
        if (files.length === 0) return;

        const formData = new FormData();
        for (let file of files) {
            formData.append('files', file);
        }

        try {
            progress.textContent = 'Uploading...';
            progress.className = 'upload-progress';

            const response = await fetch(`/api/upload/${currentPath}`, {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Upload failed');
            }

            progress.textContent = `Successfully uploaded ${files.length} file(s)`;
            progress.className = 'upload-progress success';

            // Clear input and reload
            fileInput.value = '';
            setTimeout(() => {
                progress.className = 'upload-progress hidden';
                loadFiles(currentPath);
            }, 2000);

        } catch (error) {
            progress.textContent = `Upload failed: ${error.message}`;
            progress.className = 'upload-progress error';
        }
    };
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
