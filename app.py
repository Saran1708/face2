from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mysqldb import MySQL
import MySQLdb.cursors
import bcrypt
import base64
import json
import re
from datetime import datetime
import numpy as np

app = Flask(__name__)
app.secret_key = 'your-super-secret-key-change-this-in-production'

# MySQL Configuration
app.config['MYSQL_HOST'] = 'sql12.freesqldatabase.com'
app.config['MYSQL_USER'] = 'sql12799550'
app.config['MYSQL_PASSWORD'] = 'lfPKvcJp3l'  # Change this
app.config['MYSQL_DB'] = 'sql12799550'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT id, name, email, created_at FROM users WHERE id = %s', (session['user_id'],))
        user = cursor.fetchone()
        cursor.close()
        
        if user:
            return render_template('dashboard.html', user=user)
        else:
            session.clear()
            return redirect(url_for('login_page'))
            
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        return redirect(url_for('login_page'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        face_image = data.get('faceImage', '')
        face_embeddings = data.get('faceEmbeddings', [])
        
        # Validation
        if not all([name, email, password, face_image, face_embeddings]):
            return jsonify({
                'success': False, 
                'message': 'All fields including face capture are required'
            }), 400
        
        # Email validation
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({
                'success': False, 
                'message': 'Invalid email format'
            }), 400
        
        # Password validation
        if len(password) < 6:
            return jsonify({
                'success': False, 
                'message': 'Password must be at least 6 characters long'
            }), 400
        
        # Check if user already exists
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            cursor.close()
            return jsonify({
                'success': False, 
                'message': 'Email already registered'
            }), 409
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Process face image (remove data URL prefix)
        if face_image.startswith('data:image'):
            face_image_data = face_image.split(',')[1]
        else:
            face_image_data = face_image
        
        # Convert face embeddings to JSON string
        face_embeddings_json = json.dumps(face_embeddings)
        
        # Insert user into database
        insert_query = '''INSERT INTO users (name, email, password, face_image, face_embeddings, created_at) 
                         VALUES (%s, %s, %s, %s, %s, %s)'''
        cursor.execute(insert_query, (name, email, hashed_password, face_image_data, 
                                    face_embeddings_json, datetime.now()))
        
        mysql.connection.commit()
        user_id = cursor.lastrowid
        cursor.close()
        
        return jsonify({
            'success': True, 
            'message': 'Registration successful!',
            'user_id': user_id
        }), 201
        
    except Exception as e:
        print(f"Registration error: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Registration failed. Please try again.'
        }), 500

@app.route('/login_face', methods=['POST'])
def login_face():
    try:
        data = request.get_json()
        face_embeddings = data.get('faceEmbeddings', [])
        email = data.get('email', '').strip() if data.get('email') else None
        
        if not face_embeddings:
            return jsonify({
                'success': False, 
                'message': 'Face capture is required for login'
            }), 400
        
        # Get client IP for logging
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        
        # Get all users or specific user if email provided
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        if email:
            # Email provided - check specific user
            cursor.execute('SELECT id, name, email, face_embeddings FROM users WHERE email = %s AND is_active = TRUE', (email,))
            users = [cursor.fetchone()] if cursor.fetchone() else []
            cursor.execute('SELECT id, name, email, face_embeddings FROM users WHERE email = %s AND is_active = TRUE', (email,))
            users = [cursor.fetchone()] if cursor.fetchone() else []
        else:
            # No email - check against all users
            cursor.execute('SELECT id, name, email, face_embeddings FROM users WHERE is_active = TRUE')
            users = cursor.fetchall()
        
        if not users or (email and not users[0]):
            # Log failed attempt
            cursor.execute('''INSERT INTO login_attempts (email, ip_address, success, attempt_time, face_similarity_score) 
                             VALUES (%s, %s, %s, %s, %s)''', 
                          (email or 'unknown', client_ip, False, datetime.now(), 0))
            mysql.connection.commit()
            cursor.close()
            
            return jsonify({
                'success': False, 
                'message': 'User not found or inactive'
            }), 404
        
        best_match = None
        best_similarity = 0
        similarity_threshold = 0.6  # Adjust this threshold as needed
        
        # Compare face embeddings with all users
        for user in users:
            if not user or not user.get('face_embeddings'):
                continue
                
            try:
                stored_embeddings = json.loads(user['face_embeddings'])
                similarity = calculate_face_similarity(face_embeddings, stored_embeddings)
                
                print(f"Similarity with user {user['email']}: {similarity}")
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = user
                    
            except json.JSONDecodeError:
                print(f"Error parsing face embeddings for user {user['id']}")
                continue
        
        # Check if best match meets threshold
        if best_match and best_similarity >= similarity_threshold:
            # Successful login
            session['user_id'] = best_match['id']
            session['user_name'] = best_match['name']
            session['user_email'] = best_match['email']
            session['login_time'] = datetime.now().isoformat()
            
            # Log successful attempt
            cursor.execute('''INSERT INTO login_attempts (user_id, email, ip_address, success, attempt_time, face_similarity_score) 
                             VALUES (%s, %s, %s, %s, %s, %s)''', 
                          (best_match['id'], best_match['email'], client_ip, True, datetime.now(), best_similarity))
            mysql.connection.commit()
            cursor.close()
            
            return jsonify({
                'success': True, 
                'message': f'Welcome back, {best_match["name"]}!',
                'user': {
                    'id': best_match['id'],
                    'name': best_match['name'],
                    'email': best_match['email']
                },
                'similarity_score': round(best_similarity, 4),
                'redirect_url': '/dashboard'
            }), 200
            
        else:
            # Failed login - face not recognized
            # Log failed attempt
            cursor.execute('''INSERT INTO login_attempts (email, ip_address, success, attempt_time, face_similarity_score) 
                             VALUES (%s, %s, %s, %s, %s)''', 
                          (email or 'unknown', client_ip, False, datetime.now(), best_similarity))
            mysql.connection.commit()
            cursor.close()
            
            return jsonify({
                'success': False, 
                'message': 'Face not recognized. Please try again or register first.',
                'similarity_score': round(best_similarity, 4)
            }), 401
            
    except Exception as e:
        print(f"Login error: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Login failed. Please try again.'
        }), 500

@app.route('/users')
def users_list():
    """View all registered users"""
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT id, name, email, created_at FROM users ORDER BY created_at DESC')
        users = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'success': True,
            'users': users
        })
        
    except Exception as e:
        print(f"Users list error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error loading users'
        }), 500

def calculate_face_similarity(embeddings1, embeddings2):
    """Calculate similarity between two face embeddings"""
    try:
        emb1 = np.array(embeddings1)
        emb2 = np.array(embeddings2)
        
        # Calculate euclidean distance
        distance = np.linalg.norm(emb1 - emb2)
        
        # Convert distance to similarity score (0-1 range)
        # Lower distance = higher similarity
        similarity = 1 / (1 + distance)
        
        return similarity
    except Exception as e:
        print(f"Error calculating similarity: {e}")
        return 0

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)