import os
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Load environment variables
    load_dotenv()
    
    # Get credentials
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        logger.error("Missing Spotify credentials")
        return
    
    logger.info(f"Using Client ID: {client_id[:5]}...")
    
    try:
        # Create client credentials manager
        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Create Spotify client
        sp = spotipy.Spotify(auth_manager=auth_manager)
        logger.info("Successfully created Spotify client")
        
        # Test API calls
        
        # 0. Get all available categories
        try:
            logger.info("Getting all available categories")
            categories = sp.categories(limit=50)
            logger.info(f"Categories response keys: {categories.keys() if categories else 'None'}")
            
            if categories and 'categories' in categories and 'items' in categories['categories']:
                items = categories['categories']['items']
                logger.info(f"Found {len(items)} categories")
                
                logger.info("Available categories:")
                for i, item in enumerate(items):
                    logger.info(f"Category {i+1}: {item['name']} (ID: {item['id']})")
            else:
                logger.warning("No categories found or unexpected response format")
        except Exception as e:
            logger.error(f"Error getting categories: {str(e)}")
        
        # 1. Test getting a category
        category_id = '0JQ5DAqbMKFDXXwE9BDJAr'  # Rock category ID
        try:
            logger.info(f"Testing category: {category_id}")
            category = sp.category(category_id=category_id)
            logger.info(f"Category response: {category}")
        except Exception as e:
            logger.error(f"Error getting category: {str(e)}")
        
        # 2. Test getting category playlists
        try:
            logger.info(f"Testing category playlists: {category_id}")
            playlists = sp.category_playlists(category_id=category_id, limit=10)
            logger.info(f"Category playlists response keys: {playlists.keys() if playlists else 'None'}")
            
            if playlists and 'playlists' in playlists and 'items' in playlists['playlists']:
                items = playlists['playlists']['items']
                logger.info(f"Found {len(items)} playlists")
                
                for i, item in enumerate(items[:3]):  # Show first 3 playlists
                    logger.info(f"Playlist {i+1}: {item['name']} (ID: {item['id']})")
            else:
                logger.warning("No playlists found or unexpected response format")
        except Exception as e:
            logger.error(f"Error getting category playlists: {str(e)}")
        
        # 3. Test search for playlists
        try:
            logger.info("Testing search for 'rock' playlists")
            search_results = sp.search(q='rock', type='playlist', limit=10)
            logger.info(f"Search response keys: {search_results.keys() if search_results else 'None'}")
            
            if search_results and 'playlists' in search_results and 'items' in search_results['playlists']:
                items = search_results['playlists']['items']
                logger.info(f"Found {len(items)} playlists via search")
                
                for i, item in enumerate(items[:3]):  # Show first 3 playlists
                    logger.info(f"Search result {i+1}: {item['name']} (ID: {item['id']})")
            else:
                logger.warning("No search results found or unexpected response format")
        except Exception as e:
            logger.error(f"Error searching for playlists: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error initializing Spotify client: {str(e)}")

if __name__ == "__main__":
    main() 