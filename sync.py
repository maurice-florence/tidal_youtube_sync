import os
import json
import logging
from ytmusicapi import YTMusic
import tidalapi
from dotenv import load_dotenv

# Logging instellen
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Laad de lokale .env (indien aanwezig)
load_dotenv()

# Laad secrets vanuit GitHub Actions (via SECRETS_CONTEXT) en zet ze in os.environ
secrets_str = os.environ.get("SECRETS_CONTEXT")
if secrets_str:
    try:
        secrets = json.loads(secrets_str)
        for k, v in secrets.items():
            if isinstance(v, str):
                os.environ[k] = v
    except json.JSONDecodeError:
        logging.error("Kon SECRETS_CONTEXT niet parsen als JSON.")

def get_youtube_tracks(playlist_id):
    """
    Haalt tracks op uit een openbare/verborgen YouTube (Music) playlist.
    Geen authenticatie vereist.
    """
    # Verwijder eventuele extra URL-parameters (zoals de &jct= invite link)
    clean_id = playlist_id.split('&')[0]
    
    logging.info(f"Ophalen van YouTube Music tracks (ID: {clean_id})...")
    ytmusic = YTMusic()
    
    try:
        playlist = ytmusic.get_playlist(clean_id)
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

def get_tidal_account_prefixes():
    """
    Scant os.environ naar keys die eindigen op _TIDAL_PLAYLIST_ID (of precies TIDAL_PLAYLIST_ID zijn).
    Retourneert een lijst van prefixes. (bijv. "" voor TIDAL_PLAYLIST_ID, en "VRIEND" voor VRIEND_TIDAL_PLAYLIST_ID)
    """
    prefixes = []
    for key in os.environ.keys():
        if key == "TIDAL_PLAYLIST_ID":
            prefixes.append("")
        elif key.endswith("_TIDAL_PLAYLIST_ID"):
            prefix = key.replace("_TIDAL_PLAYLIST_ID", "")
            prefixes.append(prefix)
    return list(set(prefixes))

def sync_to_tidal(yt_tracks, prefix=""):
    """
    Synchroniseert de lijst naar een specifiek Tidal account.
    """
    p = f"{prefix}_" if prefix else ""
    tidal_playlist_id = os.getenv(f"{p}TIDAL_PLAYLIST_ID")
    
    account_name = prefix if prefix else "Standaard"
    logging.info(f"--- Start sync voor Tidal account: '{account_name}' ---")
    
    if not tidal_playlist_id:
        logging.error(f"Geen {p}TIDAL_PLAYLIST_ID gevonden. Sla account over.")
        return
        
    session = tidalapi.Session()
    
    # Haal Tidal tokens op
    t_session_id = os.getenv(f"{p}TIDAL_SESSION_ID")
    t_token_type = os.getenv(f"{p}TIDAL_TOKEN_TYPE")
    t_access_token = os.getenv(f"{p}TIDAL_ACCESS_TOKEN")
    t_refresh_token = os.getenv(f"{p}TIDAL_REFRESH_TOKEN")

    # Tidal Login Logica
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
            logging.error(f"Fout bij laden Tidal sessie voor '{account_name}': {e}")
            return
    else:
        logging.info(f"Eerste keer inloggen op Tidal voor account '{account_name}'. Controleer de terminal/browser...")
        session.login_oauth_simple()
        logging.info(f"\n=== KOPIEER DEZE WAARDEN NAAR JE .env EN GITHUB SECRETS ===")
        logging.info(f"{p}TIDAL_SESSION_ID={session.session_id}")
        logging.info(f"{p}TIDAL_TOKEN_TYPE={session.token_type}")
        logging.info(f"{p}TIDAL_ACCESS_TOKEN={session.access_token}")
        logging.info(f"{p}TIDAL_REFRESH_TOKEN={session.refresh_token}")
        logging.info("=============================================================\n")
    
    if not session.check_login():
        logging.error(f"Tidal login is mislukt voor account '{account_name}'.")
        return

    logging.info(f"Tidal login succesvol voor '{account_name}'!")
    
    # Tidal Playlist ophalen
    user_playlists = session.user.playlists()
    playlist = next((pl for pl in user_playlists if str(pl.id) == str(tidal_playlist_id)), None)
    
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
            
    logging.info(f"Sync voor account '{account_name}' compleet. Er zijn {added_count} nieuwe nummers toegevoegd.\n")

if __name__ == "__main__":
    YOUTUBE_PLAYLIST_ID = os.getenv("YOUTUBE_PLAYLIST_ID")
    if not YOUTUBE_PLAYLIST_ID:
        logging.error("Zorg dat YOUTUBE_PLAYLIST_ID in je .env staat!")
    else:
        tracks = get_youtube_tracks(YOUTUBE_PLAYLIST_ID)
        if tracks:
            prefixes = get_tidal_account_prefixes()
            if not prefixes:
                logging.error("Geen enkele Tidal configuratie gevonden! Stel op z'n minst TIDAL_PLAYLIST_ID in.")
            
            for prefix in prefixes:
                sync_to_tidal(tracks, prefix)
