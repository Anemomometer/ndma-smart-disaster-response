# Cloud Hosting & Deployment Guide
## NDMA Smart Disaster Response Coordination System

Because this application uses **FastAPI** with an **embedded in-process database (DuckDB)**, it is lightweight, self-contained, and requires **no external database server configuration**.

Below are the 4 best ways to host this project, ranging from a **free permanent cloud URL** to an **instant 30-second live demo link**.

---

## 🏆 Option 1: Render.com (Recommended — 100% Free Cloud Hosting)

Render provides a generous free tier for Python web services with automatic HTTPS (`https://your-app-name.onrender.com`).

### Step-by-Step Instructions:

1. **Push your code to GitHub**:
   - Create a new repository on [GitHub](https://github.com/) (e.g., `ndma-disaster-response`).
   - In your local project folder (`d:\DBMS DA`), run:
     ```bash
     git init
     git add .
     git commit -m "Initial commit: NDMA Disaster Response System"
     git branch -M main
     git remote add origin https://github.com/<your-username>/ndma-disaster-response.git
     git push -u origin main
     ```

2. **Deploy on Render**:
   - Go to [Render Dashboard](https://dashboard.render.com/) and sign in with GitHub.
   - Click **"New +"** and select **"Web Service"**.
   - Select your `ndma-disaster-response` repository.
   - Configure the settings:
     - **Name**: `ndma-disaster-response` (or any custom name)
     - **Region**: Nearest to you (e.g., `Singapore` or `Frankfurt`)
     - **Branch**: `main`
     - **Runtime**: `Python 3`
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`
     - **Instance Type**: Select **Free**
   - Click **"Create Web Service"**.

3. **Done!**
   - In 2–3 minutes, your application will be live at:
     `https://ndma-disaster-response.onrender.com`

---

## ⚡ Option 2: Railway.app (Fastest Cloud Deployment)

Railway auto-detects Python and deploys in under 60 seconds.

1. Go to [Railway.app](https://railway.app/) and login with GitHub.
2. Click **"New Project"** -> **"Deploy from GitHub repo"**.
3. Select your repository.
4. Click **"Deploy Now"**.
5. Go to **Settings** -> **Networking** -> Click **"Generate Domain"**.
6. Your live URL will be ready immediately (e.g. `https://ndma-production.up.railway.app`).

---

## 🤗 Option 3: Hugging Face Spaces (Free 16GB RAM Cloud Container)

Hugging Face Spaces offers a completely free Docker/Python container environment that never spins down on academic accounts.

1. Go to [Hugging Face Spaces](https://huggingface.co/spaces).
2. Click **"Create new Space"**.
3. Space name: `ndma-disaster-system`, License: `mit`, Select **Docker** (Blank).
4. Clone the space repo or upload your project files (including the provided `Dockerfile`).
5. Hugging Face will automatically build and run the container on port 8000!

---

## 🚀 Option 4: Instant 30-Second Public Link from Your Laptop (No Cloud Account Needed)

If you have a project evaluation, viva, or demo **right now** and need a public link to share without pushing to GitHub or signing up for cloud hosting:

### Using Localtunnel (Free, No Sign-up):
1. Keep your server running locally (`python run_server.py`).
2. Open a second PowerShell terminal and run:
   ```bash
   npx -y localtunnel --port 8000
   ```
3. It will output a public URL like:
   `your url is: https://rapid-disaster-rescue.loca.lt`
4. Anyone on the internet can open this link and interact with your live application!

### Using Cloudflare Tunnel (Free, Permanent, No Sign-up):
```bash
npx -y untun@latest tunnel 8000
```
It gives an instant secure `https://*.trycloudflare.com` URL that tunnels directly to your local FastAPI server.
