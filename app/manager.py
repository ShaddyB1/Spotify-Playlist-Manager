import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
from typing import Dict, List, Optional
from collections import defaultdict
from typing import Any
import time
from requests.exceptions import RequestException
from spotipy.exceptions import SpotifyException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlaylistAnalysisError(Exception):
    """Custom exception for playlist analysis errors."""
    pass

class SpotifyRateLimitError(Exception):
    """Custom exception for rate limit errors."""
    pass

class SpotifyPlaylistManager:
    def __init__(self, playlist_id: str):
        """Initialize the Spotify client with comprehensive scope."""
        load_dotenv()
    
        self.scope = (
            "playlist-modify-public playlist-modify-private "
            "user-library-read user-read-recently-played "
            "user-read-playback-state playlist-read-private "
            "user-top-read user-read-email "
            "user-read-private user-follow-read user-follow-modify "
            "playlist-read-collaborative "
            "user-read-currently-playing user-read-playback-position "
            "streaming app-remote-control "
            "user-library-modify user-read-audio-features"
        )
        self.rate_limit_delay = 1
        
        # Map common category names to Spotify category IDs
        self.category_id_map = {
            'pop': '0JQ5DAqbMKFEC4WFtoNRpw',
            'rock': '0JQ5DAqbMKFDXXwE9BDJAr',
            'hip hop': '0JQ5DAqbMKFQ00XGBls6ym',
            'hip-hop': '0JQ5DAqbMKFQ00XGBls6ym',
            'r&b': '0JQ5DAqbMKFEZPnFQSFB1T',
            'indie': '0JQ5DAqbMKFCWjUTdzaG0e',
            'indie rock': '0JQ5DAqbMKFCWjUTdzaG0e',
            'alternative': '0JQ5DAqbMKFFtlLYUHv8bT',
            'electronic': '0JQ5DAqbMKFHOzuVTgTizF',
            'dance': '0JQ5DAqbMKFHOzuVTgTizF',
            'edm': '0JQ5DAqbMKFHOzuVTgTizF',
            'jazz': '0JQ5DAqbMKFAJ5xb0fwo9m',
            'classical': '0JQ5DAqbMKFPrEiAOxgac3',
            'country': '0JQ5DAqbMKFKLfwjuJMoNC',
            'folk': '0JQ5DAqbMKFy78wprEpAjl',
            'americana': '0JQ5DAqbMKFy78wprEpAjl',
            'metal': '0JQ5DAqbMKFDkd668ypn6O',
            'blues': '0JQ5DAqbMKFQiK2EHwyjcU',
            'soul': '0JQ5DAqbMKFIpEuaCnimBj',
            'reggae': '0JQ5DAqbMKFIpEuaCnimBj',  # No specific reggae category, using Soul as fallback
            'punk': '0JQ5DAqbMKFAjfauKLOZiv',
            'funk': '0JQ5DAqbMKFFsW9N8maB6z',
            'latin': '0JQ5DAqbMKFxXaXKP7zcDp',
            'world': '0JQ5DAqbMKFAQy4HL4XU2D',  # Using Travel as fallback
            'ambient': '0JQ5DAqbMKFLjmiZRss79w',
            'chill': '0JQ5DAqbMKFFzDl7qN9Apr'
        }
        
        try:
            # Get credentials from environment
            client_id = os.getenv('SPOTIFY_CLIENT_ID')
            client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
            redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')
            
            # Validate credentials
            if not client_id or not client_secret or not redirect_uri:
                missing = []
                if not client_id: missing.append('SPOTIFY_CLIENT_ID')
                if not client_secret: missing.append('SPOTIFY_CLIENT_SECRET')
                if not redirect_uri: missing.append('SPOTIFY_REDIRECT_URI')
                error_msg = f"Missing required Spotify credentials: {', '.join(missing)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Log credential info (without revealing secrets)
            logger.info(f"Using Spotify credentials - Client ID: {client_id[:5]}... Redirect URI: {redirect_uri}")
            
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=self.scope,
                cache_handler=None
            )
            
            self.sp = spotipy.Spotify(
                auth_manager=auth_manager,
                requests_timeout=60,
                retries=3,
                backoff_factor=2
            )
            self.playlist_id = playlist_id
            logger.info(f"Successfully initialized SpotifyPlaylistManager for playlist: {playlist_id}")
            
            # Verify credentials by making a simple API call
            self._verify_credentials()
            
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise

    def _handle_rate_limit(self, e: Exception) -> None:
        """Handle rate limit errors with exponential backoff."""
        if hasattr(e, 'headers') and 'Retry-After' in e.headers:
            delay = int(e.headers['Retry-After'])
        else:
            delay = self.rate_limit_delay
            self.rate_limit_delay *= 2  
        
        logger.warning(f"Rate limit hit, waiting {delay} seconds")
        time.sleep(delay)

    def _make_spotify_request(self, func, *args, **kwargs):
        """Make a Spotify API request with retry logic and rate limiting."""
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                logger.info(f"Making Spotify API request: {func.__name__} (attempt {retry_count + 1}/{max_retries})")
                result = func(*args, **kwargs)
                logger.info(f"Spotify API request successful: {func.__name__}")
                return result
            except Exception as e:
                error_str = str(e)
                logger.warning(f"Spotify API error: {error_str}")
                
                # Handle rate limiting
                if 'status: 429' in error_str and retry_count < max_retries - 1:
                    self._handle_rate_limit(e)
                    retry_count += 1
                    continue
                
                # Handle authentication errors
                if 'status: 401' in error_str or 'invalid_client' in error_str:
                    logger.error(f"Authentication error in {func.__name__}: {error_str}. Check your Spotify API credentials.")
                    # Try to refresh the token
                    try:
                        if hasattr(self.sp, 'auth_manager') and hasattr(self.sp.auth_manager, 'refresh_access_token'):
                            logger.info("Attempting to refresh access token...")
                            self.sp.auth_manager.refresh_access_token()
                            retry_count += 1
                            time.sleep(1)  # Wait a bit before retrying
                            continue
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token: {refresh_error}")
                
                # Handle permission errors
                if 'status: 403' in error_str:
                    logger.error(f"Permission denied for {func.__name__}: {error_str}")
                    logger.error(f"Request details - Function: {func.__name__}, Args: {args}, Kwargs: {kwargs}")
                    logger.error("This is likely due to missing scopes. Check if your app has the required scopes in the Spotify Developer Dashboard.")
                    logger.error(f"Current scopes: {self.scope}")
                    
                    if retry_count < max_retries - 1:
                        wait_time = 2 * (retry_count + 1)  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                        retry_count += 1
                        continue
                
                # If we've reached max retries or it's not a retryable error
                if retry_count >= max_retries - 1:
                    logger.error(f"Max retries reached for Spotify API request: {func.__name__}")
                raise e

    def get_playlist_tracks(self) -> List[Dict]:
        """Get all tracks from the playlist with pagination."""
        try:
            tracks = []
            results = self._make_spotify_request(self.sp.playlist_tracks, self.playlist_id)
            
            while results:
                tracks.extend(results['items'])
                if results['next']:
                    results = self._make_spotify_request(self.sp.next, results)
                else:
                    break
            
            
            valid_tracks = [
                track for track in tracks 
                if track and track.get('track') and track['track'].get('id')
            ]
                    
            logger.info(f"Retrieved {len(valid_tracks)} tracks from playlist {self.playlist_id}")
            return valid_tracks
        except Exception as e:
            logger.error(f"Error retrieving playlist tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to get playlist tracks: {str(e)}")

    def get_audio_features_batch(self, track_ids: List[str]) -> Dict[str, float]:
        """Get audio features for multiple tracks in one request."""
        if not track_ids:
            logger.warning("No track IDs provided for audio features")
            return {}
            
        try:
            features_dict = {}
            batch_size = 10  # Reduced from 15 to be even safer with API limits
            
            logger.info(f"Getting audio features for {len(track_ids)} tracks in batches of {batch_size}")
            
            for i in range(0, len(track_ids), batch_size):
                batch = track_ids[i:i+batch_size]
                batch_ids_str = ','.join(batch[:5]) + '...' if len(batch) > 5 else ','.join(batch)
                
                try:
                    # Add more delay to avoid rate limiting
                    time.sleep(4)  # Increased from 3 to 4 seconds
                    
                    logger.info(f"Requesting audio features for batch {i//batch_size + 1} of {(len(track_ids) + batch_size - 1)//batch_size} ({len(batch)} tracks, IDs: {batch_ids_str})")
                    
                    # Try to use the audio_features endpoint first
                    got_batch_features = False
                    features = []
                    
                    try:
                        if hasattr(self.sp, 'audio_features'):
                            features = self._make_spotify_request(
                                self.sp.audio_features,
                                batch
                            )
                            
                            # Log the response structure for debugging
                            if features:
                                logger.info(f"Audio features response type: {type(features)}, length: {len(features) if isinstance(features, list) else 'not a list'}")
                                got_batch_features = True
                            else:
                                logger.warning(f"Empty response from audio_features for batch {i//batch_size + 1}")
                    except Exception as batch_error:
                        logger.warning(f"Batch audio_features request failed: {str(batch_error)}")
                        
                    # If batch request failed or returned empty, use fallback methods
                    if not got_batch_features or not features:
                        logger.info("Using fallback methods to get audio features")
                        features = []
                        
                        for track_id in batch:
                            try:
                                # First try individual audio_features call
                                try:
                                    time.sleep(1)
                                    logger.info(f"Trying individual audio_features call for track {track_id}")
                                    feature = self._make_spotify_request(
                                        self.sp.audio_features,
                                        [track_id]
                                    )
                                    if feature and len(feature) > 0 and feature[0]:
                                        features.append(feature[0])
                                        continue
                                except Exception as e:
                                    logger.warning(f"Individual audio_features call failed for {track_id}: {str(e)}")
                                
                                # If that fails, use our fallback method that uses the tracks API
                                logger.info(f"Using track info fallback for {track_id}")
                                fallback_feature = self._get_track_info_fallback(track_id)
                                features.append(fallback_feature)
                                
                            except Exception as e:
                                logger.error(f"All fallback methods failed for track {track_id}: {str(e)}")
                                features.append(None)
                    
                    if features:
                        valid_features = [f for f in features if f]
                        logger.info(f"Successfully retrieved audio features for {len(valid_features)}/{len(batch)} tracks")
                        
                        for track_id, feature in zip(batch, features):
                            if feature:
                                # Store all audio features, not just energy
                                features_dict[track_id] = {
                                    'energy': feature.get('energy', 0.5),
                                    'danceability': feature.get('danceability', 0.5),
                                    'valence': feature.get('valence', 0.5),
                                    'tempo': feature.get('tempo', 120.0),
                                    'acousticness': feature.get('acousticness', 0.5),
                                    'instrumentalness': feature.get('instrumentalness', 0.0)
                                }
                                logger.debug(f"Audio features for track {track_id}: energy={feature.get('energy', 0.5):.2f}, danceability={feature.get('danceability', 0.5):.2f}")
                            else:
                                logger.warning(f"No features returned for track {track_id}")
                                features_dict[track_id] = {
                                    'energy': 0.5,
                                    'danceability': 0.5,
                                    'valence': 0.5,
                                    'tempo': 120.0,
                                    'acousticness': 0.5,
                                    'instrumentalness': 0.0
                                }
                                
                except Exception as e:
                    logger.error(f"Error processing batch {i//batch_size + 1}: {str(e)}", exc_info=True)
                    # Still provide default values for tracks in this batch
                    for track_id in batch:
                        features_dict[track_id] = {
                            'energy': 0.5,
                            'danceability': 0.5,
                            'valence': 0.5,
                            'tempo': 120.0,
                            'acousticness': 0.5,
                            'instrumentalness': 0.0
                        }
                        
            logger.info(f"Completed audio features retrieval for {len(features_dict)}/{len(track_ids)} tracks")
            return features_dict
        except Exception as e:
            logger.error(f"Error getting audio features for batch: {str(e)}", exc_info=True)
            # Return empty dict as fallback
            return {}

    def get_energy(self, track_id: str) -> float:
        """Get energy value for a track."""
        try:
            features = self.get_audio_features_batch([track_id])
            if track_id in features:
                # Check if features is a dictionary with energy key or a nested dictionary
                if isinstance(features[track_id], dict) and 'energy' in features[track_id]:
                    return features[track_id]['energy']
                elif isinstance(features[track_id], (int, float)):
                    return float(features[track_id])
            return 0.0
        except Exception as e:
            logger.error(f"Error getting energy for track {track_id}: {str(e)}")
            return 0.0

    def analyze_tracks(self) -> Dict[str, Any]:
        """Analyze tracks for potential removal based on multiple factors."""
        try:
            logger.info("Getting playlist information")
            playlist_info = self._make_spotify_request(
                self.sp.playlist, 
                self.playlist_id, 
                fields='name'
            )
            
            logger.info("Starting get_playlist_tracks")
            tracks = self.get_playlist_tracks()
            logger.info(f"Retrieved {len(tracks)} tracks")
            
            logger.info("Getting recently played tracks")
            try:
                recent_plays = self._make_spotify_request(
                    self.sp.current_user_recently_played,
                    limit=50
                )
                recent_plays_lookup = {
                    item['track']['id']: {
                        'played_at': datetime.fromisoformat(item['played_at'].replace('Z', '+00:00')),
                        'context': item.get('context')
                    } for item in recent_plays['items'] if item.get('track', {}).get('id')
                }
            except Exception as e:
                logger.warning(f"Failed to get recent plays: {e}")
                recent_plays_lookup = {}

            analysis = {
                'playlist_name': playlist_info.get('name', 'Untitled Playlist'),
                'total_tracks': len(tracks),
                'played_tracks': 0,
                'skipped_tracks': 0,
                'inactive_tracks': 0,
                'duplicates': [],
                'track_details': [],
                'genre_distribution': defaultdict(int),
                'artist_distribution': defaultdict(int),
                'popularity_distribution': defaultdict(int),
                'decade_distribution': defaultdict(int),
                'total_duration_ms': 0,
                'explicit_tracks': 0,
                'preview_available': 0,
                'energy_ranges': defaultdict(int),
                'tempo_distribution': defaultdict(int),
                'key_distribution': defaultdict(int),
                'mode_distribution': defaultdict(int),
                'time_signature_distribution': defaultdict(int)
            }

            track_ids = [track['track']['id'] for track in tracks if track.get('track', {}).get('id')]
            
            all_audio_features = {}
            for i in range(0, len(track_ids), 25):
                batch_ids = track_ids[i:i+25]
                try:
                    logger.info(f"Getting audio features for analysis batch {i//25 + 1}/{(len(track_ids) + 24)//25}")
                    # Use our improved audio features batch method
                    batch_features = self.get_audio_features_batch(batch_ids)
                    all_audio_features.update(batch_features)
                except Exception as e:
                    logger.error(f"Error getting audio features batch: {e}")
                    # Add default values for tracks in this batch
                    for track_id in batch_ids:
                        all_audio_features[track_id] = {
                            'energy': 0.5,
                            'danceability': 0.5,
                            'valence': 0.5,
                            'tempo': 120.0,
                            'acousticness': 0.5,
                            'instrumentalness': 0.0
                        }
                time.sleep(2)

            seen_track_ids = set()
            
            for track_item in tracks:
                try:
                    track = track_item.get('track')
                    if not track or not track.get('id'):
                        continue

                    track_id = track['id']
                    
                    # Check for duplicates
                    if track_id in seen_track_ids:
                        analysis['duplicates'].append(track['name'])
                    seen_track_ids.add(track_id)

                    
                    audio_features = all_audio_features.get(track_id, {})
                    
                    track_info = {
                        'id': track_id,
                        'name': track['name'],
                        'artists': [artist['name'] for artist in track['artists']],
                        'added_at': track_item.get('added_at', ''),
                        'popularity': track.get('popularity', 0),
                        'duration_ms': track.get('duration_ms', 0),
                        'explicit': track.get('explicit', False),
                        'preview_url': track.get('preview_url'),
                        'energy': audio_features.get('energy', 0.0),
                        'tempo': audio_features.get('tempo', 0.0),
                        'key': audio_features.get('key', -1),
                        'mode': audio_features.get('mode', 0),
                        'time_signature': audio_features.get('time_signature', 4),
                        'danceability': audio_features.get('danceability', 0.0),
                        'instrumentalness': audio_features.get('instrumentalness', 0.0),
                        'valence': audio_features.get('valence', 0.0),
                        'album': track.get('album', {}).get('name', 'Unknown Album'),
                        'release_date': track.get('album', {}).get('release_date', ''),
                        'album_type': track.get('album', {}).get('album_type', 'unknown'),
                        'uri': track.get('uri', '')
                    }

                    
                    analysis['popularity_distribution'][track_info['popularity'] // 10 * 10] += 1
                    analysis['energy_ranges'][int(track_info['energy'] * 10) * 10] += 1
                    analysis['key_distribution'][track_info['key']] += 1
                    analysis['mode_distribution'][track_info['mode']] += 1
                    analysis['time_signature_distribution'][track_info['time_signature']] += 1

                    for artist in track_info['artists']:
                        analysis['artist_distribution'][artist] += 1

                    if track_info['release_date']:
                        try:
                            year = int(track_info['release_date'][:4])
                            decade = (year // 10) * 10
                            analysis['decade_distribution'][decade] += 1
                        except (ValueError, TypeError):
                            pass

                    if track_id in recent_plays_lookup:
                        track_info['last_played'] = recent_plays_lookup[track_id]['played_at'].isoformat()
                        analysis['played_tracks'] += 1
                    else:
                        track_info['last_played'] = None
                        analysis['inactive_tracks'] += 1

                    analysis['total_duration_ms'] += track_info['duration_ms']
                    if track_info['explicit']:
                        analysis['explicit_tracks'] += 1
                    if track_info['preview_url']:
                        analysis['preview_available'] += 1

                    analysis['track_details'].append(track_info)

                except Exception as track_error:
                    logger.error(f"Error processing track: {str(track_error)}")
                    continue

            
            if len(analysis['track_details']) > 0:
                analysis.update({
                    'average_popularity': sum(t['popularity'] for t in analysis['track_details']) / len(analysis['track_details']),
                    'average_energy': sum(t['energy'] for t in analysis['track_details']) / len(analysis['track_details']),
                    'average_tempo': sum(t['tempo'] for t in analysis['track_details']) / len(analysis['track_details']),
                    'average_danceability': sum(t['danceability'] for t in analysis['track_details']) / len(analysis['track_details']),
                    'average_valence': sum(t['valence'] for t in analysis['track_details']) / len(analysis['track_details']),
                    'explicit_percentage': (analysis['explicit_tracks'] / len(analysis['track_details'])) * 100,
                    'active_percentage': (analysis['played_tracks'] / len(analysis['track_details'])) * 100
                })
            else:
                analysis.update({
                    'average_popularity': 0,
                    'average_energy': 0,
                    'average_tempo': 0,
                    'average_danceability': 0,
                    'average_valence': 0,
                    'explicit_percentage': 0,
                    'active_percentage': 0
                })

            
            for dist_key in [
                'artist_distribution', 
                'popularity_distribution', 
                'decade_distribution',
                'energy_ranges',
                'key_distribution',
                'mode_distribution'
            ]:
                if dist_key in analysis:
                    analysis[dist_key] = dict(
                        sorted(
                            analysis[dist_key].items(),
                            key=lambda x: x[1],
                            reverse=True
                        )
                    )

            logger.info(f"Completed analysis for playlist {self.playlist_id}")
            return self.convert_to_serializable(analysis)

        except Exception as e:
            logger.error(f"Error analyzing tracks: {str(e)}", exc_info=True)
            raise PlaylistAnalysisError(f"Failed to analyze tracks: {str(e)}")  

    def optimize_playlist(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize playlist based on given criteria with improved error handling."""
        try:
            logger.info(f"Starting playlist optimization with criteria: {criteria}")
            
            
            analysis = self.analyze_tracks()
            
            if not analysis['track_details']:
                raise PlaylistAnalysisError("No tracks found in playlist")
                
            tracks_to_remove = []
            min_popularity = int(criteria.get('minPopularity', 30))
            min_energy = float(criteria.get('minEnergy', 0.2))
            
            for track in analysis['track_details']:
                reasons = []
                
                
                try:
                    if track['popularity'] < min_popularity:
                        reasons.append(f"Low popularity ({track['popularity']}%)")
                    
                    if track['energy'] < min_energy:
                        reasons.append(f"Low energy ({track['energy']*100:.0f}%)")
                        
                    if reasons:
                        tracks_to_remove.append({
                            'id': track['id'],
                            'name': track['name'],
                            'artist': track['artists'][0] if track['artists'] else 'Unknown Artist',
                            'popularity': track['popularity'],
                            'energy': track['energy'],
                            'reasons': reasons
                        })
                except (KeyError, TypeError) as e:
                    logger.warning(f"Error processing track criteria: {str(e)}")
                    continue
            
            
            removed_tracks = []
            if criteria.get('autoRemove') and tracks_to_remove:
                try:
                    track_uris = [f"spotify:track:{track['id']}" for track in tracks_to_remove]
                    
                    
                    for i in range(0, len(track_uris), 100):
                        batch = track_uris[i:i+100]
                        try:
                            time.sleep(self.rate_limit_delay)  
                            self._make_spotify_request(
                                self.sp.playlist_remove_all_occurrences_of_items,
                                self.playlist_id,
                                batch
                            )
                            removed_tracks.extend(batch)
                        except Exception as batch_error:
                            logger.error(f"Error removing batch of tracks: {str(batch_error)}")
                except Exception as remove_error:
                    logger.error(f"Error during track removal: {str(remove_error)}")
            
            result = {
                'playlistName': analysis['playlist_name'],
                'tracksAnalyzed': len(analysis['track_details']),
                'tracksToRemove': tracks_to_remove,
                'tracksRemoved': len(removed_tracks) if criteria.get('autoRemove') else 0,
                'criteriaUsed': {
                    'minPopularity': min_popularity,
                    'minEnergy': min_energy,
                    'autoRemove': criteria.get('autoRemove', False)
                }
            }
            
            logger.info(f"Optimization complete. Found {len(tracks_to_remove)} tracks to remove.")
            return self.convert_to_serializable(result)
            
        except Exception as e:
            logger.error(f"Optimization error: {str(e)}", exc_info=True)
            raise PlaylistAnalysisError(f"Failed to optimize playlist: {str(e)}")

    def get_similar_tracks(self, limit: int = 20) -> List[Dict]:
        """Get similar tracks based on playlist tracks and audio features."""
        try:
            logger.info(f"Starting to get similar tracks for playlist: {self.playlist_id}")
            
            # Get playlist tracks
            tracks = self.get_playlist_tracks()
            logger.info(f"Got {len(tracks)} tracks from playlist")
            
            if not tracks:
                logger.warning("No tracks found in playlist")
                return []
    
            # Get audio features for all tracks to make better selections
            track_ids = [track['track']['id'] for track in tracks if track.get('track', {}).get('id')]
            if not track_ids:
                logger.warning("No valid track IDs found in playlist")
                return []
                
            try:
                features = self.get_audio_features_batch(track_ids)
                logger.info(f"Retrieved audio features for {len(features)} tracks")
            except Exception as e:
                logger.error(f"Error getting audio features: {e}", exc_info=True)
                features = {}
            
            # Select diverse seed tracks based on audio features if available
            seed_tracks = []
            
            # If we have features, try to select diverse tracks
            if features and len(features) > 5:
                # Sort tracks by energy to get a range
                energy_sorted = sorted(
                    [(tid, features[tid]['energy'] if isinstance(features[tid], dict) else 0.0) 
                     for tid in features],
                    key=lambda x: x[1]
                )
                
                # Get tracks from different energy levels
                if len(energy_sorted) >= 5:
                    indices = [0, len(energy_sorted)//4, len(energy_sorted)//2, 
                              3*len(energy_sorted)//4, len(energy_sorted)-1]
                    seed_tracks = [energy_sorted[i][0] for i in indices]
                    logger.info(f"Selected diverse seed tracks based on energy: {seed_tracks}")
            
            # If we couldn't select diverse tracks, fall back to the first 5 tracks
            if len(seed_tracks) < 5:
                for track in tracks:
                    try:
                        if track and track.get('track') and track['track'].get('id'):
                            if track['track']['id'] not in seed_tracks:
                                seed_tracks.append(track['track']['id'])
                                if len(seed_tracks) >= 5:
                                    break
                    except Exception as e:
                        logger.error(f"Error processing potential seed track: {e}")
                        continue
    
            logger.info(f"Selected {len(seed_tracks)} seed tracks: {seed_tracks}")
    
            if len(seed_tracks) == 0:
                logger.error("No valid seed tracks found")
                return []
    
            # Get recommendations with more parameters for better results
            try:
                logger.info("Requesting recommendations from Spotify")
                
                # Calculate average audio features to use as targets
                avg_features = {}
                if features:
                    feature_keys = ['energy', 'danceability', 'valence', 'acousticness']
                    for key in feature_keys:
                        values = []
                        for tid in features:
                            if isinstance(features[tid], dict) and key in features[tid]:
                                values.append(features[tid][key])
                        if values:
                            avg_features[f'target_{key}'] = sum(values) / len(values)
                
                # Add the average features to the recommendation request
                recommendation_params = {
                    'seed_tracks': seed_tracks[:5],
                    'limit': min(limit * 2, 100),  # Request more tracks to filter later
                    'min_popularity': 30
                }
                recommendation_params.update(avg_features)
                
                recommendations = self._make_spotify_request(
                    self.sp.recommendations,
                    **recommendation_params
                )
                
                logger.info(f"Got recommendations response: {recommendations.keys() if recommendations else 'None'}")
            except Exception as e:
                logger.error(f"Error getting recommendations: {e}", exc_info=True)
                return []
    
            # Get existing track IDs
            existing_ids = {
                track['track']['id'] for track in tracks 
                if track.get('track', {}).get('id')
            }
    
            # Process recommendations
            similar_tracks = []
            for track in recommendations.get('tracks', []):
                try:
                    if track['id'] not in existing_ids:
                        similar_tracks.append({
                            'id': track['id'],
                            'name': track['name'],
                            'artist': track['artists'][0]['name'] if track['artists'] else 'Unknown',
                            'album': track['album']['name'] if track.get('album') else 'Unknown',
                            'image': track['album']['images'][0]['url'] if track.get('album', {}).get('images') and track['album']['images'] else None,
                            'uri': track['uri'],
                            'popularity': track.get('popularity', 0)
                        })
                except Exception as e:
                    logger.error(f"Error processing recommendation track: {e}")
                    continue
            
            # Sort by popularity and limit to requested number
            similar_tracks.sort(key=lambda x: x.get('popularity', 0), reverse=True)
            similar_tracks = similar_tracks[:limit]
    
            logger.info(f"Found {len(similar_tracks)} similar tracks that are not already in the playlist")
            return similar_tracks
            
        except Exception as e:
            logger.error(f"Error getting similar tracks: {e}", exc_info=True)
            return []


    def add_similar_tracks(self, track_ids: List[str]) -> bool:
        """Add similar tracks with improved error handling and rate limiting."""
        try:
            if not track_ids:
                return False

            track_uris = [f"spotify:track:{track_id}" for track_id in track_ids if track_id]
            
            
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                try:
                    time.sleep(self.rate_limit_delay)
                    self._make_spotify_request(
                        self.sp.playlist_add_items,
                        self.playlist_id,
                        batch
                    )
                except Exception as batch_error:
                    logger.error(f"Error adding batch of tracks: {str(batch_error)}")
                    raise
            
            return True
        except Exception as e:
            logger.error(f"Error adding similar tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to add similar tracks: {str(e)}")

    def verify_playlist(self) -> bool:
        """Verify playlist exists and is accessible."""
        try:
            playlist = self._make_spotify_request(
                self.sp.playlist,
                self.playlist_id,
                fields='id,name,owner'
            )
            return bool(playlist and playlist.get('id'))
        except Exception as e:
            logger.error(f"Error verifying playlist {self.playlist_id}: {str(e)}")
            return False

    def convert_to_serializable(self, data: Any) -> Any:
        """Convert complex data types to serializable Python types."""
        try:
            if isinstance(data, defaultdict):
                return dict(data)
            elif isinstance(data, (set, type({}.items()))):
                return list(data)
            elif isinstance(data, dict):
                return {k: self.convert_to_serializable(v) for k, v in data.items()}
            elif isinstance(data, (list, tuple)):
                return [self.convert_to_serializable(x) for x in data]
            elif isinstance(data, datetime):
                return data.isoformat()
            return data
        except Exception as e:
            logger.error(f"Error converting to serializable: {str(e)}")
            return str(data)

    def get_playlist_info(self) -> Dict[str, Any]:
        """Get detailed playlist information."""
        try:
            playlist = self._make_spotify_request(
                self.sp.playlist,
                self.playlist_id,
                fields='id,name,owner,images,tracks.total,description,public,collaborative'
            )
            
            return {
                'id': playlist.get('id'),
                'name': playlist.get('name'),
                'owner': playlist.get('owner', {}).get('display_name'),
                'owner_id': playlist.get('owner', {}).get('id'),
                'image': playlist.get('images', [{}])[0].get('url') if playlist.get('images') else None,
                'total_tracks': playlist.get('tracks', {}).get('total', 0),
                'description': playlist.get('description'),
                'public': playlist.get('public'),
                'collaborative': playlist.get('collaborative')
            }
        except Exception as e:
            logger.error(f"Error getting playlist info: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to get playlist info: {str(e)}")

    def _reset_rate_limit_delay(self):
        """Reset rate limit delay to base value."""
        self.rate_limit_delay = 1

    def _increase_rate_limit_delay(self):
        """Increase rate limit delay with exponential backoff."""
        self.rate_limit_delay = min(self.rate_limit_delay * 2, 32)  

    @staticmethod
    def format_duration(duration_ms: int) -> str:
        """Format duration from milliseconds to readable string."""
        try:
            seconds = int((duration_ms / 1000) % 60)
            minutes = int((duration_ms / (1000 * 60)) % 60)
            hours = int(duration_ms / (1000 * 60 * 60))
            
            if hours > 0:
                return f"{hours}:{minutes:02d}:{seconds:02d}"
            return f"{minutes}:{seconds:02d}"
        except Exception:
            return "0:00"

    def cleanup(self):
        """Cleanup resources and reset state."""
        try:
            self._reset_rate_limit_delay()
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def get_category_playlists(self, category, limit=20):
        """
        Get playlists for a specific category with improved error handling and fallback.
        
        Args:
            category: The name of the category (case-insensitive)
            limit: Maximum number of playlists to return
            
        Returns:
            List of playlist objects or empty list if none found
        """
        # Common category mapping (lowercase name to Spotify ID)
        category_ids = {
            'rock': '0JQ5DAqbMKFHCxg5H5PtqW',
            'pop': '0JQ5DAqbMKFDXXwE9BDJAr',
            'hip hop': '0JQ5DAqbMKFQ00XGBls6ym',
            'r&b': '0JQ5DAqbMKFEZPnFQSFB1T',
            'indie': '0JQ5DAqbMKFAXlCG6QiuXf',
            'dance': '0JQ5DAqbMKFzHmL4tf05da',
            'electronic': '0JQ5DAqbMKFFzDl7qN9Apr',
            'jazz': '0JQ5DAqbMKFAJ5xb0fwo9m',
            'metal': '0JQ5DAqbMKFDTEtSaS4R92',
            'classical': '0JQ5DAqbMKFPrEiAOxgac3',
            'reggae': '0JQ5DAqbMKFIpEuaCnimBj',
            'punk': '0JQ5DAqbMKFAjfauKLOZiv',
            'funk': '0JQ5DAqbMKFFsW9N8maB6z',
            'latin': '0JQ5DAqbMKFxXaXKP7zcDp',
            'world': '0JQ5DAqbMKFAQy4HL4XU2D',
            'ambient': '0JQ5DAqbMKFLjmiZRss79w',
            'chill': '0JQ5DAqbMKFFzDl7qN9Apr'
        }
        
        logger.info(f"Getting playlists for category: {category}")
        
        # Normalize category name for case-insensitive lookup
        category_lower = category.lower()
        category_id = category_ids.get(category_lower, category_lower)
        
        playlists = []
        
        try:
            # First try to get playlists from the category endpoint
            logger.info(f"Attempting to get playlists for category ID: {category_id}")
            results = self._make_spotify_request(
                self.sp.category_playlists, 
                category_id=category_id, 
                limit=limit
            )
            
            if results and 'playlists' in results and 'items' in results['playlists']:
                playlists = results['playlists']['items']
                logger.info(f"Found {len(playlists)} playlists for category {category}")
            else:
                logger.warning(f"No playlists found for category: {category}")
        
        except Exception as e:
            logger.error(f"Error getting category playlists for {category}: {str(e)}")
            
        # If no playlists found or error occurred, try search as fallback
        if not playlists:
            logger.info(f"Falling back to search for category: {category}")
            try:
                search_results = self._make_spotify_request(
                    self.sp.search, 
                    q=f"genre:{category}", 
                    type='playlist', 
                    limit=limit
                )
                
                if search_results and 'playlists' in search_results and 'items' in search_results['playlists']:
                    playlists = search_results['playlists']['items']
                    logger.info(f"Found {len(playlists)} playlists via search for {category}")
            except Exception as e:
                logger.error(f"Error searching for playlists for category {category}: {str(e)}")
        
        return playlists
            
    def search_playlists(self, query, limit=20):
        """Search for playlists by query."""
        try:
            results = self.sp.search(q=query, type='playlist', limit=limit)
            
            if not results or 'playlists' not in results or 'items' not in results['playlists']:
                return []
                
            return results['playlists']['items']
        except Exception as e:
            logger.error(f"Error searching playlists: {str(e)}")
            return []
            
    def follow_playlist(self, playlist_id):
        """Follow a playlist."""
        try:
            self.sp.current_user_follow_playlist(playlist_id=playlist_id)
            return True
        except Exception as e:
            logger.error(f"Error following playlist: {str(e)}")
            return False
            
    def unfollow_playlist(self, playlist_id):
        """Unfollow a playlist."""
        try:
            self.sp.current_user_unfollow_playlist(playlist_id=playlist_id)
            return True
        except Exception as e:
            logger.error(f"Error unfollowing playlist: {str(e)}")
            return False
    
    def _verify_credentials(self):
        """Verify Spotify credentials by making a simple API call."""
        try:
            # Try to get current user info as a simple test
            user_info = self._make_spotify_request(self.sp.current_user)
            if user_info and 'id' in user_info:
                logger.info(f"Successfully verified Spotify credentials for user: {user_info['id']}")
            else:
                logger.warning("Spotify credentials verification returned unexpected response")
        except Exception as e:
            logger.error(f"Failed to verify Spotify credentials: {str(e)}")
            # Don't raise the exception, just log it
    
    def _get_track_info_fallback(self, track_id: str) -> Dict:
        """Fallback method to get basic track information when audio_features fails.
        Uses the tracks API which has better permission access."""
        try:
            logger.info(f"Using fallback method to get track info for {track_id}")
            track_info = self._make_spotify_request(
                self.sp.track,
                track_id
            )
            
            # Create a simplified audio features object with default values
            # but include any information we can get from the track object
            fallback_features = {
                'energy': 0.5,  # Default mid-level values
                'danceability': 0.5,
                'valence': 0.5,
                'tempo': 120.0,
                'acousticness': 0.5,
                'instrumentalness': 0.0,
                'popularity': track_info.get('popularity', 50) / 100.0,  # Normalize to 0-1 range
                'duration_ms': track_info.get('duration_ms', 0),
                'name': track_info.get('name', 'Unknown'),
                'artists': [artist['name'] for artist in track_info.get('artists', [])]
            }
            
            logger.info(f"Successfully retrieved fallback track info for {track_id}")
            return fallback_features
        except Exception as e:
            logger.error(f"Error getting fallback track info for {track_id}: {str(e)}")
            # Return empty default values
            return {
                'energy': 0.5,
                'danceability': 0.5,
                'valence': 0.5,
                'tempo': 120.0,
                'acousticness': 0.5,
                'instrumentalness': 0.0
            }
    
    
        
    
        
