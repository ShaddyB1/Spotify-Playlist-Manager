from gevent import monkey
monkey.patch_all()  # This needs to happen before any other imports

import os
from dotenv import load_dotenv
from app.main import app

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Get port from environment, defaulting to 5001 if not specified
    port = int(os.getenv('PORT', 5001))
    
    print(f"Starting server on port {port}")
    print(f"Spotify Client ID: {os.getenv('SPOTIFY_CLIENT_ID')[:5]}...")  # Only show first 5 chars for security
    
    app.run(host='0.0.0.0', port=port)
