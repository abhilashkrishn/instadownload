# Instagram Downloader

A lightweight, self-hosted Instagram media downloader built with FastAPI and Instaloader. The application provides an authenticated web interface for downloading Instagram posts, reels and TV media.

## Features

- **Instagram Media Downloads** – Download videos and images from public Instagram posts, reels and TV URLs supported by Instaloader.
- **Authentication** – Password-protected access with signed session tokens.
- **Persistent Sessions** – Secure, HTTP-only session cookies with a 30-day validity period.
- **Concurrent Processing** – Supports two simultaneous Instaloader worker tasks.
- **Duplicate Request Handling** – Coordinates concurrent requests for the same shortcode to avoid duplicate downloads.
- **Cancellation Safety** – Keeps background download processing independent of HTTP client disconnections.
- **Temporary Storage** – Stores downloaded media in a temporary application directory.
- **Automatic Cleanup** – Removes stale download directories after 10 minutes when they are not actively in use.
- **Responsive Interface** – Separate HTML templates for the application and login page.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 |
| Web Framework | FastAPI |
| ASGI Server | Uvicorn |
| Instagram Downloader | Instaloader |
| Data Validation | Pydantic |
| Frontend | HTML, CSS, JavaScript |
| Authentication | HMAC-SHA256 signed session tokens |
| Background Processing | ThreadPoolExecutor |
| Containerization | Docker |
| Reverse Proxy | Nginx |

## Project Structure

```text
instadown-fastapi/
├── main.py
├── templates/
│   ├── index.html
│   └── login.html
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── README.md
└── upload.ps1
```

The `.env` file and local development environment are excluded from version control.

## Requirements

- Python 3.12
- Docker (for containerized deployment)
- Git

## Installation

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

## Configuration

Create a `.env` file in the project root.

| Variable | Required | Description |
|---|---|---|
| `APP_USER` | No | Login username. Defaults to `dhanya`. |
| `APP_PASSWORD` | Yes | Application login password. |
| `SESSION_SECRET` | Yes | Secret used to sign session tokens. |
| `COOKIE_PATH` | No | Cookie path. Defaults to `/`. |
| `COOKIE_SECURE` | No | Enables secure cookies when set to `true`. Defaults to `false`. |

Example:

```env
APP_USER=your_username
APP_PASSWORD=your_password
SESSION_SECRET=your_long_random_secret
COOKIE_PATH=/
COOKIE_SECURE=false
```

Both `APP_PASSWORD` and `SESSION_SECRET` are mandatory. The application will not start if either is missing.

Never commit `.env` files or credentials to GitHub.

## Running Locally

Start the application:

```bash
python main.py
```

The application listens on:

```text
http://localhost:8200
```

For development, the application starts Uvicorn with automatic reload enabled.

## Docker Deployment

Build the Docker image:

```bash
docker build -t instadownload:latest .
```

Run the container:

```bash
docker run -d \
  --name instadownload \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8200:8200 \
  instadownload:latest
```

Check container status:

```bash
docker ps
```

View application logs:

```bash
docker logs -f instadownload
```

Stop the container:

```bash
docker stop instadownload
```

Remove the container:

```bash
docker rm instadownload
```

## Nginx Reverse Proxy

The application can operate behind an existing Nginx reverse proxy.

Example configuration for deployment under `/instadown/`:

```nginx
location = /instadown {
    return 301 /instadown/;
}

location /instadown/ {
    proxy_pass http://127.0.0.1:8200/;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Set the corresponding cookie configuration:

```env
COOKIE_PATH=/instadown/
COOKIE_SECURE=true
```

The trailing slash in `proxy_pass` is important because Nginx uses it to remove the `/instadown/` prefix before forwarding requests.

## Supported Instagram URLs

The application extracts shortcodes from these URL formats:

```text
https://www.instagram.com/p/SHORTCODE/
https://www.instagram.com/reel/SHORTCODE/
https://www.instagram.com/reels/SHORTCODE/
https://www.instagram.com/tv/SHORTCODE/
```

The shortcode is passed to Instaloader for media retrieval.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Application interface; requires authentication. |
| GET | `/login` | Login page. |
| POST | `/api/login` | Authenticates credentials and creates a session. |
| GET | `/logout` | Ends the session. |
| POST | `/api/process` | Processes an Instagram URL and initiates or coordinates a download. |
| GET | `/download/{shortcode}` | Retrieves the downloaded media. |

### Processing Request

`POST /api/process`

Request body:

```json
{
  "url": "https://www.instagram.com/p/SHORTCODE/"
}
```

Successful responses include:

- `success`
- `download_url`
- `file_size_mb`
- `file_bytes`

Authentication is required for protected application endpoints.

## Download Processing

The application uses a two-worker thread pool for Instaloader operations.

Concurrency management includes:

- Active reference counting for shortcodes.
- In-flight events for coordinating duplicate requests.
- Background asyncio tasks to isolate download execution from HTTP request cancellation.
- Cleanup after worker completion.
- Protection against deleting directories currently in use.

Downloaded media is stored under the system temporary directory:

```text
fastapi_insta_storage/
└── SHORTCODE/
    ├── media.mp4
    └── media.jpg
```

The exact filenames depend on the media retrieved by Instaloader.

Temporary download directories older than 10 minutes are eligible for cleanup when they are not actively in use.

## Security

- Application access requires authentication.
- Password comparisons use constant-time comparison.
- Session tokens are signed using HMAC-SHA256.
- Session cookies are HTTP-only.
- Cookie security can be enabled for HTTPS deployments.
- Session tokens expire after 30 days.
- Credentials and secrets must remain outside version control.
- The application should be exposed through HTTPS and a reverse proxy rather than exposing its internal port publicly.

## License

No open-source license has currently been specified. All rights remain with the repository owner unless a license is added.