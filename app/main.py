from flask import Flask, redirect, request, session, url_for, render_template, flash, jsonify
from flask_session import Session
from flask_cors import CORS
from datetime import timedelta, datetime
import os
import logging
from dotenv import load_dotenv
from app.services.spotify_service import SpotifyService, SpotifyAuthError
from app.services.rate_limiter import rate_limit
from app.manager import SpotifyPlaylistManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create the Flask app first
app = Flask(__name__)

# Configure app with all settings at once (don't split the configuration)
app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=False,  # Sessions expire when browser closes
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),  # Max session time
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='spotify_session'  # Unique session name
)

# Initialize extensions
CORS(app)
Session(app)

# Initialize services
spotify_service = SpotifyService()

# Add cache control
@app.after_request
def add_header(response):
    """Add headers to prevent caching."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.before_request
def check_session():
    """Check session validity before each request."""
    if 'token_info' in session:
        try:
            # Check if session is expired
            created_at = session.get('created_at')
            if created_at:
                created_at = datetime.fromisoformat(created_at)
                if datetime.now() - created_at > timedelta(hours=1):
                    logger.info("Session expired, clearing session")
                    session.clear()
                    return redirect(url_for('index'))
                    
            # Check if token needs refresh
            if spotify_service.is_token_expired(session['token_info']):
                try:
                    new_token = spotify_service.refresh_token(session['token_info'])
                    session['token_info'] = new_token
                    session['created_at'] = datetime.now().isoformat()
                    logger.info("Token refreshed successfully")
                except Exception as e:
                    logger.error(f"Token refresh failed: {str(e)}")
                    session.clear()
                    return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Session check error: {str(e)}")
            session.clear()
            return redirect(url_for('index'))

@app.route('/')
def index():
    if session.get('token_info'):
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login')
def login():
    try:
        auth_url = spotify_service.get_auth_url()
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        flash('Failed to initialize login', 'error')
        return render_template('error.html', error="Authentication failed"), 500

@app.route('/callback')
def callback():
    try:
        logger.info(f"Callback received - args: {request.args}")
        error = request.args.get('error')
        if error:
            logger.error(f"Spotify auth error: {error}")
            flash(f'Authentication error: {error}', 'error')
            return redirect(url_for('index'))

        code = request.args.get('code')
        state = request.args.get('state')
        stored_state = session.get('oauth_state')
        
        logger.info(f"State check - Received: {state}, Stored: {stored_state}")
        
        if not code:
            logger.error("No code received in callback")
            flash('Authentication failed: No code received', 'error')
            return redirect(url_for('index'))
        
        if state != stored_state:
            logger.error(f"State mismatch: received {state}, expected {stored_state}")
            flash('Authentication failed: State verification failed', 'error')
            return redirect(url_for('index'))

        # Get token
        token_info = spotify_service.get_token(code)
        if not token_info:
            logger.error("No token info received")
            flash('Authentication failed: No token received', 'error')
            return redirect(url_for('index'))
            
        session['token_info'] = token_info
        
        # Get user info
        sp = spotify_service.get_spotify_client()
        if not sp:
            logger.error("Failed to create Spotify client")
            flash('Failed to initialize Spotify client', 'error')
            return redirect(url_for('index'))
            
        user_info = sp.current_user()
        session['user_info'] = {
            'id': user_info['id'],
            'name': user_info['display_name'],
            'image': user_info['images'][0]['url'] if user_info.get('images') else None
        }
        
        logger.info(f"Successfully authenticated user: {user_info['id']}")
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.error(f"Callback error: {str(e)}", exc_info=True)
        flash(f'Authentication failed: {str(e)}', 'error')
        return redirect(url_for('index'))
        
@app.route('/dashboard')
@spotify_service.require_auth
def dashboard():
    try:
        playlists = spotify_service.get_user_playlists()
        return render_template('dashboard.html', 
                             playlists=playlists,
                             user=session.get('user_info'))
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        flash('Failed to load playlists', 'error')
        return redirect(url_for('index'))

@app.route('/playlist/<playlist_id>/analyze')
@spotify_service.require_auth
@rate_limit
def analyze_playlist(playlist_id):
    try:
        manager = SpotifyPlaylistManager(playlist_id)
        analysis = manager.analyze_tracks()
        return render_template('analyze.html', analysis=analysis)
    except Exception as e:
        logger.error(f"Analysis error: {str(e)}")
        flash('Failed to analyze playlist', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/playlist/<playlist_id>/similar', methods=['GET'])
@spotify_service.require_auth
@rate_limit
def get_similar_tracks(playlist_id):
    try:
        manager = SpotifyPlaylistManager(playlist_id)
        similar_tracks = manager.get_similar_tracks(limit=20)
        return jsonify({
            'tracks': similar_tracks,
            'total': len(similar_tracks)
        })
    except Exception as e:
        logger.error(f"Similar tracks error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlist/<playlist_id>/similar/add', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def add_similar_tracks(playlist_id):
    try:
        track_ids = request.json.get('track_ids', [])
        if not track_ids:
            return jsonify({'error': 'No tracks specified'}), 400

        manager = SpotifyPlaylistManager(playlist_id)
        manager.add_similar_tracks(track_ids)
        
        return jsonify({
            'message': f'Successfully added {len(track_ids)} tracks',
            'added_tracks': len(track_ids)
        })
    except Exception as e:
        logger.error(f"Add similar tracks error: {str(e)}")
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/analyze-optimization/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def analyze_optimization(playlist_id):
    try:
        criteria = request.json
        manager = SpotifyPlaylistManager(playlist_id)
        analysis = manager.analyze_tracks()
        
        tracks_to_remove = []
        for track in analysis['track_details']:
            reasons = []
            
            # Check popularity
            if track['popularity'] < int(criteria.get('minPopularity', 30)):
                reasons.append(f"Low popularity ({track['popularity']}%)")
            
            # Check energy if available
            if 'energy' in track and track['energy'] < float(criteria.get('minEnergy', 0.2)):
                reasons.append(f"Low energy ({track['energy']*100:.0f}%)")
            
            if reasons:
                tracks_to_remove.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0],
                    'reason': ', '.join(reasons)
                })
        
        return jsonify({
            'tracksToRemove': tracks_to_remove,
            'totalTracks': len(analysis['track_details']),
            'affectedTracks': len(tracks_to_remove)
        })
    except Exception as e:
        logger.error(f"Optimization analysis error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/optimize/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def optimize_playlist(playlist_id):
    try:
        criteria = request.json
        manager = SpotifyPlaylistManager(playlist_id)
        result = manager.optimize_playlist(criteria)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Optimization error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout', methods=['POST'])
def logout():
    try:
        # Clear Spotify OAuth token
        spotify_service.clear_auth()
        
        # Clear all session data
        session.clear()
        
        # Clear Flask session
        session.pop('token_info', None)
        session.pop('user_info', None)
        session.pop('oauth_state', None)
        
        # Add success message
        flash('Successfully logged out', 'success')
        
        # Force client-side cache clearing
        response = redirect(url_for('index'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        flash('Error during logout', 'error')
        return redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error="An internal error occurred"), 500

# This is what Gunicorn uses
def create_app():
    return app

if __name__ == '__main__':
    # Check required environment variables
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 
                    'SPOTIFY_REDIRECT_URI', 'FLASK_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
