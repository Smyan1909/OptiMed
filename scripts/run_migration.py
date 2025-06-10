import psycopg
from pathlib import Path 
from dotenv import load_dotenv
import os

load_dotenv()
sql_path = Path(r"migrations\001_create_embeddings.sql")

with open(sql_path, "r") as file:
    sql_script = file.read()

database_url = os.getenv("PGVECTOR_DSN")
if database_url is None:
    raise ValueError("PGVECTOR_DSN environment variable is not set")

conn = psycopg.connect(database_url)
with conn, conn.cursor() as cur:
    cur.execute(sql_script)

print("Migration completed successfully.")
