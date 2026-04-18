from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase
import torch


device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', device=device)

# 2. Connection Settings
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password"
driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def embed_locally():
    with driver.session() as session:
        # Get all chunks where embedding is missing
        result = session.run("MATCH (c:Chunk) WHERE c.embedding IS NULL RETURN c.chunk_id AS id, c.content AS text")

        records = list(result)
        total = len(records)
        print(f"Starting local embedding for {total} chunks...")

        for i, record in enumerate(records):
            embedding = model.encode(record["text"], normalize_embeddings=True).tolist()

            session.run("""
                MATCH (c:Chunk {chunk_id: $id})
                SET c.embedding = $embedding
            """, id=record["id"], embedding=embedding)

            if i % 10 == 0:
                print(f"Progress: {i}/{total} chunks completed.")

    print("All chunks successfully embedded locally.")

embed_locally()
driver.close()
