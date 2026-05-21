# Forgensic Deployment Guide from Scratch

This document explains the full deployment process used to move the Forgensic project from a local setup to a live production website on the subdomain `forgery.tanuh.ai` using a Google Cloud VM, Nginx, FastAPI, Firestore, and Cloudinary.

## 1. What was already in the project

The project already had a working backend and frontend. The backend was built with FastAPI, and the frontend was made of static HTML, CSS, and JavaScript files. The project also used Firestore for authentication and history storage, and Cloudinary for image uploads. The main goal of deployment was to host the app publicly on a real domain instead of a temporary local or Render-based setup.

## 2. What the Google Cloud VM was used for

The VM acted as the main server machine. It was used to run the FastAPI backend, serve the frontend through Nginx, and connect the public domain to the application. The VM did not replace Firestore. Firestore continued to handle structured data like authentication and history, while the VM handled the application server.

## 3. First step: connect to the VM

The first step was SSH access to the VM using the IP address, username, and password provided by the project manager.

Command used:

```bash
ssh tanuh@VM_IP
```

After logging in, the system was verified using:

```bash
whoami
pwd
uname -a
```

These commands confirmed the user account, current working directory, and operating system details.

## 4. Prepare the VM

The first step was SSH access to the VM using the IP address, username, and password provided by the project manager. After logging in, the system was verified using commands like `whoami`, `pwd`, and `uname -a` to confirm the user account and operating system.

## 4. Prepare the VM

A dedicated project folder was created inside the home directory so the deployment stayed organized.

Commands used:

```bash
mkdir projects
cd projects
mkdir forgensic
cd forgensic
```

The system was then updated:

```bash
sudo apt update
```

Required packages were installed:

```bash
sudo apt install -y git python3 python3-pip python3-venv
```

These tools were required to clone the repository and run the backend inside an isolated Python environment.

## 5. Clone the GitHub repository

A project folder was created inside the home directory so the work stayed organized. Then the system was updated using `sudo apt update`, and the required tools were installed:

- Git
- Python 3
- pip
- venv

These tools were needed to clone the repo and run the backend in a clean Python environment.

## 5. Clone the GitHub repository

The GitHub repository was cloned into the VM.

Commands used:

```bash
git clone https://github.com/tanuh-bcd/Forgensic-v1.git
cd Forgensic-v1
ls
```

The `ls` command confirmed the repository structure and ensured that both frontend and backend folders were present.

## 6. Set up the backend

The project repository was cloned into the VM using Git. After cloning, the root folder was checked to confirm that both `backend` and `frontend` folders existed. This confirmed that the repo structure was correct and ready for deployment.

## 6. Set up the backend

Inside the backend folder, a Python virtual environment was created.

Commands used:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

After activating the environment, the required Python packages were installed:

```bash
pip install -r requirements.txt
```

The backend structure was checked using:

```bash
ls app
```

The FastAPI application entry point was verified inside `app/main.py`.

## 7. Confirm that the backend works

Inside the `backend` folder, a Python virtual environment was created using `python3 -m venv .venv`. After activating it with `source .venv/bin/activate`, the dependencies were installed using `pip install -r requirements.txt`.

The FastAPI entry point was verified in `app/main.py`, and the backend was started using:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Later, after testing, the backend host was changed to `127.0.0.1` because Nginx would act as the public-facing layer.

## 7. Confirm that the backend works

The FastAPI backend was started manually to confirm that all dependencies and configurations were working correctly.

Command used:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The terminal showed:

```text
Uvicorn running on http://127.0.0.1:8000
```

This confirmed that the backend server was functioning correctly on the VM.

## 8. Install and verify Nginx

The backend startup output showed that Uvicorn was running successfully. This meant the backend code, dependencies, and configuration were all working correctly on the VM.

## 8. Install and verify Nginx

Nginx was installed to serve the frontend publicly and to act as a reverse proxy for the FastAPI backend.

Commands used:

```bash
sudo apt install -y nginx
sudo systemctl status nginx
```

The service status showed:

```text
active (running)
```

which confirmed that Nginx was installed successfully.

## 9. Confirm the domain connection

Nginx was installed on the VM using `sudo apt install -y nginx`. After installation, its status was checked with `sudo systemctl status nginx`, and it was confirmed to be active and running. At this point, the domain could already show the default Nginx welcome page.

## 9. Confirm the domain connection

The browser was opened at `http://forgery.tanuh.ai`, and the Nginx welcome page appeared. This confirmed that DNS was already connected correctly to the VM IP address and that inbound HTTP traffic was working.

## 10. Replace the default Nginx page with the frontend

The default Nginx files in `/var/www/html` were removed, and the frontend files from the project were copied into that folder. After that, refreshing `http://forgery.tanuh.ai` showed the actual website interface instead of the default Nginx page.

## 11. Fix the frontend API URL

The frontend configuration file `frontend/config.js` originally pointed to `http://127.0.0.1:8000`. That works only when the browser is on the same machine, which is not true for public users. The API base URL was changed to `/api` so that the browser sends requests to the public site path, and Nginx forwards those requests internally to the backend.

## 12. Configure Nginx reverse proxy

Nginx was configured so it could do two jobs:

- serve the frontend files
- forward `/api` requests to the FastAPI backend on `127.0.0.1:8000`

This made the app accessible through one domain instead of exposing the backend port directly.

## 13. Test the Nginx configuration

The configuration was checked using `sudo nginx -t`. After it passed successfully, Nginx was restarted so the new settings took effect. This connected the frontend and backend through the same public domain.

## 14. Make the backend permanent

At first, the backend ran only inside a terminal session. That meant it would stop if the terminal closed or the VM restarted. To fix this, a `systemd` service was created for the backend.

The service was added as `/etc/systemd/system/forgensic.service`, then enabled and started using systemd commands. After that, the backend became a permanent service that starts automatically when the VM boots and keeps running in the background.

## 15. Add HTTPS with Certbot

To make the website secure and production-ready, Certbot and the Nginx plugin were installed. Then a certificate was generated for `forgery.tanuh.ai` using Let’s Encrypt. The HTTPS setup also configured automatic HTTP-to-HTTPS redirection.

After this step, the website became accessible through `https://forgery.tanuh.ai` with a secure lock icon in the browser.

## 16. What the final deployment looks like

The final architecture is:

- `https://forgery.tanuh.ai` opens the public website
- Nginx serves the frontend and acts as the reverse proxy
- Nginx forwards `/api` calls to FastAPI
- FastAPI runs as a `systemd` service
- Firestore stores authentication and history data
- Cloudinary handles image uploads

## 17. What to do when GitHub changes later

If the GitHub repository is updated later, the usual workflow is:

- pull the latest code on the VM
- copy updated frontend files to `/var/www/html`
- restart Nginx if the frontend changes
- restart the backend service if backend code changes
- reinstall Python dependencies only if `requirements.txt` changes

This makes future updates simple and repeatable.

## 18. Important notes

- Firestore was not replaced by the VM.
- The VM is for running the application server, not as the main data store.
- The frontend is permanently served by Nginx.
- The backend is permanently managed by systemd.
- HTTPS is now active, so the site is safe to use publicly.

## 19. Final result

The deployment was successful. The project moved from a local/development-style setup to a live production setup on a real domain with proper backend hosting, frontend hosting, reverse proxying, and SSL security.

