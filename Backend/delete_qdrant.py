from storage.qdrant_client import client

client.delete_collection("text_docs")
client.delete_collection("image_docs")
print("✅ Deleted old collections")
