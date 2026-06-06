import os
import psycopg2
import psycopg2.extras
import pylast
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

DATABASE_URL = os.environ.get("DATABASE_URL")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
LASTFM_SECRET = os.environ.get("LASTFM_SECRET")

print(f"[STARTUP] DATABASE_URL set: {bool(DATABASE_URL)}")
print(f"[STARTUP] LASTFM_API_KEY set: {bool(LASTFM_API_KEY)}")

app = FastAPI(title="Sonosfer API")

# Middleware CORS indispensable para que tu Frontend en GitHub Pages pueda leer esta API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=500, detail="DATABASE_URL no configurada")
    conn = psycopg2.connect(url)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    try:
        yield conn
    finally:
        conn.close()

def get_lastfm():
    return pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_SECRET
    )

@app.get("/")
def root():
    return {"status": "ok", "app": "Sonosfer API"}

@app.get("/songs")
def get_songs(limit: int = 50, offset: int = 0, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.track_number, s.cluster_id,
               s.cloudflare_url,
               ar.name AS artist, ar.id AS artist_id,
               al.title AS album, al.id AS album_id, al.year
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        JOIN artists ar ON s.artist_id = ar.id
        ORDER BY s.id
        LIMIT %s OFFSET %s
    """, (limit, offset))
    return cur.fetchall()

@app.get("/songs/{song_id}")
def get_song(song_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.track_number, s.cluster_id,
               s.cloudflare_url,
               ar.name AS artist, ar.id AS artist_id,
               al.title AS album, al.id AS album_id, al.year
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        JOIN artists ar ON s.artist_id = ar.id
        WHERE s.id = %s
    """, (song_id,))
    song = cur.fetchone()
    if not song:
        raise HTTPException(status_code=404, detail="Canción no encontrada")
    return song

@app.get("/songs/{song_id}/recommendations")
def get_recommendations(song_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT cluster_id FROM songs WHERE id = %s", (song_id,))
    song = cur.fetchone()
    if not song:
        raise HTTPException(status_code=404, detail="Canción no encontrada")
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.cluster_id, s.cloudflare_url,
               ar.name AS artist, al.title AS album
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        JOIN artists ar ON s.artist_id = ar.id
        WHERE s.cluster_id = %s AND s.id != %s
        ORDER BY RANDOM()
        LIMIT 10
    """, (song["cluster_id"], song_id))
    return cur.fetchall()

@app.get("/artists")
def get_artists(db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id, name FROM artists ORDER BY name")
    return cur.fetchall()

@app.get("/artists/{artist_id}/image")
def get_artist_image(artist_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT name FROM artists WHERE id = %s", (artist_id,))
    artist = cur.fetchone()
    if not artist:
        raise HTTPException(status_code=404, detail="Artista no encontrado")
    try:
        network = get_lastfm()
        lastfm_artist = network.get_artist(artist["name"])
        image_url = lastfm_artist.get_cover_image()
        return {"artist_id": artist_id, "image_url": image_url}
    except Exception:
        return {"artist_id": artist_id, "image_url": None}

@app.get("/artists/{artist_id}/songs")
def get_artist_songs(artist_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.track_number,
               s.cluster_id, s.cloudflare_url,
               al.title AS album, al.year
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        WHERE s.artist_id = %s
        ORDER BY al.year, s.track_number
    """, (artist_id,))
    return cur.fetchall()

@app.get("/albums")
def get_albums(db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT al.id, al.title, al.year,
               ar.name AS artist, ar.id AS artist_id
        FROM albums al
        JOIN artists ar ON al.artist_id = ar.id
        ORDER BY ar.name, al.year
    """)
    return cur.fetchall()

@app.get("/albums/{album_id}/songs")
def get_album_songs(album_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.track_number,
               s.cluster_id, s.cloudflare_url
        FROM songs s
        WHERE s.album_id = %s
        ORDER BY s.track_number
    """, (album_id,))
    return cur.fetchall()

@app.get("/albums/{album_id}/cover")
def get_album_cover(album_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT al.title, ar.name
        FROM albums al JOIN artists ar ON al.artist_id = ar.id
        WHERE al.id = %s
    """, (album_id,))
    album = cur.fetchone()
    if not album:
        raise HTTPException(status_code=404, detail="Álbum no encontrado")
    try:
        network = get_lastfm()
        lastfm_album = network.get_album(album["name"], album["title"])
        cover_url = lastfm_album.get_cover_image()
        return {"album_id": album_id, "cover_url": cover_url}
    except Exception:
        return {"album_id": album_id, "cover_url": None}

@app.get("/genres")
def get_genres(db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id, name FROM genres ORDER BY name")
    return cur.fetchall()

@app.get("/search")
def search(q: str, db=Depends(get_db)):
    cur = db.cursor()
    pattern = f"%{q}%"
    cur.execute("""
        SELECT s.id, s.title, s.duration, s.cluster_id, s.cloudflare_url,
               ar.name AS artist, al.title AS album
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        JOIN artists ar ON s.artist_id = ar.id
        WHERE s.title ILIKE %s OR ar.name ILIKE %s
        ORDER BY s.title
        LIMIT 20
    """, (pattern, pattern))
    return cur.fetchall()
