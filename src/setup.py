from setuptools import setup, find_packages

setup(
    name="spotify-playlist-manager",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'Flask==2.0.1',
        'spotipy==2.19.0',
        'python-dotenv==0.19.0',
        'click==8.0.1'
    ],
)