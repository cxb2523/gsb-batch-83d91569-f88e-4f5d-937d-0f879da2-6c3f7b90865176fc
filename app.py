from flask import Flask, render_template, request, jsonify, send_file # type: ignore
import subprocess
import os
import json
import re
import time
import threading
from datetime import datetime
import csv

app = Flask(__name__)

def safe_filename(text):
    """Same naming rule as maps_scraper.safe_filename"""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)[:100]

def output_paths(keyword, city):
    """Per-run output file paths for a keyword/city pair"""
    base = f"{safe_filename(keyword)}_{safe_filename(city)}"
    return {
        "csv": os.path.join("output", f"{base}_businesses.csv"),
        "json": os.path.join("output", f"{base}_businesses.json"),
        "skipped": os.path.join("output", f"{base}_skipped.json"),
    }

# Files produced by the most recent run (used by the download endpoints)
current_output = {"csv": None, "json": None}

# Status tracking
scraper_status = {
    "running": False,
    "progress": 0,
    "current_business": "",
    "total_businesses": 0,
    "message": "Ready",
    "results": None,
    "skipped": [],
    "skipped_count": 0,
    "error": None
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(scraper_status)

@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    global scraper_status
    
    if scraper_status["running"]:
        return jsonify({"error": "Scraper is already running"}), 400
    
    data = request.json
    keyword = data.get('keyword', '').strip()
    city = data.get('city', '').strip()
    max_results = data.get('max_results')
    no_emails = data.get('no_emails', False)
    headless = data.get('headless', True)
    timeout = data.get('timeout', 300)  # Default 5 minutes
    
    if not keyword or not city:
        return jsonify({"error": "Keyword and city are required"}), 400
    
    # Reset status
    scraper_status = {
        "running": True,
        "progress": 0,
        "current_business": "",
        "total_businesses": 0,
        "message": "Starting scraper...",
        "results": None,
        "skipped": [],
        "skipped_count": 0,
        "error": None
    }
    
    # Start scraper in background thread
    thread = threading.Thread(
        target=run_scraper,
        args=(keyword, city, max_results, no_emails, headless, timeout)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started"})

def run_scraper(keyword, city, max_results, no_emails, headless, timeout):
    global scraper_status, current_output

    try:
        # Build command
        cmd = [
            "python",
            "maps_scraper.py",
            "--keyword", keyword,
            "--city", city,
            "--verbose"
        ]
        
        # headless should be True by default (headless=False when headless is passed as False)
        if not headless:
            # Only add --headless if we want headless mode
            pass
        else:
            cmd.append("--headless")
        
        cmd.extend(["--timeout", str(timeout)])
        
        if max_results:
            cmd.extend(["--max-results", str(max_results)])
        
        if no_emails:
            cmd.append("--no-emails")
        
        scraper_status["message"] = "🚀 Launching browser..."
        scraper_status["progress"] = 5
        
        # Run scraper with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=timeout + 30  # Add 30s buffer
        )
        
        scraper_status["progress"] = 75
        scraper_status["message"] = "📊 Processing results..."
        
        if result.returncode != 0:
            scraper_status["error"] = result.stderr or "Scraper failed"
            scraper_status["running"] = False
            return
        
        # Load results from the per-keyword/city files written by maps_scraper
        paths = output_paths(keyword, city)
        current_output = {"csv": None, "json": None}

        results = []
        if os.path.exists(paths["csv"]):
            with open(paths["csv"], 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                results = list(reader)
            current_output["csv"] = paths["csv"]
            if os.path.exists(paths["json"]):
                current_output["json"] = paths["json"]

        # Load skip records written by the scraper
        skipped = []
        if os.path.exists(paths["skipped"]):
            try:
                with open(paths["skipped"], 'r', encoding='utf-8') as f:
                    skipped_payload = json.load(f)
                skipped = skipped_payload.get("skipped", [])
            except Exception:
                skipped = []

        scraper_status["progress"] = 100
        scraper_status["message"] = f"✅ Complete! 成功 {len(results)} 条、跳过 {len(skipped)} 条"
        scraper_status["results"] = results
        scraper_status["total_businesses"] = len(results)
        scraper_status["skipped"] = skipped
        scraper_status["skipped_count"] = len(skipped)
        scraper_status["running"] = False
        
    except Exception as e:
        scraper_status["error"] = str(e)
        scraper_status["running"] = False

@app.route('/api/results/csv')
def download_csv():
    csv_file = current_output.get("csv")
    if not csv_file or not os.path.exists(csv_file):
        return jsonify({"error": "No results available"}), 404

    return send_file(
        csv_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"businesses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

@app.route('/api/results/json')
def download_json():
    json_file = current_output.get("json")
    if not json_file or not os.path.exists(json_file):
        return jsonify({"error": "No results available"}), 404
    
    return send_file(
        json_file,
        mimetype='application/json',
        as_attachment=True,
        download_name=f"businesses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

if __name__ == '__main__':
    os.makedirs("output", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("checkpoints", exist_ok=True)
    print("🚀 Starting UI Server...")
    print("📱 Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
