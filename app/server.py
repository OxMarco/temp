import os
import sqlite3
import sys
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI, LengthFinishReasonError
from functools import wraps
from waitress import serve
from analyser import process_image_recognition

load_dotenv()

# -------------------------------------------------------------------
# Database Functions
# -------------------------------------------------------------------
def init_db(db_path: str = 'credits.db'):
    """
    Initialize the database, creating the `user_credits` table if it does not exist.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(50) UNIQUE NOT NULL,
                credits INTEGER NOT NULL DEFAULT 10
            )
        ''')
        conn.commit()


def get_user_credits(user_id: str, db_path: str = 'credits.db') -> int:
    """
    Retrieve the number of credits for a given user ID from the database.
    Returns `None` if the user does not exist.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT credits FROM user_credits WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def set_user_credits(user_id: str, credit_amount: int, db_path: str = 'credits.db'):
    """
    Set the number of credits for a given user ID, upserting in case the user does not exist.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        # Using SQLite UPSERT syntax (requires SQLite 3.24.0+)
        cursor.execute('''
            INSERT INTO user_credits (user_id, credits)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET credits=excluded.credits
        ''', (user_id, credit_amount))
        conn.commit()


def require_credits(user_id: str, db_path: str = 'credits.db'):
    """
    Ensure that a user has enough credits to proceed. If no record exists, 
    the user is automatically given the default (10) credits. If the user 
    has fewer than 1 credit, a ValueError is raised.
    """
    # Ensure a user row exists; if not, defaults to 10 credits.
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO user_credits (user_id)
            VALUES (?)
        ''', (user_id,))
        conn.commit()

    current_credits = get_user_credits(user_id, db_path=db_path)
    if current_credits is None or current_credits < 1:
        raise ValueError("No more credits left")

    set_user_credits(user_id, current_credits - 1, db_path=db_path)


# -------------------------------------------------------------------
# Application Factory
# -------------------------------------------------------------------
def create_app() -> Flask:
    """
    Factory function that creates and returns a Flask app instance.
    """
    app = Flask(__name__)
    CORS(app)

    # Initialize OpenAI client
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    api_key = os.getenv('API_KEY')

    def require_api_key_and_user_id(f):
        """
        Decorator that verifies the request has a valid API key
        and a valid user ID in the headers.
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_key_param = request.headers.get('X-Api-Key')
            if not api_key_param or api_key_param != api_key:
                return jsonify({"error": "Invalid API key"}), 422

            user_id = request.headers.get('X-User-Id')
            if not user_id:
                return jsonify({"error": "Missing required user ID"}), 422

            # Pass user_id along to the route function
            return f(user_id, *args, **kwargs)
        return decorated_function

    @app.route('/', methods=['GET', 'POST'])
    def index():
        """
        Index route handler. Returns statistics data.
        """
        return jsonify({'message':datetime.now()})

    @app.route('/credits', methods=['GET'])
    @require_api_key_and_user_id
    def credits_left(user_id):
        """
        Returns the number of credits left for the user.
        """
        user_credits = get_user_credits(user_id)
        return jsonify({'credits': user_credits or 0})

    @app.route('/analyze/image', methods=['POST'])
    @require_api_key_and_user_id
    def analyze_image(user_id):
        """
        Endpoint that accepts a JSON payload containing:
        - lang: the language in which to generate a description
        - image: a base64-encoded image (JPEG)
        
        Validates input, checks user credits, 
        and calls OpenAI to analyze/describe the image.
        """
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 422

        lang = data.get('lang')
        image = data.get('image')
        if not lang or not image:
            return jsonify({'error': 'Missing required fields'}), 422

        # Check and decrement user credits
        try:
            require_credits(user_id)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 402
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        try:
            response_content = process_image_recognition(client, lang, image)
            if response_content.parsed:
                return jsonify({
                    'name': response_content.parsed.name,
                    'description': response_content.parsed.description,
                    'synonyms': response_content.parsed.synonyms
                })

            if response_content.refusal:
                return jsonify({'error': 'Image is not processable'}), 422

            return jsonify({'error': 'Image cannot be identified'}), 422

        except Exception as e:
            if isinstance(e, LengthFinishReasonError):
                return jsonify({'error': 'Image too big'}), 422
            return jsonify({'error': str(e)}), 500

    @app.errorhandler(404)
    def not_found(e):
        """
        404 handler for unknown routes.
        """
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def server_error(e):
        """
        500 handler for internal server errors.
        """
        return jsonify({'error': 'Internal server error'}), 500

    return app

# -------------------------------------------------------------------
# Main Entry Point
# -------------------------------------------------------------------
if __name__ == '__main__':
    init_db('credits.db')

    app = create_app()
    host = os.getenv('FLASK_HOST')
    port = os.getenv('FLASK_PORT')
    if not host or not port:
        sys.exit(-1)
    serve(app=app, host=host, port=port)
