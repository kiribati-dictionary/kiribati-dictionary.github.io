import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/api/your_function', methods=['POST'])
def custom_function_endpoint():
  logging.info('Received request at /api/function')
  # Your code here

if __name__ == '__main__':
    app.run()