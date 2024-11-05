from gevent import monkey
monkey.patch_all()  # This needs to happen before any other imports

from app.main import app

if __name__ == "__main__":
    app.run()
