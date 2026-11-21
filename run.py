from app import create_app

app = create_app()

if __name__ == "__main__":
    # Per l'uso in rete locale: python run.py --host 0.0.0.0 (vedi README)
    import sys
    host = "0.0.0.0" if "--host" in sys.argv else "127.0.0.1"
    app.run(host=host, port=5000, debug="--debug" in sys.argv)
