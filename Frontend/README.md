# AI Interview UI (React)

Vite + React front end for your FastAPI interview backend. Flow: sign in, set up (role, resume, device check),
interview room (Aria asks aloud, you answer by voice or typing), results report.

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
```

Start your backend on port 8000. In dev, Vite proxies `/api/*` to `http://localhost:8000`, so no CORS setup is
needed while developing. Change the target in `vite.config.js` if needed.

The API base is `/api/v1` by default (your `main.py` mounts the router there). To point at another server:

```bash
VITE_API_URL=https://api.example.com/api/v1 npm run build
```

## Before deploying

- **CORS:** if the UI and API live on different origins, add `CORSMiddleware` to `main.py` with the UI origin.
- **Duplicate routes:** `main.py` includes `api_router` twice (with and without the `/api/v1` prefix). Remove one.
- **Voice:** speech recognition uses the browser's Web Speech API (Chrome and Edge). Other browsers fall back to
  typing. For production-quality voice, swap in a server-side speech-to-text/text-to-speech service.

## Settings (`src/config.js`)

- `SHOW_FEEDBACK`: show Aria's feedback after each answer (practice mode). Turn off for real hiring interviews.
- `DEFAULT_ADAPTIVE`: default for the "adaptive questions" switch.

## Where things are

| File | Purpose |
|---|---|
| `src/api.js` | All backend calls and token handling |
| `src/screens/Room.jsx` | Interview room: start, speak, listen, submit, next question |
| `src/screens/Setup.jsx` | Resume upload, job description, options, camera and mic check |
| `src/screens/Report.jsx` | Results from the final `/answer` response |
| `src/speech.js`, `src/devices.js` | Voice input and output, camera and mic |
