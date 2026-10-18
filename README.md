# Strategic Intelligence System MVP (Digital Twin)

An autonomous, evidence-backed strategic decision intelligence system that models a company and its market to evaluate business moves (pricing, channels, product launches) under uncertainty.

---

## What the System Does

1. **Ingests Company Knowledge**: Upload a document (PDF, DOCX, CSV, TXT, MD) or describe the business context in the prompt.
2. **Builds a Living Digital Twin**: The Understanding Agent parses entities (Company, Product, Segments, Competitors, Constraints, Objectives, and Financial Parameters) into an in-memory structured state.
3. **Plans & Researches**: The Planner identifies high-impact information gaps; the Research Agent gathers evidence (via Tavily/SerpAPI or realistic fixtures) and embeds them into ChromaDB.
4. **Formulates Competing Strategies**: The Strategy Agent proposes distinct hypotheses with price points, target segments, and go-to-market channels.
5. **Simulates via Monte Carlo**: The Simulation Agent runs 5,000 statistical draws per hypothesis modeling price elasticity, customer acquisition cost (CAC), fixed/variable costs, and demand distributions (P10/P50/P90).
6. **Adversarial Stress-Testing**: The Devil's Advocate Agent actively attempts to disprove the leading hypothesis, attacking weak assumptions and triggering targeted research replanning when critical flaws are found.
7. **Synthesizes Final Decision Package**: Produces an actionable recommendation complete with confidence scoring, cited supporting & counter-evidence, assumption disclosures, what would change the decision, and suggested real-world experiments.

---

## Architecture

- **Backend**: Python 3.13, [FastAPI](https://fastapi.tiangolo.com/), [LangGraph](https://github.com/langchain-ai/langgraph) state machine.
- **Frontend**: Clean Vanilla JavaScript/CSS/HTML dark-mode UI with live Server-Sent Events (SSE) streaming, interactive evidence drawer, and simulation breakdown.
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
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini

# Optional: Tavily or SerpAPI for live web research (uses realistic demo fixtures if omitted)
TAVILY_API_KEY=
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Run the Server
```bash
python backend/main.py
```
Open your browser at **[http://localhost:8000](http://localhost:8000)**.

---

## Sample Demo Flow

1. **Option A (With Document)**:
   Upload a file containing company context or financial guidelines.
2. **Option B (Zero-Document Demo Prompt)**:
   Paste a strategic scenario directly into the prompt box, for example:
   > *"Company: Nila Home. Product: Modular kitchen storage starter kit. Unit cost: ₹180. Fixed cost: ₹45,000/month. Marketing budget: ₹3,00,000. Question: What price point and distribution channel should we launch with in India?"*
3. Click **Start Strategic Analysis** and watch the agents build the digital twin, run simulations, stress-test hypotheses, and produce the final decision package in real time.

---

## Configuration Reference

| Environment Variable | Description | Default |
|---|---|---|
| `LLM_BASE_URL` | Base URL for OpenAI-compatible LLM endpoint | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API key for LLM provider | `""` |
| `LLM_MODEL` | LLM model name | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | Local sentence-transformers model | `all-MiniLM-L6-v2` |
| `TAVILY_API_KEY` | Tavily API key for live web search | `""` |
| `SERPAPI_KEY` | SerpAPI key (secondary search provider) | `""` |
| `DEMO_MODE` | Force pre-baked fixture data for search | `false` |
| `PORT` | FastAPI server port | `8000` |
| `CASE_TIMEOUT_SECONDS` | Maximum allowed runtime per decision case | `300` |

---

## License
MIT
