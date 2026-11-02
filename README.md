# Instagram Downloader

A lightweight, mobile-friendly Instagram media downloader built with **FastAPI** and **Instaloader**.

Designed for simple, password-protected access with efficient download handling and minimal server resource consumption.

## Features

- Password-protected login.
- Mobile-friendly interface.
- Instagram post, Reel and video URL processing.
- Image and video downloads.
- Concurrent download handling.
- Duplicate download coordination.
- Temporary file management and automatic cleanup.
- Session-based authentication.
- Docker deployment support.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 |
| Web Framework | FastAPI |
| Instagram Processing | Instaloader |
| ASGI Server | Uvicorn |
| Deployment | Docker |
| Frontend | HTML, CSS, JavaScript |

## Project Structure

```text
instadownload/
├── templates/
│   ├── index.html
│   └── login.html
├── main.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .gitignore
└── README.md
```

## Requirements

- Python 3.12+
- pip
- Docker (optional)

## Local Installation

Clone the repository:

```bash
git clone https://github.com/abhilashkrishn/instadownload.git
cd instadownload
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Configuration

Create a `.env` file in the project root:

```env
APP_USER=your_username
APP_PASSWORD=your_password
SESSION_SECRET=your_random_secret
COOKIE_PATH=/
COOKIE_SECURE=false
```

For production deployments:

```env
COOKIE_PATH=/instadown/
COOKIE_SECURE=true
```

**Security:** Never commit `.env` or expose application credentials. Use a strong, randomly generated session secret.

## Run Locally

```bash
uvicorn main:app --host 0.0.0.0 --port 8200
```

Open:

```text
http://127.0.0.1:8200
```

## Docker Deployment

Build the image:

```bash
docker build -t instadownload .
```

Run the container:

```bash
docker run -d \
  --name instadownload \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8200:8200 \
  instadownload
```

## Resource Configuration

The application uses:

- One Uvicorn worker.
- A two-thread download executor.
- Temporary storage for downloaded media.
- Automatic cleanup of old temporary files.

## Important Notes

- Download availability depends on Instagram accessibility and content restrictions.
- Private or restricted content may not be downloadable.
- Use this application responsibly and respect content ownership and applicable terms of service.

## License

No license has been specified yet.