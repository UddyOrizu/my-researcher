import os
import torch
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
import chromadb
import chromadb.utils.embedding_functions as embedding_functions
from azure.storage.blob import BlobServiceClient  # Add this import at the top
import json
import pytesseract
from PIL import Image
import io
import hashlib
import extract_msg
import re

current_dir_path = os.path.dirname(os.path.realpath(__file__))
CONFIG = json.load(open(current_dir_path + '/config.json'))

AZURE_API_KEY = CONFIG['AZURE_API_KEY']
AZURE_API_BASE = CONFIG['AZURE_API_BASE']
AZURE_API_VERSION = CONFIG['AZURE_API_VERSION']


azure_conn_str = CONFIG.get('AZURE_CONNECTION_STRING')
blob_container = CONFIG.get('AZURE_BLOB_CONTAINER', 'knowledge-base')

if not azure_conn_str:
    print("[ERROR] Azure connection string required.")



client = chromadb.PersistentClient(path="/data/chroma")

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=AZURE_API_KEY,
                api_base=AZURE_API_BASE,
                api_type="azure",
                api_version=AZURE_API_VERSION,
                model_name="text-embedding-3-small"
            )

collection = client.get_or_create_collection(name="knowledge_base",embedding_function=openai_ef)

blob_service_client = BlobServiceClient.from_connection_string(azure_conn_str)
container_client = blob_service_client.get_container_client(blob_container)


def embed_text(query):
    return openai_ef(query)
##################
# Scoring & Search
##################
def late_interaction_score(query_emb, doc_emb):
    q_vec = query_emb.view(-1)
    d_vec = doc_emb.view(-1)
    q_norm = q_vec / q_vec.norm()
    d_norm = d_vec / d_vec.norm()
    return float(torch.dot(q_norm, d_norm))

def retrieve(query,query_id=None,top_k=5):
    result = None  

    if query_id is None:
        # If no query_id, just return the top 5 results for the query
        result = collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas"]
        )
    else:
        result = collection.query(
                query_texts=[query],
                n_results=top_k,
                where={"query_id": query_id},
                include=["documents", "metadatas"]
            )
    
    # For a single query (result["documents"][0] and result["metadatas"][0])
    for doc, meta in zip(result["documents"][0], result["metadatas"][0]):    
        # meta is a dict or list of dicts depending on how you stored metadata
        # If meta is a list of dicts, flatten or access as needed
        if isinstance(meta, dict):
            print("Year:", meta.get("year"))
            print("Service Line:", meta.get("service_line"))
            print("Document Type:", meta.get("document_type"))
        elif isinstance(meta, list):
            # If you stored metadata as a list of dicts, merge them
            merged_meta = {}
            for m in meta:
                merged_meta.update(m)
            print("Year:", merged_meta.get("year"))
            print("Service Line:", merged_meta.get("service_line"))
            print("Document Type:", merged_meta.get("document_type"))
    
    return result

##################################
# Building a Corpus from a Folder
##################################

def extract_blob_metadata_from_path(blob_name):
    """
    Extract year, service_line, and type from blob path.
    Example: 'container/knowledge_base/2023/service_line/reports/report-123.pdf'
    Returns dict: {'year': ..., 'service_line': ..., 'type': ...}
    """
    # Regex to match: .../<year>/<service_line>/<type>/
    match = re.search(r'/(\d{4})/([^/]+)/([^/]+)/', blob_name)
    if match:
        return {
            "year": match.group(1),
            "service_line": match.group(2),
            "type": match.group(3)
        }
    return {"year": None, "service_line": None, "type": None}

def load_corpus_from_dir(blob_prefix):
    """
    Scan Azure Blob Storage container for txt, pdf, and image files under blob_prefix,
    embed their text, and return a list of { 'embedding':..., 'metadata':... } entries.
    """
    corpus = []

    blobs = container_client.list_blobs(name_starts_with=blob_prefix)
    for blob in blobs:
        filename = os.path.basename(blob.name)
        if not (filename.endswith(".txt") or filename.endswith(".pdf") or filename.endswith(".msg") or filename.lower().endswith(('.png', '.jpg', '.jpeg'))):
            continue

        # Download blob to memory
        blob_client = container_client.get_blob_client(blob.name)
        blob_bytes = blob_client.download_blob().readall()
        text = ""
        if filename.endswith(".txt"):
            text = blob_bytes.decode("utf-8")
        elif filename.endswith(".pdf"):
            try:
                import io
                doc = fitz.open(stream=blob_bytes, filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text() + "\n"
            except Exception as e:
                print(f"[WARN] Failed to read PDF {blob.name}: {e}")
                continue
        elif filename.endswith(".msg"):
            try:
                import io
                with open("temp_msg.msg", "wb") as temp_file:
                    temp_file.write(blob_bytes)
                msg = extract_msg.Message("temp_msg.msg")
                msg_sender = msg.sender or ""
                msg_subject = msg.subject or ""
                msg_date = msg.date or ""
                msg_body = msg.body or ""
                text = f"From: {msg_sender}\nSubject: {msg_subject}\nDate: {msg_date}\n\n{msg_body}"
                os.remove("temp_msg.msg")
            except Exception as e:
                print(f"[WARN] Failed to read MSG {blob.name}: {e}")
                continue
        elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            try:                
                image = Image.open(io.BytesIO(blob_bytes))
                text = pytesseract.image_to_string(image)
            except Exception as e:
                print(f"[WARN] OCR failed for image {blob.name}: {e}")
                continue
        else:
            continue

        if not text.strip():
            continue

        snippet = text[:100].replace('\n', ' ') + "..."
        doc_id = hashlib.sha256(blob.name.encode('utf-8')).hexdigest() 
        meta = extract_blob_metadata_from_path(blob.name)
        try:
            collection.add(
                documents=[text],
                metadatas=[{"snippet": snippet}, 
                           {"source": blob.name}, 
                           {"filename": filename},
                           {"year": meta.get("year")},
                           {"service_line": meta.get("service_line")},
                           {"document_type": meta.get("type")}],
                ids=[doc_id]
            )


        except Exception as e:
            print(f"[WARN] Skipping embedding for blob file {blob.name} due to error: {e}")

    return corpus


###########################
# KnowledgeBase Class (API)
###########################
class KnowledgeBase:
    """
    Simplified example showing how you might wrap the retrieval logic
    into a class. You can add 'add_documents' or advanced chunking, etc.
    """
    def __init__(self, device="cpu"):
        self.device = device
        self.collection = collection

    def add_documents(self, text, source, query_id):
        snippet = text[:100].replace('\n', ' ') + "..."
        doc_id = hashlib.sha256(source).hexdigest()                
        self.collection.add(
                documents=[text],
                metadatas=[{"snippet": snippet}, 
                           {"source": source}, 
                           {"query_id": query_id}
                           ],
                ids=[doc_id]
            )
    
    def add_documents_to_KB(self, text, blob, filename):
        snippet = text[:100].replace('\n', ' ') + "..."
        doc_id = hashlib.sha256(blob.name.encode('utf-8')).hexdigest() 
        meta = extract_blob_metadata_from_path(blob.name)        
        self.collection.add(
                documents=[text],
                metadatas=[{"snippet": snippet}, 
                           {"source": blob.name}, 
                           {"filename": filename},
                           {"year": meta.get("year")},
                           {"service_line": meta.get("service_line")},
                           {"document_type": meta.get("type")}],
                ids=[doc_id]
            )

    def search(self, query, query_id =None, top_k=3):

        return retrieve(
            query=query,
            query_id=query_id,
            top_k=top_k,
        )