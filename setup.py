from setuptools import setup, find_packages

setup(
    name="spotify-playlist-manager",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'spotipy',
        'pandas',
        'numpy',
        'click',
        'python-dotenv',
        'SQLAlchemy',
    ],
)