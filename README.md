# Local File Share Service

A simple, no-security web-based file sharing service for local networks.

## Features

- 📁 Browse folders and files
- ⬆️ Upload multiple files
- ⬇️ Download files
- 📱 Responsive design - works on phones, tablets, and computers
- 🚀 Simple setup - no configuration needed

## Installation

1. Install Python 3 (if not already installed):
```bash
sudo apt update
sudo apt install python3 python3-pip
```

2. Install dependencies:
```bash
pip3 install -r requirements.txt
```

## Usage

### Start the server:
```bash
python3 server.py
```

Or make it executable:
```bash
chmod +x server.py
./server.py
```

### Access the service:

- **From the host computer:** http://localhost:8080
- **From other devices on your network:** http://YOUR_IP:8080

To find your IP address:
```bash
hostname -I
```

## Shared Files Location

Files are stored in the `shared_files` directory (created automatically in the same folder as server.py).

## Security Warning

⚠️ **This service has NO authentication or security features!**

- Only use on trusted local networks
- Anyone on your network can upload/download files
- Do not expose to the internet
- Do not share sensitive files

## Stopping the Server

Press `Ctrl+C` in the terminal to stop the server.

## Requirements

- Python 3.6 or higher
- Flask
- Werkzeug

## License

MIT License