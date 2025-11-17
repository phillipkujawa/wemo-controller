# Quick Deploy Guide - Choose Your Option

Your backend is ready to deploy! Choose the easiest option for you:

## Option 1: Railway.app (Recommended - 5 minutes)

### Step 1: Login to Railway
```bash
cd /Users/phillip.kujawa/wemo-controller
railway login
```
This will open your browser to authenticate.

### Step 2: Initialize and Deploy
```bash
railway init
railway up
```

### Step 3: Add Environment Variable
```bash
railway variables set GOVEE_API_KEY=7c91d5cc-26c7-42fc-a10f-b177eba5c715
```

### Step 4: Get Your URL
```bash
railway domain
```
Copy the URL (e.g., `https://your-app.railway.app`)

### Step 5: Update Frontend
Edit `index.html` line 292:
```javascript
const API_BASE = "https://your-app.railway.app";  // Replace with your Railway URL
```

---

## Option 2: Render.com (No CLI needed - 3 minutes)

### Step 1: Push to GitHub
```bash
cd /Users/phillip.kujawa/wemo-controller
gh auth login
gh repo create wemo-controller --public --source=. --remote=origin --push
```

### Step 2: Go to Render.com
1. Visit https://render.com and sign in
2. Click "New +" → "Web Service"
3. Connect your GitHub account and select `wemo-controller` repo

### Step 3: Configure Service
- **Name**: wemo-govee-controller
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step 4: Add Environment Variable
- Click "Environment"
- Add: `GOVEE_API_KEY` = `7c91d5cc-26c7-42fc-a10f-b177eba5c715`

### Step 5: Deploy
- Click "Create Web Service"
- Wait for deployment (~2 minutes)
- Copy your URL (e.g., `https://wemo-govee-controller.onrender.com`)

### Step 6: Update Frontend
Edit `index.html` line 292:
```javascript
const API_BASE = "https://wemo-govee-controller.onrender.com";  // Replace with your Render URL
```

---

## Option 3: Fly.io (Fast - 4 minutes)

### Step 1: Install and Login
```bash
curl -L https://fly.io/install.sh | sh
fly auth login
```

### Step 2: Launch App
```bash
cd /Users/phillip.kujawa/wemo-controller
fly launch --name wemo-govee-controller --region sea
```
Say "Yes" to deploy, "No" to Redis

### Step 3: Set Secret
```bash
fly secrets set GOVEE_API_KEY=7c91d5cc-26c7-42fc-a10f-b177eba5c715
```

### Step 4: Get URL
Your URL will be: `https://wemo-govee-controller.fly.dev`

### Step 5: Update Frontend
Edit `index.html` line 292:
```javascript
const API_BASE = "https://wemo-govee-controller.fly.dev";
```

---

## Option 4: Vercel (Alternative - 5 minutes)

### Step 1: Install Vercel CLI
```bash
npm install -g vercel
```

### Step 2: Deploy
```bash
cd /Users/phillip.kujawa/wemo-controller
vercel --prod
```

### Step 3: Add Environment Variable in Dashboard
1. Go to https://vercel.com/dashboard
2. Select your project
3. Settings → Environment Variables
4. Add: `GOVEE_API_KEY` = `7c91d5cc-26c7-42fc-a10f-b177eba5c715`

### Step 4: Redeploy
```bash
vercel --prod
```

---

## After Deployment

### Test Your Backend
Replace `YOUR_URL` with your deployed URL:
```bash
curl https://YOUR_URL/govee/devices
```

### Open Your Frontend
```bash
open index.html
```

Or serve it locally:
```bash
python -m http.server 8080
# Then open http://localhost:8080
```

---

## Troubleshooting

### Backend not responding?
- Check logs: `railway logs` or check Render/Fly dashboard
- Verify GOVEE_API_KEY is set correctly
- Make sure port is set to `$PORT` in start command

### Frontend not connecting?
- Check browser console for CORS errors
- Verify API_BASE URL in index.html is correct
- Make sure URL starts with `https://` not `http://`

### MQTT not connecting?
- Check backend logs for "MQTT: Connected successfully"
- Verify GOVEE_API_KEY is correct
- MQTT connection may take 10-30 seconds to establish

---

## What You Get

✅ **Real-time Updates**: Device state changes push to browser instantly via SSE
✅ **Govee Events**: MQTT subscription for device events (water low, presence, etc.)
✅ **Auto Reconnect**: Frontend automatically reconnects if connection drops
✅ **HTTPS**: All platforms provide free SSL certificates
✅ **24/7 Uptime**: Backend stays running (Railway/Render free tier may sleep after inactivity)

Enjoy your event-driven smart home controller! 🎉
