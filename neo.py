from neo4j import GraphDatabase
import json

URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password"

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def process_law_entry(tx, ch):
    # 1. Insert Law and Chunk in one go
    tx.run("""
    MERGE (l:Law {lawId: $lawId})
    SET l.act_name = $act_name,
        l.date = $date,
        l.category = $category

    MERGE (c:Chunk {chunk_id: $chunk_id})
        ON CREATE SET c.type = $type, c.content = $content

    MERGE (l)-[:HAS_CHUNK]->(c)
    """, **ch)

    # 2. Handle Context Path (including lawId in Structure for uniqueness)
    parts = ch["context_path"].split(" > ")
    prev_node_id = None

    for i, p in enumerate(parts):
        # We use lawId + name + level to ensure 'Chapter 1' of Law A
        # is different from 'Chapter 1' of Law B
        res = tx.run("""
        MERGE (s:Structure {name: $name, lawId: $lawId})
        RETURN id(s) AS node_id
        """, name=p, lawId=ch["lawId"])

        curr_node_id = res.single()["node_id"]

        if prev_node_id:
            tx.run("""
            MATCH (a) WHERE id(a) = $prev_id
            MATCH (b) WHERE id(b) = $curr_id
            MERGE (b)-[:CHILD_OF]->(a)
            """, prev_id=prev_node_id, curr_id=curr_node_id)

        prev_node_id = curr_node_id

    # 3. Connect chunk to the leaf structure
    if prev_node_id:
        tx.run("""
        MATCH (c:Chunk {chunk_id: $chunk_id})
        MATCH (s) WHERE id(s) = $s_id
        MERGE (c)-[:IN_CONTEXT]->(s)
        """, chunk_id=ch["chunk_id"], s_id=prev_node_id)

with driver.session() as session:
    with open("out.jsonl", encoding="utf-8") as f:
        for line in f:
            ch = json.loads(line)
            # Map your JSON keys to the expected payload
            payload = {
                "lawId": ch["lawId"],
                "act_name": ch["act_name"],
                "date": ch["date"],
                "category": ch.get("act_category"), # Use .get for safety
                "chunk_id": ch["chunk_id"],
                "type": ch["type"],
                "content": ch["content"],
                "context_path": ch["context_path"]
            }

            # Use execute_write for the public, retry-able API
            session.execute_write(process_law_entry, payload)

driver.close()
