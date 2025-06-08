import psycopg
from pathlib import Path 
from dotenv import load_dotenv
import os

load_dotenv()
sql_path = Path(r"migrations\001_create_embeddings.sql")

with open(sql_path, "r") as file:
    sql_script = file.read()


conn: psycopg.Connection[psycopg.rows.Row] = psycopg.connect(os.getenv("DATABASE_URL"))
with conn, conn.cursor() as cur:
    cur.execute(sql_script)

print("Migration completed successfully.")
