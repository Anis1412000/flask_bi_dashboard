#!/usr/bin/env python3
"""
Simple run script for the Odoo Dashboard project.
This script will attempt to create database tables and then run the Flask app.
"""

from app import app, db
import sys

def setup_database():
    """Create database tables if they don't exist."""
    try:
        with app.app_context():
            # This will create tables if they don't exist
            db.create_all()
            print("✅ Database tables created successfully!")
            return True
    except Exception as e:
        print(f"⚠️ Database setup issue: {e}")
        print("Note: Make sure PostgreSQL is running and database 'new_db4' exists")
        return False

def run_app():
    """Run the Flask application."""
    print("🚀 Starting Odoo Dashboard...")
    print("📊 Dashboard will be available at: http://127.0.0.1:5000")
    print("📄 Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0', port=5000)

if __name__ == '__main__':
    print("=== Odoo Dashboard Setup ===")
    
    # Try to setup database (optional - app will still run without it)
    setup_database()
    
    # Run the application
    try:
        run_app()
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error running application: {e}")
        sys.exit(1)