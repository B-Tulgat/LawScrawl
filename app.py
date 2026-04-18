import os
import torch
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase
from google import genai

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Gemini client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Device setup
device = "cuda" if torch.cuda.is_available() else "cpu"

# Embedding model
embed_model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", device=device)

# Neo4j connection
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password"
driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

# Categories
CATEGORIES = [
    "Бүгд",
    "Аймаг, нийслэлийн Засаг даргын захирамж",
    "Засгийн газрын агентлагийн даргын тушаал",
    "Сайдын тушаал",
    "Аймаг, нийслэлийн ИТХ-ын шийдвэр",
    "Ерөнхийлөгчийн зарлиг",
    "УИХ-аас томилогддог байгууллагын дарга, түүнтэй адилтгах албан тушаалтны шийдвэр",
    "Засгийн газрын тогтоол",
    "Зөвлөл, хороо, бусад байгууллага",
    "Монгол Улсын олон улсын гэрээ",
    "Монгол Улсын хууль",
    "Монгол Улсын Үндсэн Хууль",
    "Хууль, хяналтын байгууллага",
    "Төрийн зарим чиг үүргийг хууль болон гэрээний үндсэн дээр хэрэгжүүлж буй байгууллага",
    "Улсын дээд шүүхийн тогтоол",
    "Улсын Их Хурлын тогтоол",
    "Шүүхийн ерөнхий зөвлөл",
    "Үндсэн хуулийн цэцийн шийдвэр",
]

# --- Logic function ---
def get_rag_response(query_text, selected_category=None):
    # 1. Vector search
    query_emb = embed_model.encode(query_text, normalize_embeddings=True).tolist()

    with driver.session() as session:
        cypher_query = """
        CALL db.index.vector.queryNodes('chunk_vector_index', 8, $vector)
        YIELD node AS chunk, score
        WHERE score > 0.4
        MATCH (law:Law)-[:HAS_CHUNK]->(chunk)
        """

        params = {"vector": query_emb}

        if selected_category and selected_category != "Бүгд":
            cypher_query += " WHERE law.category = $category "
            params["category"] = selected_category

        cypher_query += """
        RETURN chunk.content AS text,
               chunk.name AS clause_name,
               law.lawId AS lawId,
               score
        """

        context_data = session.run(cypher_query, **params).data()


    # 2. Build context
    context_str = "\n\n".join([
        f"URL: https://legalinfo.mn/mn/detail?lawId={item['lawId']}\n"
        f"Заалт: {item['clause_name']}\n"
        f"Агуулга: {item['text']}"
        for item in context_data
    ])

    sources = [
        {
            "lawId": item["lawId"],
            "clause_name": item["clause_name"],
            "url": f"https://legalinfo.mn/mn/detail?lawId={item['lawId']}",
            "score": round(float(item["score"]), 4),
        }
        for item in context_data
    ]

    if not context_str:
        context_str = "Мэдээллийн сангаас таны хайлттай төстэй мэдээлэл олдсонгүй. Иймд зөвхөн суурь моделийн мэдлэгийн дагуу хариу өгнө."

    # 3. Prompt
    prompt = f"""
Та бол Монгол Улсын хууль тогтоомжийн мэргэшсэн туслах.

Доорх өгөгдсөн КОНТЕКСТ-ийг ашиглан хэрэглэгчийн асуултанд хариулна уу.

ДҮРЭМ:
1. Хариулт маш тодорхой, албан ёсны байх ёстой.
2. Өгүүлбэр бүрийн ард эх сурвалжийн URL-ыг заавал хаалтанд бичнэ. Байхгүй тохиолдолд хаалтан дотор холбоос байхгүй гэж бич.
3. Контекстэд байхгүй мэдээллийг өөрөөсөө зохиож болохгүй.
4. Perplexity format answer

КОНТЕКСТ:
{context_str}

АСУУЛТ:
{query_text}
"""

    print(prompt)

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt
    )

    return {
        "answer": response.text,
        "sources": sources
    }


# --- Flask routes ---
@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)


@app.route("/ask", methods=["POST"])
def ask():
    data = request.json
    result = get_rag_response(data.get("query"), data.get("category"))
    print(result)
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)