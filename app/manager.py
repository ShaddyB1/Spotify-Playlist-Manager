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
            "user-top-read"
        )
        self.rate_limit_delay = 1
        
        try:
            auth_manager = SpotifyOAuth(
                client_id=os.getenv('SPOTIFY_CLIENT_ID'),
                client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
                redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
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
                return func(*args, **kwargs)
            except Exception as e:
                if 'status: 429' in str(e) and retry_count < max_retries - 1:
                    self._handle_rate_limit(e)
                    retry_count += 1
                    continue
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
        try:
            features_dict = {}
            batch_size = 25  
            
            for i in range(0, len(track_ids), batch_size):
                batch = track_ids[i:i+batch_size]
                
                try:
                   
                    time.sleep(1)
                    
                    features = self.sp.audio_features(batch)
                    if features:
                        for track_id, feature in zip(batch, features):
                            if feature:
                                features_dict[track_id] = feature.get('energy', 0.0)
                            else:
                                features_dict[track_id] = 0.0
                                
                except Exception as e:
                    logger.error(f"Error processing batch: {str(e)}")
                    for track_id in batch:
                        features_dict[track_id] = 0.0
                        
            return features_dict
        except Exception as e:
            logger.error(f"Error getting audio features for batch: {str(e)}")
            return {track_id: 0.0 for track_id in track_ids}

    def get_energy(self, track_id: str) -> float:
        """Get energy level for a single track."""
        if not track_id:
            return 0.0
            
        try:
            features = self.get_audio_features_batch([track_id])
            return features.get(track_id, 0.0)
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
            for i in range(0, len(track_ids), 50):
                batch_ids = track_ids[i:i+50]
                try:
                    batch_features = self._make_spotify_request(
                        self.sp.audio_features,
                        batch_ids
                    )
                    for track_id, features in zip(batch_ids, batch_features):
                        if features:
                            all_audio_features[track_id] = features
                except Exception as e:
                    logger.error(f"Error getting audio features batch: {e}")
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
        """Get similar tracks based on playlist tracks."""
        try:
            logger.info(f"Starting to get similar tracks for playlist: {self.playlist_id}")
            
            # Get playlist tracks
            tracks = self.get_playlist_tracks()
            logger.info(f"Got {len(tracks)} tracks from playlist")
            
            if not tracks:
                logger.warning("No tracks found in playlist")
                return []
    
            # Get seed tracks
            seed_tracks = []
            for track in tracks[:10]:  # Look at first 10 tracks
                try:
                    if track and track.get('track') and track['track'].get('id'):
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
    
            # Get recommendations
            try:
                logger.info("Requesting recommendations from Spotify")
                recommendations = self.sp.recommendations(
                    seed_tracks=seed_tracks[:5],
                    limit=limit,
                    min_popularity=30
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
                            'name': track.get('name', 'Unknown Track'),
                            'artist': track['artists'][0]['name'] if track.get('artists') else 'Unknown Artist',
                            'popularity': track.get('popularity', 0),
                            'preview_url': track.get('preview_url'),
                            'image': (track.get('album', {}).get('images', [{}])[0].get('url')
                                    if track.get('album', {}).get('images') else None)
                        })
                except Exception as e:
                    logger.error(f"Error processing recommendation: {e}")
                    continue
    
            logger.info(f"Returning {len(similar_tracks)} similar tracks")
            return similar_tracks
    
        except Exception as e:
            logger.error(f"Error in get_similar_tracks: {e}", exc_info=True)
            raise


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
    
    
        
    
        
