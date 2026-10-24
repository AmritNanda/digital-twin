# Strategic Intelligence System MVP (Digital Twin)

An evidence-backed decision workspace that builds a private company source from documents, tests business options under uncertainty, and records how each recommendation was reached.

---

## What the System Does

1. **Ingests Company Knowledge**: Upload up to five documents (PDF, DOCX, CSV, TXT, MD; 20 MB each and 50 MB per case) or describe the business context in the prompt.
2. **Builds a Living Digital Twin**: The Understanding Agent parses entities (Company, Product, Segments, Competitors, Constraints, Objectives, and Financial Parameters) into an in-memory structured state.
3. **Plans & Researches**: The Planner identifies high-impact information gaps; the Research Agent gathers evidence (via Tavily/SerpAPI or realistic fixtures) and embeds them into ChromaDB.
4. **Formulates Competing Strategies**: The Strategy Agent proposes distinct hypotheses with price points, target segments, and go-to-market channels.
5. **Simulates via Monte Carlo**: The Simulation Agent runs 5,000 statistical draws per hypothesis modeling price elasticity, customer acquisition cost (CAC), fixed/variable costs, and demand distributions (P10/P50/P90).
6. **Adversarial Stress-Testing**: The Devil's Advocate Agent actively attempts to disprove the leading hypothesis, attacking weak assumptions and triggering targeted research replanning when critical flaws are found.
7. **Synthesizes Final Decision Package**: Produces an actionable recommendation complete with confidence scoring, cited supporting & counter-evidence, assumption disclosures, what would change the decision, and suggested real-world experiments.

---

## Architecture

- **Backend**: Python 3.13, [FastAPI](https://fastapi.tiangolo.com/), [LangGraph](https://github.com/langchain-ai/langgraph) state machine.
- **Frontend**: React, TypeScript, Vite, Motion, custom CSS and SVG. The case page has a source drawer, versioned run ledger, approval checkpoint, discussion composer, and PDF/CSV/JSON exports.
- **Private workspace**: SQLite users, sessions, cases, documents, runs, messages and audit events. LangGraph SQLite checkpoints resume the approval pause.
- **Vector Store**: [ChromaDB](https://www.trychroma.com/) with local SentenceTransformers embeddings (`all-MiniLM-L6-v2`, runs locally without an API key).
- **LLM**: Any OpenAI-compatible provider (OpenAI, Groq, Together, Ollama, etc.).
- **Search Provider**: Tavily AI search or SerpAPI with seamless fallback to realistic fixtures (`DEMO_MODE=true` or when offline).

---

## Quick Start

### 1. Configure Environment
Copy the example environment file and configure your API keys:
```bash
cp .env.example .env
```
Open `.env` and set your LLM configuration:
```ini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=your-gemini-api-key-here
LLM_MODEL=gemini-3.5-flash
STRATEGY_DEMO_EMAIL=founder@example.com
STRATEGY_DEMO_PASSWORD=replace-with-a-long-unique-password

# Optional: Tavily or SerpAPI for live web research (uses realistic demo fixtures if omitted)
TAVILY_API_KEY=
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build && cd ..
```

### 3. Run the Server
```bash
python backend/main.py
```
Open **[http://localhost:8000](http://localhost:8000)** and sign in with the account configured above. For frontend development, run `npm run dev` from `frontend/`; Vite proxies `/api` to FastAPI on port 8000.

---

## Sample Demo Flow

1. **Option A (With Documents)**:
   Upload company context and financial guidelines. Document-only submission extracts the source twin and then waits for a decision question.
2. **Option B (Zero-Document Demo Prompt)**:
   Paste a strategic scenario directly into the prompt box, for example:
   > *"Company: Nila Home. Product: Modular kitchen storage starter kit. Unit cost: ₹180. Fixed cost: ₹45,000/month. Marketing budget: ₹3,00,000. Question: What price point and distribution channel should we launch with in India?"*
3. Submit the question. Inspect the run ledger, review consequential assumptions, and approve the final simulation. Discuss the result or propose a new CAC/elasticity scenario to create another run.

The external research fixture mode is labeled in the result and exports. The PDF parser needs extractable text; scanned PDFs require a text-based copy. Each analysis uses a retrieved subset of indexed passages and shows which passages were used. The legacy `/api/upload` and `/api/case` endpoints remain available for older clients.

## Checks

Run backend API checks with `PYTHONPATH=backend python -m pytest tests/test_workspace_api.py -q -p no:cacheprovider`, then build the frontend with `cd frontend && npm run build`.

---

## Configuration Reference

| Environment Variable | Description | Default |
|---|---|---|
| `LLM_BASE_URL` | Base URL for OpenAI-compatible LLM endpoint | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API key for LLM provider | `""` |
| `LLM_MODEL` | LLM model name | `gpt-4o-mini` |
| `LLM_TIMEOUT_SECONDS` | Per-attempt LLM request timeout | `45` |
| `LLM_MAX_RETRIES` | Retries after an LLM request failure | `1` |
| `LLM_REASONING_EFFORT` | Reasoning effort for Gemini requests | `low` |
| `EMBEDDING_MODEL` | Local sentence-transformers model | `all-MiniLM-L6-v2` |
| `TAVILY_API_KEY` | Tavily API key for live web search | `""` |
| `SERPAPI_KEY` | SerpAPI key (secondary search provider) | `""` |
| `DEMO_MODE` | Force pre-baked fixture data for search | `false` |
| `PORT` | FastAPI server port | `8000` |
| `CASE_TIMEOUT_SECONDS` | Maximum allowed runtime per decision case | `300` |

---

## License
MIT
