# PersonaGraph Frontend

React + Vite frontend for the active PersonaGraph workflow:

- `Graph`
- `Setup`
- `Simulate`
- `Report`
- `Interact`

## Local Run

```bash
npm install
npm run dev
```

The dev server defaults to `http://localhost:3020`.

Set `VITE_API_BASE_URL` if the backend is not running on `http://localhost:8020`.

## Build

```bash
npm run build
```

## Container Run

The frontend image is defined in `frontend/Dockerfile`. The full stack is defined in `../docker-compose.yml`.
