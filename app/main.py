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

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='spotify_session'
)

CORS(app)
Session(app)

spotify_service = SpotifyService()

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.before_request
def check_session():
    if request.path == '/':
        return None
        
    if 'token_info' in session:
        try:
            created_at = session.get('created_at')
            if created_at:
                created_at = datetime.fromisoformat(created_at)
                if datetime.now() - created_at > timedelta(hours=1):
                    session.clear()
                    return redirect(url_for('index'))
                    
            if spotify_service.is_token_expired(session['token_info']):
                try:
                    new_token = spotify_service.refresh_token(session['token_info'])
                    session['token_info'] = new_token
                    session['created_at'] = datetime.now().isoformat()
                except Exception as e:
                    logger.error(f"Token refresh failed: {str(e)}")
                    session.clear()
                    return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Session check error: {str(e)}")
            session.clear()
            return redirect(url_for('index'))

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    if not path:
        if session.get('token_info'):
            return redirect(url_for('dashboard'))
        return render_template('index.html')
    elif path in ['dashboard', 'login', 'callback']:
        return redirect(url_for(path))
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
        code = request.args.get('code')
        state = request.args.get('state')
        stored_state = session.get('oauth_state')
        
        if not code:
            flash('Authentication failed: No code received', 'error')
            return redirect(url_for('index'))
        
        if state != stored_state:
            flash('Authentication failed: State verification failed', 'error')
            return redirect(url_for('index'))

        token_info = spotify_service.get_token(code)
        if not token_info:
            flash('Authentication failed: No token received', 'error')
            return redirect(url_for('index'))
            
        session['token_info'] = token_info
        session['created_at'] = datetime.now().isoformat()
        
        sp = spotify_service.get_spotify_client()
        if not sp:
            flash('Failed to initialize Spotify client', 'error')
            return redirect(url_for('index'))
            
        user_info = sp.current_user()
        session['user_info'] = {
            'id': user_info['id'],
            'name': user_info['display_name'],
            'image': user_info['images'][0]['url'] if user_info.get('images') else None
        }
        
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

@app.route('/api/analyze-optimization/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def analyze_optimization(playlist_id):
    try:
        criteria = request.json
        if not criteria:
            return jsonify({'error': 'No criteria provided'}), 400
            
        manager = SpotifyPlaylistManager(playlist_id)
        
        # Get the playlist tracks and analyze them
        tracks = manager.get_playlist_tracks()
        
        tracks_to_remove = []
        for track in tracks:
            if not track.get('track'):
                continue
                
            track_data = track['track']
            reasons = []
            
            # Check popularity
            if track_data['popularity'] < int(criteria.get('minPopularity', 30)):
                reasons.append(f"Low popularity ({track_data['popularity']}%)")
            
            # Check energy
            energy = manager.get_energy(track_data['id'])
            if energy < float(criteria.get('minEnergy', 0.2)):
                reasons.append(f"Low energy ({energy*100:.0f}%)")
            
            if reasons:
                tracks_to_remove.append({
                    'id': track_data['id'],
                    'name': track_data['name'],
                    'artist': track_data['artists'][0]['name'],
                    'reasons': reasons,
                    'popularity': track_data['popularity'],
                    'energy': energy
                })
        
        return jsonify({
            'tracksToRemove': tracks_to_remove,
            'totalTracks': len(tracks),
            'affectedTracks': len(tracks_to_remove)
        })
        
    except Exception as e:
        logger.error(f"Optimization analysis error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/optimize/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def optimize_playlist(playlist_id):
    try:
        criteria = request.json
        if not criteria:
            return jsonify({'error': 'No optimization criteria provided'}), 400
            
        manager = SpotifyPlaylistManager(playlist_id)
        tracks_to_remove = []
        
        # Get all tracks
        tracks = manager.get_playlist_tracks()
        
        for track in tracks:
            if not track.get('track'):
                continue
                
            track_data = track['track']
            remove = False
            
            # Check criteria
            if track_data['popularity'] < int(criteria.get('minPopularity', 30)):
                remove = True
            
            energy = manager.get_energy(track_data['id'])
            if energy < float(criteria.get('minEnergy', 0.2)):
                remove = True
            
            if remove:
                tracks_to_remove.append(track_data['id'])
        
        # Remove tracks if specified
        if criteria.get('autoRemove') and tracks_to_remove:
            track_uris = [f"spotify:track:{track_id}" for track_id in tracks_to_remove]
            manager.sp.playlist_remove_all_occurrences_of_items(playlist_id, track_uris)
        
        return jsonify({
            'message': f'Successfully optimized playlist. Removed {len(tracks_to_remove)} tracks.',
            'removedTracks': len(tracks_to_remove)
        })
        
    except Exception as e:
        logger.error(f"Optimization error: {str(e)}", exc_info=True)
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
        
       
        if not manager.verify_playlist():
            return jsonify({'error': 'Playlist not found or not accessible'}), 404

     
        manager.add_similar_tracks(track_ids)
        
        return jsonify({
            'message': f'Successfully added {len(track_ids)} tracks',
            'added_tracks': len(track_ids)
        })
        
    except Exception as e:
        logger.error(f"Error adding similar tracks: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/logout', methods=['POST'])
def logout():
    try:
        if spotify_service:
            spotify_service.clear_auth()
        session.clear()
        response = redirect(url_for('index'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        flash('Successfully logged out', 'success')
        return response
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return redirect(url_for('index'))

@app.route('/api/playlist/<playlist_id>/similar', methods=['GET'])
@spotify_service.require_auth
@rate_limit
def get_similar_tracks(playlist_id):
    try:
        logger.info(f"Starting similar tracks request for playlist: {playlist_id}")
        
       
        manager = SpotifyPlaylistManager(playlist_id)
        
        
        if not manager.verify_playlist():
            logger.error(f"Playlist {playlist_id} not found or not accessible")
            return jsonify({
                'error': 'Playlist not found or not accessible'
            }), 404
        
       
        similar_tracks = manager.get_similar_tracks(limit=20)
        
        if not similar_tracks:
            logger.warning("No similar tracks found")
            return jsonify({
                'tracks': [],
                'total': 0,
                'message': 'No similar tracks found'
            })

        response = {
            'tracks': similar_tracks,
            'total': len(similar_tracks)
        }
        
        logger.info(f"Successfully found {len(similar_tracks)} similar tracks")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Similar tracks error: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Failed to fetch similar tracks',
            'details': str(e)
        }), 500

@app.errorhandler(404)
def not_found_error(error):
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error="An internal error occurred"), 500

def create_app():
    return app

if __name__ == '__main__':
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 
                    'SPOTIFY_REDIRECT_URI', 'FLASK_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
