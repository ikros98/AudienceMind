# Graphiti Compatibility Service

This deployment package supports two modes:

- local laptop mode: Neo4j and the Graphiti compatibility service run inside this repo on your machine
- remote host mode: the same service runs on a server and is consumed over SSH port forwarding

## What This Stack Includes

- `Neo4j 5.26` in Docker Compose
- the FastAPI compatibility service from `backend/app/graphiti_service/`
- file-backed graph metadata under `GRAPHITI_SERVICE_DATA_DIR`
- `graphiti-core` using:
  - Neo4j at `bolt://127.0.0.1:7687`
  - an OpenAI-compatible extraction model
  - an OpenAI-compatible embedding model
  - optional reranker settings
  - a client override that can force provider-side reasoning off

## Environment Files

- root `.env`: main app settings and the Graphiti client endpoint used by PersonaGraph
- `deploy/graphiti/local.env.example`: local Graphiti service settings for this laptop
- `deploy/graphiti/service.env.example`: remote-server Graphiti service settings

Important variables:

- `GRAPHITI_BASE_URL`: where the main app reaches the compatibility service
- `GRAPHITI_API_KEY`: bearer token shared between the app and the compatibility service
- `GRAPHITI_EMBEDDING_MODEL`: embedding model for Graphiti, now defaulted to `bge-large-en-v1.5`
- `NEO4J_HEAP_INITIAL_SIZE`, `NEO4J_HEAP_MAX_SIZE`, `NEO4J_PAGECACHE_SIZE`: Neo4j memory tuning knobs

## Local Laptop Setup

Use this when the graph stack should live on your laptop while the LLM can still point at another endpoint such as Runpod vLLM.

### 1. Configure the main app

Copy and edit the root `.env`:

```bash
cp .env.example .env
```

For local Graphiti development, the key settings are:

```env
GRAPH_BACKEND=graphiti
GRAPHITI_BASE_URL=http://127.0.0.1:8182
GRAPHITI_API_KEY=replace_with_graphiti_bearer_token
OUTPUT_LANGUAGE=en
```

Your main LLM remains controlled by the repo root `.env`:

```env
LLM_API_KEY=your_openrouter_api_key_here
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3.6-plus:free
```

### 2. Configure the local Graphiti service

Initialize the local files:

```bash
npm run graphiti:setup
```

Then edit `deploy/graphiti/local.env`.

Useful defaults:

- `GRAPHITI_SERVICE_PORT=8182`
- `GRAPHITI_EMBEDDING_MODEL=bge-large-en-v1.5`
- `GRAPHITI_LLM_TIMEOUT_SECONDS=300`
- `GRAPHITI_LLM_MAX_TOKENS=4096`
- `GRAPHITI_LLM_MAX_RETRIES=1`
- `GRAPHITI_SEARCH_RERANKER=rrf`
- `NEO4J_HEAP_INITIAL_SIZE=512M`
- `NEO4J_HEAP_MAX_SIZE=1G`
- `NEO4J_PAGECACHE_SIZE=512M`

Important note:

- the local default here now inherits the OpenRouter chat endpoint from the repo root `.env`
- you only need to place your OpenRouter key once in the root `.env` under `LLM_API_KEY`
- embeddings can still stay on a separate dedicated endpoint if your chat model does not serve embeddings
- if you switch Graphiti to a slower provider path, you should expect more batches and lower ingest throughput; faster dedicated inference should still support fewer batches and materially quicker graph extraction

If your main chat endpoint also serves embeddings, you can leave:

```env
GRAPHITI_EMBEDDER_BASE_URL=
GRAPHITI_EMBEDDER_API_KEY=
```

If embeddings live elsewhere, set them explicitly.

### 3. Start the local graph stack

Start local Neo4j:

```bash
npm run graphiti:neo4j:up
```

Start the local compatibility service in a second terminal:

```bash
npm run graphiti:service
```

Health check:

```bash
npm run graphiti:health
```

Expected local ports:

- Neo4j HTTP: `127.0.0.1:7474`
- Neo4j Bolt: `127.0.0.1:7687`
- Graphiti compatibility service: `127.0.0.1:8182`

Then start the app itself in a third terminal:

```bash
npm run dev
```

If `npm run graphiti:service` says the service is already running on `127.0.0.1:8182`, that is fine. It now exits cleanly instead of crashing.

## Local Layout

```text
deploy/graphiti/local.env
deploy/graphiti/local-data/
deploy/graphiti/neo4j/
backend/app/graphiti_service/
```

## Sizing Guidance

### Laptop / local development

Use the conservative defaults from `deploy/graphiti/local.env`:

- `NEO4J_HEAP_INITIAL_SIZE=512M`
- `NEO4J_HEAP_MAX_SIZE=1G`
- `NEO4J_PAGECACHE_SIZE=512M`

These are safe for developer machines and avoid the boot failures caused by oversized Neo4j memory settings.

### Dedicated server / higher-throughput deployment

Use `deploy/graphiti/service.env.example` as the starting point and scale based on host RAM.

Practical guidance:

- give Neo4j enough heap for query execution, but do not starve the OS and Python service
- reserve meaningful page cache for relationship-heavy traversals
- leave headroom for Docker, Graphiti, and your model client traffic

Reasonable starting points:

- 16 GB host: `1G / 4G / 2G`
- 32 GB host: `2G / 8G / 4G`
- 64 GB host: `4G / 16G / 8G`

That format is:

```text
heap initial / heap max / pagecache
```

Then tune further with real workloads.

## Remote Host Setup

Use this when Graphiti should run on a server and the app should reach it over SSH port forwarding.

### Assumptions

- Ubuntu or similar Linux host
- Docker with Compose plugin installed
- Python 3.11+
- an OpenAI-compatible chat endpoint available
- an embedding endpoint available if the chat endpoint does not expose embeddings

### Suggested layout

```text
/opt/PersonaGraph
/opt/personagraph-graphiti
```

The systemd template assumes:

- repo backend working directory: `/opt/PersonaGraph/backend`
- repo backend virtualenv: `/opt/PersonaGraph/backend/.venv`
- service env file: `/opt/personagraph-graphiti/service.env`

### Setup

1. Create the deployment directory and copy the env template:

```bash
sudo mkdir -p /opt/personagraph-graphiti
sudo cp /opt/PersonaGraph/deploy/graphiti/service.env.example /opt/personagraph-graphiti/service.env
sudo chown -R "$USER":"$USER" /opt/personagraph-graphiti
```

2. Edit `/opt/personagraph-graphiti/service.env`:

- set a real `GRAPHITI_SERVICE_BEARER_TOKEN`
- set a real `NEO4J_PASSWORD`
- set the chat endpoint in `GRAPHITI_LLM_*`
- set the embedding endpoint in `GRAPHITI_EMBEDDER_*`
- keep `GRAPHITI_SEARCH_RERANKER=rrf` unless you have a reliable cross-encoder path

3. Start Neo4j:

```bash
cd /opt/PersonaGraph/deploy/graphiti
set -a
source /opt/personagraph-graphiti/service.env
set +a
docker compose up -d
```

If your host rejects Docker bind mounts under `/opt` with a read-only filesystem error, run the compose stack from a user-writable directory instead:

```bash
mkdir -p ~/personagraph-graphiti-compose
cp /opt/PersonaGraph/deploy/graphiti/docker-compose.yml ~/personagraph-graphiti-compose/docker-compose.yml
cd ~/personagraph-graphiti-compose
set -a
source /opt/personagraph-graphiti/service.env
set +a
docker compose up -d
```

4. Install the service dependencies:

```bash
cd /opt/PersonaGraph/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r /opt/PersonaGraph/deploy/graphiti/requirements.txt
```

5. Install the systemd unit:

```bash
sudo cp /opt/PersonaGraph/deploy/graphiti/systemd.service.template /etc/systemd/system/personagraph-graphiti.service
sudo systemctl daemon-reload
sudo systemctl enable personagraph-graphiti
sudo systemctl start personagraph-graphiti
sudo systemctl status personagraph-graphiti
```

6. Verify health on the server:

```bash
curl http://127.0.0.1:8181/health
```

## SSH Tunnel From Your Laptop

Example tunnel:

```bash
ssh -N -L 8181:127.0.0.1:8181 -i ~/.ssh/ndeamonrd.pem paperspace@184.105.157.30
```

Then the local app can target:

```text
GRAPHITI_BASE_URL=http://127.0.0.1:8181
```

## Authenticated Smoke Test

Replace `TOKEN` with `GRAPHITI_SERVICE_BEARER_TOKEN`.

Create a graph:

```bash
curl -X POST http://127.0.0.1:8182/graphs \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"PersonaGraph test graph"}'
```

Set ontology:

```bash
curl -X PUT http://127.0.0.1:8182/graphs/personagraph_example/ontology \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d @ontology.json
```

Ingest one episode:

```bash
curl -X POST http://127.0.0.1:8182/graphs/personagraph_example/episodes \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "episodes": [
      {
        "name": "chunk-1",
        "episode_body": "Ralph Lauren launched a new collection.",
        "source_description": "seed document"
      }
    ]
  }'
```

## Notes

- The compatibility service maps PersonaGraph `graph_id` directly to Graphiti `group_id`.
- Graph metadata, ontology JSON, and alias maps are stored on disk under `GRAPHITI_SERVICE_DATA_DIR`.
- `rrf` is the default search reranker because it is the safest option across mixed OpenAI-compatible providers.
- If you want to maximize server-side throughput later, tune the LLM serving stack first. The Graphiti service itself is lightweight compared with long extraction and embedding requests.
