from dotenv import load_dotenv
load_dotenv()

from app.manager import SpotifyPlaylistManager
from app.services.spotify_service import SpotifyService

print("Testing Spotify credentials...")

# Test SpotifyService
service = SpotifyService()
print('Service Client ID:', service.client_id[:5] + '...' if service.client_id else None)
print('Service Client Secret:', service.client_secret[:5] + '...' if service.client_secret else None)

# Test guest token
try:
    token = service.get_guest_token()
    print("Guest token retrieval:", "Success" if token else "Failed")
except Exception as e:
    print("Error getting guest token:", str(e))

# Test direct guest token
try:
    token = service.get_guest_token_direct()
    print("Direct guest token retrieval:", "Success" if token else "Failed")
except Exception as e:
    print("Error getting direct guest token:", str(e))

# Test SpotifyPlaylistManager
try:
    manager = SpotifyPlaylistManager('test_playlist_id')
    print('Manager initialized successfully')
except Exception as e:
    print('Error initializing manager:', str(e)) 