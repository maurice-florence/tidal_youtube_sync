import os
import logging
from ytmusicapi import YTMusic
import tidalapi
from dotenv import load_dotenv

# Logging instellen
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()

def get_youtube_tracks(playlist_id):
    """
    Haalt tracks op uit een openbare/verborgen YouTube (Music) playlist.
    Geen authenticatie vereist.
    """
    logging.info("Ophalen van YouTube Music tracks...")
    ytmusic = YTMusic()
    
    try:
        playlist = ytmusic.get_playlist(playlist_id)
        tracks = []
        
        for track in playlist.get('tracks', []):
            title = track.get('title')
            # Pak de naam van de eerste artiest
            artist = track.get('artists')[0].get('name') if track.get('artists') else ""
            
            if title and artist:
                tracks.append({
                    'title': title,
                    'artist': artist
                })
                
        logging.info(f"{len(tracks)} tracks gevonden in de YouTube playlist.")
        return tracks
    except Exception as e:
        logging.error(f"Fout bij ophalen YouTube playlist: {e}")
        return []

def sync_to_tidal(yt_tracks, tidal_playlist_id):
    """
    Synchroniseert de lijst naar Tidal.
    """
    session = tidalapi.Session()
    
    # Haal Tidal tokens op
    t_session_id = os.getenv("TIDAL_SESSION_ID")
    t_token_type = os.getenv("TIDAL_TOKEN_TYPE")
    t_access_token = os.getenv("TIDAL_ACCESS_TOKEN")
    t_refresh_token = os.getenv("TIDAL_REFRESH_TOKEN")

    # Tidal Login Logica (Headless of Eerste keer)
    if t_access_token and t_refresh_token:
        logging.info("Inloggen op Tidal via opgeslagen tokens...")
        try:
            session.load_oauth_session(
                session_id=t_session_id,
                token_type=t_token_type,
                access_token=t_access_token,
                refresh_token=t_refresh_token
            )
        except Exception as e:
            logging.error(f"Fout bij laden Tidal sessie: {e}")
            return
    else:
        logging.info("Eerste keer inloggen op Tidal. Controleer de terminal/browser...")
        session.login_oauth_simple()
        logging.info("\n=== KOPIEER DEZE WAARDEN NAAR JE .env EN GITHUB SECRETS ===")
        logging.info(f"TIDAL_SESSION_ID={session.session_id}")
        logging.info(f"TIDAL_TOKEN_TYPE={session.token_type}")
        logging.info(f"TIDAL_ACCESS_TOKEN={session.access_token}")
        logging.info(f"TIDAL_REFRESH_TOKEN={session.refresh_token}")
        logging.info("=============================================================\n")
    
    if not session.check_login():
        logging.error("Tidal login is mislukt.")
        return

    logging.info("Tidal login succesvol!")
    
    # Tidal Playlist ophalen
    user_playlists = session.user.playlists()
    playlist = next((p for p in user_playlists if str(p.id) == str(tidal_playlist_id)), None)
    
    if not playlist:
        logging.error(f"Geen Tidal afspeellijst gevonden met ID: {tidal_playlist_id}")
        return

    # Bestaande tracks ophalen om duplicaten te voorkomen
    tidal_tracks = playlist.tracks()
    existing_combinations = [f"{t.name.lower()} {t.artist.name.lower()}" for t in tidal_tracks if hasattr(t, 'name') and hasattr(t, 'artist')]
    existing_ids = [t.id for t in tidal_tracks]
    
    added_count = 0
    for yt_track in yt_tracks:
        search_query = f"{yt_track['title']} {yt_track['artist']}"
        
        # Simpele check of een variatie van de titel + artiest al bestaat
        if search_query.lower() in existing_combinations:
            continue
            
        # Zoek het nummer in Tidal
        search_result = session.search(search_query, models=[tidalapi.Track])
        tracks_found = search_result.get('tracks', []) if isinstance(search_result, dict) else search_result.tracks
        
        if tracks_found:
            top_match = tracks_found[0]
            if top_match.id not in existing_ids:
                try:
                    playlist.add([top_match.id])
                    logging.info(f"Toegevoegd: {yt_track['title']} - {yt_track['artist']}")
                    existing_ids.append(top_match.id) # Voorkom dubbele toevoegingen in dezelfde run
                    added_count += 1
                except Exception as e:
                    logging.error(f"Fout bij toevoegen {search_query}: {e}")
        else:
            logging.warning(f"Niet gevonden in Tidal: {search_query}")
            
    logging.info(f"Sync compleet. Er zijn {added_count} nieuwe nummers toegevoegd.")

if __name__ == "__main__":
    YOUTUBE_PLAYLIST_ID = os.getenv("YOUTUBE_PLAYLIST_ID")
    TIDAL_PLAYLIST_ID = os.getenv("TIDAL_PLAYLIST_ID")
    
    if not YOUTUBE_PLAYLIST_ID or not TIDAL_PLAYLIST_ID:
        logging.error("Zorg dat YOUTUBE_PLAYLIST_ID en TIDAL_PLAYLIST_ID in je .env staan!")
    else:
        tracks = get_youtube_tracks(YOUTUBE_PLAYLIST_ID)
        if tracks:
            sync_to_tidal(tracks, TIDAL_PLAYLIST_ID)
