from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import re
import os

app = Flask(__name__)
CORS(app)  # Enable CORS to allow React frontend to access the API

# Get the current script directory
# script_dir = os.path.dirname(__file__)

# Set the path to the database file, which is one directory up
# DATABASE = os.path.join(script_dir, '..', 'dictionary.db')
DATABASE = 'dictionary.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    if len(query) <= 2:
        cursor.execute("SELECT DISTINCT wrd FROM dictionary WHERE wrd LIKE ?", ('%' + query + '%',))
        words = cursor.fetchall()
    else:
        cursor.execute("SELECT DISTINCT wrd, def FROM dictionary WHERE wrd LIKE ? OR def LIKE ?", 
                       ('%' + query + '%', '%' + query + '%'))
        rows = cursor.fetchall()
        words = [
            (wrd,) 
            for wrd, definition in rows
            if query in wrd.lower() or word_in_definition(query, definition)
        ]
    
    conn.close()
    return jsonify([word[0] for word in words])

@app.route('/')
def hello():
    return "hello"

@app.route('/words/<letter>', methods=['GET'])
def words_by_letter(letter):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT wrd FROM dictionary WHERE wrd LIKE ?", (letter + '%',))
    words = cursor.fetchall()
    conn.close()
    return jsonify([word[0] for word in words])

@app.route('/definition/<word>', methods=['GET'])
def definition(word):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT def FROM dictionary WHERE wrd=?", (word,))
    results = cursor.fetchall()
    conn.close()
    return jsonify([result[0] for result in results])

def word_in_definition(query, definition):
    cleaned_definition = re.sub(r'[^\w\s]', '', definition).lower()
    return f' {query} ' in f' {cleaned_definition} '

if __name__ == '__main__':
    app.run(debug=True)
