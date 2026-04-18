# Mongolian Legal RAG System

### Disclaimer: This `README` is made with a help of AI

A Retrieval-Augmented Generation (RAG) system for querying Mongolian legislation from [legalinfo.mn](https://legalinfo.mn). It scrapes, cleans, chunks, embeds, and indexes laws into a Neo4j graph database, then exposes a Flask web interface powered by Google Gemini.

---

## Architecture

```
legalinfo.mn
     │
     ▼
scraping.ipynb        ← Crawl4AI scraper → saves raw .md files per category
     │
     ▼
cleaner.py            ← Strips headers/footers → cleaned .md files
     │
     ▼
chunker_01.py         ← Splits laws into clause/subclause chunks → out.jsonl
     │
     ▼
neo.py                ← Loads chunks into Neo4j graph (Law → Chunk → Structure)
     │
     ▼
embed.py              ← Encodes chunks with multilingual MiniLM → stored in Neo4j
     │
     ▼
app.py                ← Flask + Gemini RAG API + web UI
```

---

## Prerequisites

- Python 3.10+
- Docker & Docker Compose (for Neo4j)
- A [Google Gemini API key](https://aistudio.google.com/app/apikey)

---

## Quick Start

### 1. Clone & install dependencies

```bash
git clone <your-repo-url>
cd mongolian-legal-rag

pip install -r requirements.txt
```

> If using a conda environment, activate it first:
> `conda activate your-env`

### 2. Start Neo4j with Docker

```bash
docker-compose up -d
```

Neo4j will be available at:
- **Browser UI:** http://localhost:7474
- **Bolt:** bolt://localhost:7687
- **Credentials:** `neo4j` / `password`

### 3. Set up environment variables

```bash
cp .env.example .env
# Then edit .env and add your Gemini API key
```

### 4. Run the pipeline

```bash
# Step 1: Scrape laws (run in Jupyter)
jupyter notebook scraping.ipynb

# Step 2: Clean raw files
python cleaner.py

# Step 3: Chunk cleaned files into out.jsonl
python chunker_01.py ~/Desktop/LawScrawl_Cleaned out.jsonl

# Step 4: Load chunks into Neo4j
python neo.py

# Step 5: Create the vector index in Neo4j (run once in Neo4j Browser)
# See "Neo4j Vector Index" section below

# Step 6: Generate embeddings
python embed.py

# Step 7: Start the web app
python app.py
```

Open http://localhost:5000 in your browser.

---

## Neo4j Vector Index

After loading data with `neo.py`, create the vector index once in the **Neo4j Browser** (http://localhost:7474):

```cypher
CREATE VECTOR INDEX chunk_vector_index IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 384,
    `vector.similarity_function`: 'cosine'
  }
}
```

---

## Environment Variables

Copy `.env.example` to `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## Project Structure

```
.
├── scraping.ipynb       # Async web crawler for legalinfo.mn
├── cleaner.py           # Strips boilerplate from raw scraped .md files
├── chunker_01.py        # Parses Mongolian legal structure into chunks
├── neo.py               # Ingests chunks into Neo4j graph
├── embed.py             # Generates and stores vector embeddings
├── app.py               # Flask web app with Gemini RAG
├── docker-compose.yml   # Neo4j container setup
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
└── templates/
    └── index.html       # Web UI template
```

---

## Graph Schema

```
(Law)-[:HAS_CHUNK]->(Chunk)-[:IN_CONTEXT]->(Structure)
(Structure)-[:CHILD_OF]->(Structure)
```

| Node | Key Properties |
|---|---|
| `Law` | `lawId`, `act_name`, `date`, `category` |
| `Chunk` | `chunk_id`, `type`, `content`, `embedding` |
| `Structure` | `name`, `lawId` |

---

## Supported Law Categories

The system supports all 17 categories from legalinfo.mn including:
- Монгол Улсын хууль (Laws of Mongolia)
- Монгол Улсын Үндсэн Хууль (Constitution)
- Засгийн газрын тогтоол (Government resolutions)
- Ерөнхийлөгчийн зарлиг (Presidential decrees)
- and more — selectable from the web UI dropdown.

---

## Tech Stack

| Component | Technology |
|---|---|
| Scraping | [Crawl4AI](https://github.com/unclecode/crawl4ai) 0.8 |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` |
| Graph DB | Neo4j 5.x |
| LLM | Google Gemini (`gemini-3-flash-preview`) |
| Web Framework | Flask |
| GPU Support | PyTorch (CUDA auto-detected) |
