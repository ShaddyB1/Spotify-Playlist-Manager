import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
import numpy as np
from dataclasses import dataclass
from enum import Enum
import time
import traceback

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlaylistAnalysisError(Exception):
    """Custom exception for playlist analysis errors."""
    pass

class OptimizationCriteria(Enum):
    POPULARITY = "popularity"
    ENERGY = "energy"
    DANCEABILITY = "danceability"
    VALENCE = "valence"
    TEMPO = "tempo"
    ACOUSTICNESS = "acousticness"

@dataclass
class OptimizationConfig:
    min_popularity: int = 20
    min_energy: float = 0.2
    max_inactive_days: int = 30
    target_playlist_size: Optional[int] = None
    preserve_top_artists: bool = True
    preserve_recently_added: bool = True
    recent_threshold_days: int = 7
    balance_genres: bool = True
    max_artist_percentage: float = 0.15

class SpotifyPlaylistManager:
    def __init__(self, playlist_id: Optional[str] = None):
        """Initialize the Spotify client with comprehensive scope."""
        load_dotenv()

        # Define the necessary scope for Spotify API
        self.scope = (
            "playlist-modify-public playlist-modify-private "
            "user-library-read user-read-recently-played "
            "user-read-playback-state playlist-read-private "
            "user-top-read"
        )

        # Ensure required environment variables are set
        client_id = os.getenv('SPOTIFY_CLIENT_ID')
        client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')

        if not all([client_id, client_secret, redirect_uri]):
            logger.error("Missing required Spotify environment variables.")
            raise SpotifyAuthError("Spotify authentication details are incomplete.")

        try:
            # Initialize the Spotify client
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=self.scope
            ))
            self.playlist_id = playlist_id
            logger.info(f"Successfully initialized SpotifyPlaylistManager for playlist: {playlist_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise  # Re-raise the exception for further handling


    def get_playlist_tracks(self):
        """Retrieve tracks from the playlist."""
        try:
            results = self.sp.playlist_tracks(self.playlist_id)
            tracks = []
            for item in results['items']:
                track = item['track']
                tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'popularity': track['popularity'],
                    'artists': [artist['name'] for artist in track['artists']],
                    'energy': self.get_energy(track['id'])  
                })
            return tracks
        except Exception as e:
            logger.error(f"Error getting tracks for playlist {self.playlist_id}: {str(e)}")
            raise
    

    
    def analyze_tracks(self, playlist_id: Optional[str] = None) -> Dict[str, Any]:
        """Analyze tracks for potential removal based on multiple factors."""
        try:
            target_playlist_id = playlist_id or self.playlist_id
            tracks = self.get_playlist_tracks(target_playlist_id)
            recent_plays = self.sp.current_user_recently_played(limit=50)
            
            recent_plays_lookup = {
                item['track']['id']: {
                    'played_at': datetime.fromisoformat(item['played_at'].replace('Z', '+00:00')),
                    'context': item.get('context')
                } for item in recent_plays['items']
            }
            
            analysis = {
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
                'audio_features': [],
                'tempo_distribution': [],
                'key_distribution': defaultdict(int),
                'time_signature_distribution': defaultdict(int)
            }
            
            track_ids = set()
            
            for track in tracks:
                if not track['track']:
                    continue
                    
                track_id = track['track']['id']
                
                # Check for duplicates
                if track_id in track_ids:
                    analysis['duplicates'].append(track['track']['name'])
                track_ids.add(track_id)
                
                track_info = {
                    'id': track_id,
                    'name': track['track']['name'],
                    'artists': [artist['name'] for artist in track['track']['artists']],
                    'added_at': track['added_at'],
                    'popularity': track['track']['popularity'],
                    'duration_ms': track['track']['duration_ms'],
                    'explicit': track['track']['explicit'],
                    'preview_url': track['track']['preview_url']
                }
                
                # Update distributions
                analysis['popularity_distribution'][track_info['popularity'] // 10 * 10] += 1
                for artist in track_info['artists']:
                    analysis['artist_distribution'][artist] += 1
                
                # Get audio features
                try:
                    audio_features = self.sp.audio_features([track_id])[0]
                    if audio_features:
                        track_info.update({
                            'danceability': audio_features['danceability'],
                            'energy': audio_features['energy'],
                            'key': audio_features['key'],
                            'tempo': audio_features['tempo'],
                            'valence': audio_features['valence'],
                            'acousticness': audio_features['acousticness']
                        })
                        analysis['audio_features'].append(audio_features)
                        analysis['tempo_distribution'].append(audio_features['tempo'])
                        analysis['key_distribution'][audio_features['key']] += 1
                        analysis['time_signature_distribution'][audio_features['time_signature']] += 1
                except Exception as e:
                    logger.warning(f"Could not get audio features for track {track_id}: {str(e)}")
                
                # Check play history
                if track_id in recent_plays_lookup:
                    track_info['last_played'] = recent_plays_lookup[track_id]['played_at'].isoformat()
                    analysis['played_tracks'] += 1
                else:
                    track_info['last_played'] = None
                    analysis['inactive_tracks'] += 1
                
                analysis['track_details'].append(track_info)
            
            # Calculate averages and additional metrics
            analysis.update({
                'average_popularity': sum(t['popularity'] for t in analysis['track_details']) / len(analysis['track_details']),
                'average_tempo': np.mean(analysis['tempo_distribution']) if analysis['tempo_distribution'] else 0,
                'tempo_variety': np.std(analysis['tempo_distribution']) if analysis['tempo_distribution'] else 0,
                'total_duration_ms': sum(t['duration_ms'] for t in analysis['track_details']),
                'explicit_tracks': sum(1 for t in analysis['track_details'] if t['explicit']),
                'preview_available': sum(1 for t in analysis['track_details'] if t['preview_url'])
            })
            
            logger.info(f"Completed analysis for playlist {target_playlist_id}")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to analyze tracks: {str(e)}")

    def get_similar_tracks(self, limit=10):
        """Get similar tracks based on current playlist's tracks."""
        try:
            current_tracks = self.get_playlist_tracks()  # No arguments needed here
            track_ids = [track['id'] for track in current_tracks]

            if not track_ids:
                logger.warning("No tracks found to find similar songs.")
                return []

            # Assume you have a method to get recommendations based on track IDs
            similar_tracks = self.sp.recommendations(seed_tracks=track_ids, limit=limit)
            similar_tracks_info = [{
                'id': track['id'],
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
            } for track in similar_tracks['tracks']]

            logger.info(f"Found {len(similar_tracks_info)} similar tracks for playlist {self.playlist_id}")
            return similar_tracks_info

        except Exception as e:
            logger.error(f"Error finding similar tracks: {str(e)}")
            raise
    
    def add_similar_tracks(self, track_ids: List[str], playlist_id: Optional[str] = None) -> int:
        """Add selected similar tracks to the playlist."""
        try:
            target_playlist_id = playlist_id or self.playlist_id
            if not target_playlist_id:
                raise ValueError("No playlist ID provided")

            track_uris = [f"spotify:track:{track_id}" for track_id in track_ids]
            
            # Add tracks in batches of 100 (Spotify API limit)
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                self.sp.playlist_add_items(target_playlist_id, batch)

            logger.info(f"Added {len(track_ids)} similar tracks to playlist {target_playlist_id}")
            return len(track_ids)

        except Exception as e:
            logger.error(f"Error adding similar tracks: {str(e)}")
            raise

    def optimize_playlist(self, criteria):
        """Optimize the playlist based on provided criteria."""
        try:
            current_tracks = self.get_playlist_tracks()  # No arguments needed here
            tracks_to_remove = []

            # Example criteria: Remove tracks with low popularity
            if criteria == "low_popularity":
                popularity_threshold = 50  # Define a threshold for popularity
                for track in current_tracks:
                    if track['popularity'] < popularity_threshold:
                        tracks_to_remove.append(track['id'])

            # Remove tracks from the playlist
            if tracks_to_remove:
                self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, tracks_to_remove)
                logger.info(f"Removed {len(tracks_to_remove)} tracks from playlist {self.playlist_id} based on criteria '{criteria}'")
            else:
                logger.info(f"No tracks removed from playlist {self.playlist_id} based on criteria '{criteria}'")

        except Exception as e:
            logger.error(f"Error optimizing playlist: {str(e)}")
            raise

    def update_playlist(self, tracks_to_remove: List[str], tracks_to_add: List[str]) -> bool:
        """Update the playlist by removing and adding tracks."""
        try:
            if tracks_to_remove:
                self.sp.playlist_remove_all_occurrences_of_items(
                    self.playlist_id,
                    tracks_to_remove
                )
                logger.info(f"Removed {len(tracks_to_remove)} tracks from playlist {self.playlist_id}")
            
            if tracks_to_add:
                self.sp.playlist_add_items(
                    self.playlist_id,
                    tracks_to_add
                )
                logger.info(f"Added {len(tracks_to_add)} tracks to playlist {self.playlist_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating playlist: {str(e)}")
            return False

    def get_playlist_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics about the playlist."""
        try:
            analysis = self.analyze_tracks()
            
            metrics = {
                'basic_info': {
                    'total_tracks': analysis['total_tracks'],
                    'total_duration': analysis['total_duration_ms'] / (1000 * 60),  # in minutes
                    'average_popularity': analysis['average_popularity'],
                    'average_tempo': analysis['average_tempo']
                },
                'activity': {
                    'played_tracks': analysis['played_tracks'],
                    'inactive_tracks': analysis['inactive_tracks'],
                    'play_ratio': analysis['played_tracks'] / analysis['total_tracks'] if analysis['total_tracks'] > 0 else 0
                },
                'content': {
                    'explicit_tracks': analysis['explicit_tracks'],
                    'preview_available': analysis['preview_available'],
                    'unique_artists': len(analysis['artist_distribution']),
                    'artist_variety': len(analysis['artist_distribution']) / analysis['total_tracks'] if analysis['total_tracks'] > 0 else 0
                },
                'distributions': {
                    'popularity': dict(sorted(analysis['popularity_distribution'].items())),
                    'artists': dict(sorted(analysis['artist_distribution'].items(), 
                                        key=lambda x: x[1], 
                                        reverse=True)[:10]),  # Top 10 artists
                    'decades': dict(sorted(analysis['decade_distribution'].items())),
                    'tempo': {
                        'mean': np.mean(analysis['tempo_distribution']) if analysis['tempo_distribution'] else 0,
                        'std': np.std(analysis['tempo_distribution']) if analysis['tempo_distribution'] else 0,
                        'ranges': {
                            'slow': len([t for t in analysis['tempo_distribution'] if t < 100]),
                            'medium': len([t for t in analysis['tempo_distribution'] if 100 <= t <= 130]),
                            'fast': len([t for t in analysis['tempo_distribution'] if t > 130])
                        }
                    }
                },
                'audio_features': {
                    'average': {
                        'danceability': np.mean([t.get('danceability', 0) for t in analysis['track_details']]),
                        'energy': np.mean([t.get('energy', 0) for t in analysis['track_details']]),
                        'valence': np.mean([t.get('valence', 0) for t in analysis['track_details']]),
                        'acousticness': np.mean([t.get('acousticness', 0) for t in analysis['track_details']])
                    },
                    'variety': {
                        'danceability': np.std([t.get('danceability', 0) for t in analysis['track_details']]),
                        'energy': np.std([t.get('energy', 0) for t in analysis['track_details']]),
                        'valence': np.std([t.get('valence', 0) for t in analysis['track_details']]),
                        'acousticness': np.std([t.get('acousticness', 0) for t in analysis['track_details']])
                    }
                },
                'recommendations': {
                    'suggested_actions': self._generate_recommendations(analysis)
                }
            }
            
            logger.info(f"Generated metrics for playlist {self.playlist_id}")
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting playlist metrics: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to get playlist metrics: {str(e)}")

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[Dict[str, str]]:
        """Generate recommendations for playlist improvement."""
        recommendations = []

        # Check popularity distribution
        if analysis['average_popularity'] < 40:
            recommendations.append({
                'type': 'popularity',
                'suggestion': 'Consider adding more popular tracks to increase playlist visibility',
                'severity': 'medium'
            })

        # Check artist variety
        artist_variety = len(analysis['artist_distribution']) / analysis['total_tracks']
        if artist_variety < 0.5:
            recommendations.append({
                'type': 'variety',
                'suggestion': 'Consider adding tracks from more different artists',
                'severity': 'high'
            })

        # Check tempo distribution
        if analysis['tempo_distribution']:
            tempo_std = np.std(analysis['tempo_distribution'])
            if tempo_std < 15:
                recommendations.append({
                    'type': 'tempo',
                    'suggestion': 'Consider adding more variety in track tempos',
                    'severity': 'low'
                })

        # Check energy distribution
        if 'energy' in analysis['audio_features']:
            energy_values = [t.get('energy', 0) for t in analysis['track_details']]
            if np.std(energy_values) < 0.2:
                recommendations.append({
                    'type': 'energy',
                    'suggestion': 'Consider adding more variety in track energy levels',
                    'severity': 'medium'
                })

        return recommendations

    def get_user_playlists(self) -> List[Dict]:
        """Get all playlists for the current user."""
        try:
            playlists = []
            results = self.sp.current_user_playlists(limit=50)
            
            while results:
                playlists.extend(results['items'])
                if results['next']:
                    results = self.sp.next(results)
                else:
                    break

            logger.info(f"Retrieved {len(playlists)} playlists for user")
            return playlists
        except Exception as e:
            logger.error(f"Error retrieving user playlists: {str(e)}")
            raise

    def get_current_user(self) -> Dict:
        """Get current user's profile information."""
        try:
            return self.sp.current_user()
        except Exception as e:
            logger.error(f"Error getting current user: {str(e)}")
            raise

    def get_audio_features_batch(self, track_ids: List[str]) -> List[Dict]:
        """Get audio features for a batch of tracks."""
        try:
            features = []
            for i in range(0, len(track_ids), 100):  
                batch = track_ids[i:i+100]
                batch_features = self.sp.audio_features(batch)
                features.extend([f for f in batch_features if f])
            return features
        except Exception as e:
            logger.error(f"Error getting audio features: {str(e)}")
            return []
