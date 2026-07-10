# Knowledge Engine: local Qdrant server

The recommended v1 runtime setup is a separate local Qdrant server instead of embedded `qdrant-client` storage.

Why:

- the agent can keep running while scripts inspect/reindex Qdrant;
- no embedded local-storage file lock;
- `knowledge_index_status.py` and `knowledge_index_all.py` can run while Textual is live;
- still local-only when bound to `127.0.0.1`.

## Start Qdrant

Install Docker Desktop or another Docker-compatible runtime, then from the repo root run:

```powershell
docker compose -f docker-compose.qdrant.yml up -d
```

Check it:

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:6333/collections', timeout=3).read().decode())"
```

## Configure the knowledge engine

`config/knowledge.yaml` should use:

```yaml
qdrant:
  enabled: true
  mode: http
  url: http://localhost:6333
  timeout_seconds: 2.0
```

Keep the BGE-M3 settings unchanged:

```yaml
embedding_backend: sentence_transformers
embedding_model: C:/models/bge-m3
embedding_device: cpu
embedding_local_files_only: true
vector_size: 1024
```

## Reindex into the server

The embedded local Qdrant data is not automatically migrated. Reindex from source data:

```powershell
python scripts/knowledge_index_all.py --write-qdrant
python scripts/knowledge_index_status.py
```

Expected point counts are approximately:

- `agent_capability_router`: 2
- `agent_chat_history`: current number of chat-history records
- `agent_long_term_memory`: current memory count, possibly 0

## Important security note

The compose file binds Qdrant to `127.0.0.1` only. Do not expose Qdrant directly through Caddy/Tailscale unless you add proper authentication and understand that it contains personal chat/memory data.

## Stop Qdrant

```powershell
docker compose -f docker-compose.qdrant.yml down
```

Data remains under:

```text
runtime/knowledge/qdrant_server/
```
