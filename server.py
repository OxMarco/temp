import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI, LengthFinishReasonError
from typing import List
from pydantic import BaseModel

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
# Pydantic Model for Handling Response Parsing
# -------------------------------------------------------------------
class PictureDescription(BaseModel):
    """
    Defines the structure of the expected response content when describing an image:
    - name: The object's name.
    - description: A short description of the object.
    - fun_facts: A list of funny facts about the object.
    """
    name: str
    description: str
    fun_facts: List[str]


# -------------------------------------------------------------------
# Application Factory
# -------------------------------------------------------------------
def create_app() -> Flask:
    """
    Factory function that creates and returns a Flask app instance.
    """
    app = Flask(__name__)
    CORS(app)  # Enable CORS

    # Initialize OpenAI client
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    @app.route('/credits', methods=['GET'])
    def credits_left():
        """
        Returns the number of credits left for the user.
        """
        user_id = request.headers.get('X-User-Id')
        if not user_id:
            return jsonify({"error": "Missing required user ID"}), 422

        user_credits = get_user_credits(user_id)
        return jsonify({'credits': user_credits or 0})


    @app.route('/analyze/image', methods=['POST'])
    def analyze_image():
        """
        Endpoint that accepts a JSON payload containing:
        - lang: the language in which to generate a description
        - image: a base64-encoded image (JPEG)
        
        The route validates the input, checks user credits, 
        and calls OpenAI to analyze/describe the image.
        """
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 422

        lang = data.get('lang')
        image = data.get('image')

        if not lang or not image:
            return jsonify({'error': 'Missing required fields'}), 422

        user_id = request.headers.get('X-User-Id')
        if not user_id:
            return jsonify({"error": "Missing required user ID"}), 422

        # Check and decrement user credits
        try:
            require_credits(user_id)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 402
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        # Call OpenAI API
        try:
            completion = client.beta.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Describe the object in the image, tell me its name, "
                                    f"describe it and give three funny facts about it. "
                                    f"Use a simple language, use {lang} only"
                                )
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image}"
                                }
                            }
                        ]
                    }
                ],
                response_format=PictureDescription,
                max_tokens=500
            )

            response_content = completion.choices[0].message
            if response_content.parsed:
                return jsonify({
                    'name': response_content.parsed.name,
                    'description': response_content.parsed.description,
                    'funFacts': response_content.parsed.fun_facts
                })

            if response_content.refusal:
                return jsonify({'error': 'Image is not processable'}), 422

            return jsonify({'error': 'Image cannot be identified'}), 422

        except Exception as e:
            # Example: Large image => LengthFinishReasonError
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
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=3000)
