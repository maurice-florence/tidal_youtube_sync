import os
import logging
from ytmusicapi import YTMusic
import tidalapi
from dotenv import load_dotenv
from difflib import SequenceMatcher
from datetime import datetime, timezone

# Logging instellen
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()

def is_similar(a, b, threshold=0.5):
    """
    Controleert of twee strings voor een bepaald percentage op elkaar lijken.
    Handig om te voorkomen dat Tidal willekeurige resultaten toevoegt.
    """
    if not a or not b:
        return False
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold

def get_youtube_tracks(playlist_id):
    """
    Haalt tracks op uit een openbare/verborgen YouTube (Music) playlist.
    Geen authenticatie vereist.
    """
    clean_id = playlist_id.split('&')[0]
    
    logging.info(f"Ophalen van YouTube Music tracks (ID: {clean_id})...")
    ytmusic = YTMusic()
    
    try:
        playlist = ytmusic.get_playlist(clean_id)
        tracks = []
        
        for track in playlist.get('tracks', []):
            title = track.get('title')
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
    Synchroniseert de lijst naar Tidal (Zowel toevoegen als opschonen).
    """
    session = tidalapi.Session()
    
    t_session_id = os.getenv("TIDAL_SESSION_ID")
    t_token_type = os.getenv("TIDAL_TOKEN_TYPE")
    t_access_token = os.getenv("TIDAL_ACCESS_TOKEN")
    t_refresh_token = os.getenv("TIDAL_REFRESH_TOKEN")

    if t_access_token and t_refresh_token:
        logging.info("Inloggen op Tidal via opgeslagen tokens...")
        try:
            session.load_oauth_session(
                token_type=t_token_type,
                access_token=t_access_token,
                refresh_token=t_refresh_token
            )
        except Exception as e:
            logging.error(f"Fout bij laden Tidal sessie: {e}")
            return
    else:
        if os.getenv("GITHUB_ACTIONS"):
            logging.error("Tokens ontbreken. Kan niet interactief inloggen in de cloud. Sla sync over.")
            return
            
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
    
    user_playlists = session.user.playlists()
    playlist = next((p for p in user_playlists if str(p.id) == str(tidal_playlist_id)), None)
    
    if not playlist:
        logging.error(f"Geen Tidal afspeellijst gevonden met ID: {tidal_playlist_id}")
        return

    # Ophalen via items() in plaats van tracks() om date_added te kunnen gebruiken
    items = list(playlist.items())
    
    # We slaan de namen op voor de duplicate-check
    existing_combinations = [f"{t.name.lower()} {t.artist.name.lower()}" for t in items if hasattr(t, 'name') and hasattr(t, 'artist')]
    existing_ids = [t.id for t in items]
    
    # --- 1. TOEVOEGEN VAN NIEUWE NUMMERS ---
    added_count = 0
    for yt_track in yt_tracks:
        search_query = f"{yt_track['title']} {yt_track['artist']}"
        
        if search_query.lower() in existing_combinations:
            continue
            
        search_result = session.search(search_query, models=[tidalapi.Track])
        tracks_found = search_result.get('tracks', []) if isinstance(search_result, dict) else search_result.tracks
        
        if tracks_found:
            top_match = tracks_found[0]
            
            # Fuzzy match check!
            if is_similar(yt_track['title'], top_match.name, threshold=0.5):
                if top_match.id not in existing_ids:
                    try:
                        playlist.add([top_match.id])
                        logging.info(f"Toegevoegd: {yt_track['title']} - {yt_track['artist']}")
                        existing_ids.append(top_match.id)
                        added_count += 1
                    except Exception as e:
                        logging.error(f"Fout bij toevoegen {search_query}: {e}")
            else:
                logging.warning(f"Geweigerd: Tidal vond '{top_match.name}', maar dit lijkt onvoldoende op '{yt_track['title']}'.")
        else:
            logging.warning(f"Niet gevonden in Tidal: {search_query}")
            
    logging.info(f"Toevoeg-ronde compleet. {added_count} nieuwe nummers toegevoegd.")

    # --- 2. OPSCHOON-RONDE (VERWIJDEREN) ---
    # Beveiliging: alleen nummers verwijderen die ná 1 juli 2026 zijn toegevoegd aan Tidal.
    CUTOFF_DATE = datetime(2026, 7, 1, tzinfo=timezone.utc)
    removed_count = 0
    
    # We itereren achterstevoren zodat de indexen kloppen als we er eentje verwijderen
    for i in range(len(items) - 1, -1, -1):
        item = items[i]
        
        # Controleer de datagrens
        if hasattr(item, 'date_added') and item.date_added and item.date_added >= CUTOFF_DATE:
            # Is dit nummer nog aanwezig in YouTube?
            found_in_yt = False
            for yt_track in yt_tracks:
                if is_similar(yt_track['title'], item.name, threshold=0.5):
                    found_in_yt = True
                    break
            
            if not found_in_yt:
                try:
                    # playlist.remove_by_index verwijdert het n-de element in de lijst
                    playlist.remove_by_index(i)
                    logging.info(f"Verwijderd: {item.name} - {item.artist.name} (niet meer aanwezig in YouTube)")
                    removed_count += 1
                except Exception as e:
                    logging.error(f"Fout bij verwijderen {item.name}: {e}")
                    
    if removed_count > 0:
        logging.info(f"Opschoon-ronde compleet. Er zijn {removed_count} nummers verwijderd.")

if __name__ == "__main__":
    YOUTUBE_PLAYLIST_ID = os.getenv("YOUTUBE_PLAYLIST_ID")
    TIDAL_PLAYLIST_ID = os.getenv("TIDAL_PLAYLIST_ID")
    
    if not YOUTUBE_PLAYLIST_ID or not TIDAL_PLAYLIST_ID:
        logging.error("Zorg dat YOUTUBE_PLAYLIST_ID en TIDAL_PLAYLIST_ID in je .env staan!")
    else:
        tracks = get_youtube_tracks(YOUTUBE_PLAYLIST_ID)
        if tracks:
            try:
                sync_to_tidal(tracks, TIDAL_PLAYLIST_ID)
            except Exception as e:
                logging.error(f"Onverwachte fout tijdens syncen: {e}")
