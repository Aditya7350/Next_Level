# 🚀 Deploying AI Interview Platform to Render

This guide provides instructions to make the **AI Interview Platform** live on [Render](https://render.com).

---

## 📋 Table of Contents
1. [Important Prerequisite: MongoDB Atlas IP Access](#1-important-prerequisite-mongodb-atlas-ip-access)
2. [Deployment Option A: Render Blueprint (Recommended - 1 Click)](#2-deployment-option-a-render-blueprint-recommended)
3. [Deployment Option B: Manual Web Service & Static Site](#3-deployment-option-b-manual-setup-in-render-dashboard)
4. [Deployment Option C: Single Unified Service (Free Tier All-in-One)](#4-deployment-option-c-single-unified-service)
5. [Environment Variables Reference](#5-environment-variables-reference)
6. [Post-Deployment Verification](#6-post-deployment-verification)

---

## 1. Important Prerequisite: MongoDB Atlas IP Access

Render uses dynamic IP addresses that change over time. If your MongoDB Atlas cluster only allows your local IP, Render will not be able to connect.

1. Go to [MongoDB Atlas](https://cloud.mongodb.com/).
2. In the left navigation, click **Network Access** (under Security).
3. Click **Add IP Address**.
4. Click **Allow Access from Anywhere** (`0.0.0.0/0`).
5. Click **Confirm**.

---

## 2. Deployment Option A: Render Blueprint (Recommended)

This repository includes a pre-configured [`render.yaml`](file:///d:/AI_Interview_RAG-main/render.yaml) file. Render reads this file and automatically configures both the **Backend Web Service** and the **Frontend Static Site**, and links their URLs together.

### Step-by-Step:
1. **Push your code to GitHub**:
   ```bash
   git add .
   git commit -m "Configure project for Render deployment"
   git push origin main
   ```
2. Open your [Render Dashboard](https://dashboard.render.com/).
3. Click **New +** in the top right, then select **Blueprint**.
4. Connect your GitHub repository (`AI_Interview_RAG-main`).
5. Render will automatically detect `render.yaml` and create two services:
   - `ai-interview-backend` (FastAPI + AI Proctoring + RAG Engine)
   - `ai-interview-frontend` (React + Vite)
6. In the Blueprint setup form, enter your secret environment variables:
   - `OPENAI_API_KEY`: Your OpenAI API key (`sk-...`).
   - `MONGODB_URI`: Your MongoDB connection string.
7. Click **Apply**.
8. Render will build both services and provide you with live URLs:
   - **Frontend:** `https://ai-interview-frontend.onrender.com`
   - **Backend API:** `https://ai-interview-backend.onrender.com`

---

## 3. Deployment Option B: Manual Setup in Render Dashboard

If you prefer to create the services manually without Blueprints:

### Step 1: Deploy Backend Web Service
1. In Render Dashboard, click **New +** → **Web Service**.
2. Connect your GitHub repository.
3. Configure settings:
   - **Name:** `ai-interview-backend`
   - **Region:** Choose the region closest to you (e.g., Singapore, Frankfurt, Oregon).
   - **Branch:** `main`
   - **Root Directory:** Leave blank (root).
   - **Runtime:** `Python 3`
   - **Build Command:**
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command:**
     ```bash
     uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
     ```
   - **Health Check Path:** `/health`
4. Add **Environment Variables**:
   | Key | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.12.8` |
   | `ENVIRONMENT` | `production` |
   | `OPENAI_API_KEY` | `sk-...` |
   | `MONGODB_URI` | `mongodb+srv://...` |
   | `ADMIN_EMAIL` | `admin@interview.ai` |
   | `ADMIN_PASSWORD` | `AdminPass123` |
   | `PROCTOR_MAX_WARNINGS` | `5` |
   | `PROCTOR_WARN_COOLDOWN` | `20.0` |
5. Click **Deploy Web Service** and copy your backend URL (e.g., `https://ai-interview-backend.onrender.com`).

### Step 2: Deploy Frontend Static Site
1. In Render Dashboard, click **New +** → **Static Site**.
2. Connect the same repository.
3. Configure settings:
   - **Name:** `ai-interview-frontend`
   - **Branch:** `main`
   - **Root Directory:** `Frontend`
   - **Build Command:**
     ```bash
     npm install && npm run build
     ```
   - **Publish Directory:** `dist`
4. In **Redirects / Rewrites**, click **Add Rewrite Rule**:
   - **Source:** `/*`
   - **Destination:** `/index.html`
   - **Action:** `Rewrite`
5. Under **Environment Variables**, add:
   | Key | Value |
   |---|---|
   | `VITE_API_URL` | `https://ai-interview-backend.onrender.com/api/v1` (replace with your actual backend URL) |
6. Click **Deploy Static Site**.

---

## 4. Deployment Option C: Single Unified Service

If you want to host **both Frontend and Backend together in a single Render Web Service**:

1. Click **New +** → **Web Service**.
2. Configure:
   - **Runtime:** `Python 3`
   - **Build Command:**
     ```bash
     chmod +x render-build.sh && ./render-build.sh
     ```
   - **Start Command:**
     ```bash
     uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
     ```
3. Set your environment variables (`MONGODB_URI`, `OPENAI_API_KEY`, etc.).
4. The backend will automatically build and host the React frontend at the root `/` and the API at `/api/v1` with zero CORS configuration needed!

---

## 5. Environment Variables Reference

See [`.env.example`](file:///d:/AI_Interview_RAG-main/.env.example) for a complete template:

| Variable | Description | Default |
|---|---|---|
| `MONGODB_URI` | MongoDB Atlas connection string | Required |
| `OPENAI_API_KEY` | OpenAI API key for evaluation | Required |
| `ADMIN_EMAIL` | Administrator login email | `admin@interview.ai` |
| `ADMIN_PASSWORD` | Administrator login password | `AdminPass123` |
| `ADMIN_NAME` | Administrator display name | `Recruiter Admin` |
| `PROCTOR_MAX_WARNINGS` | Maximum warnings before early conclusion | `5` |
| `PROCTOR_WARN_COOLDOWN`| Minimum seconds between warnings | `20.0` |
| `PROCTOR_DEVICE_CONF` | Threshold for detecting phones/devices | `0.08` |
| `VITE_API_URL` | Frontend API target URL (Static Site only) | `/api/v1` |

---

## 6. Post-Deployment Verification

Once Render finishes deploying:

1. **Verify Backend Health:**
   - Open: `https://your-backend.onrender.com/health`
   - Expected Response: `{"status": "ok"}`
2. **Test Candidate Flow:**
   - Open your frontend URL: `https://your-frontend.onrender.com`
   - Register or sign in with candidate credentials (`adityasarode1215@gmail.com` / `Nokia@124` or create a new account).
   - Upload a resume and start an interview.
   - Verify camera checks badge: `● Camera checks on`.
3. **Test Recruiter Admin Portal:**
   - Open: `https://your-frontend.onrender.com/#/admin-login`
   - Log in with `admin@interview.ai` / `AdminPass123`.
   - Verify candidate dossiers, scores, and integrity reports load correctly.
