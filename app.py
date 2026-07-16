"""
Play Store Review Scraper — backend
Run with: python app.py
Requires: flask, google-play-scraper
"""

import json
import os
import re
import statistics
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from google_play_scraper import reviews, Sort, app as gp_app

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="")


def safe_filename(app_id: str, scores: list, count: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    score_tag = "all" if not scores else "-".join(str(s) for s in sorted(scores))
    clean_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", app_id)
    return f"{clean_id}__stars-{score_tag}__n{count}__{stamp}.json"


def extract_app_id(raw: str) -> str:
    """Accepts either a bare package id or a full Play Store URL."""
    raw = raw.strip()
    m = re.search(r"[?&]id=([a-zA-Z0-9_.]+)", raw)
    if m:
        return m.group(1)
    return raw


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/app-info")
def app_info():
    """Look up basic app metadata (name, icon, developer, overall rating)."""
    raw = request.args.get("app_id", "")
    app_id = extract_app_id(raw)
    if not app_id:
        return jsonify({"error": "app_id is required"}), 400
    try:
        info = gp_app(app_id, lang=request.args.get("lang", "en"),
                      country=request.args.get("country", "us"))
        return jsonify({
            "appId": app_id,
            "title": info.get("title"),
            "icon": info.get("icon"),
            "developer": info.get("developer"),
            "score": info.get("score"),
            "ratings": info.get("ratings"),
            "reviewsCount": info.get("reviews"),
            "installs": info.get("installs"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/scrape", methods=["POST"])
def scrape():
    payload = request.get_json(force=True) or {}
    raw_app_id = payload.get("app_id", "")
    app_id = extract_app_id(raw_app_id)
    count = int(payload.get("count", 100))
    scores = payload.get("scores", [])  # list of ints 1-5, empty = all
    lang = payload.get("lang", "id")
    country = payload.get("country", "id")
    sort_map = {
        "newest": Sort.NEWEST,
        "rating": Sort.RATING,
        "relevance": Sort.MOST_RELEVANT,
    }
    sort_order = sort_map.get(payload.get("sort", "newest"), Sort.NEWEST)

    if not app_id:
        return jsonify({"error": "app_id is required"}), 400
    count = max(1, min(count, 5000))

    try:
        all_reviews = []
        if scores:
            # google-play-scraper only filters one score at a time,
            # so fetch per-star and merge to honor "which star(s)" selection.
            per_star = max(1, count // len(scores))
            for s in scores:
                result, _ = reviews(
                    app_id,
                    lang=lang,
                    country=country,
                    sort=sort_order,
                    count=per_star,
                    filter_score_with=s,
                )
                all_reviews.extend(result)
        else:
            result, _ = reviews(
                app_id,
                lang=lang,
                country=country,
                sort=sort_order,
                count=count,
            )
            all_reviews.extend(result)

        all_reviews = all_reviews[:count]

        # Normalize + make JSON-serializable (datetimes -> isoformat)
        cleaned = []
        for r in all_reviews:
            cleaned.append({
                "reviewId": r.get("reviewId"),
                "userName": r.get("userName"),
                "userImage": r.get("userImage"),
                "content": r.get("content"),
                "score": r.get("score"),
                "thumbsUpCount": r.get("thumbsUpCount"),
                "reviewCreatedVersion": r.get("reviewCreatedVersion"),
                "at": r.get("at").isoformat() if r.get("at") else None,
                "replyContent": r.get("replyContent"),
                "repliedAt": r.get("repliedAt").isoformat() if r.get("repliedAt") else None,
                "appVersion": r.get("appVersion"),
            })

        scores_present = [c["score"] for c in cleaned if c["score"] is not None]
        stats = {
            "total": len(cleaned),
            "average": round(statistics.mean(scores_present), 2) if scores_present else None,
            "distribution": {str(i): scores_present.count(i) for i in range(1, 6)},
        }

        filename = safe_filename(app_id, scores, len(cleaned))
        record = {
            "meta": {
                "appId": app_id,
                "requestedCount": count,
                "starsFilter": scores or "all",
                "lang": lang,
                "country": country,
                "sort": payload.get("sort", "newest"),
                "scrapedAt": datetime.now().isoformat(),
                "filename": filename,
            },
            "stats": stats,
            "reviews": cleaned,
        }
        with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        return jsonify(record)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/saved")
def list_saved():
    files = []
    for fn in sorted(os.listdir(DATA_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(DATA_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            files.append({
                "filename": fn,
                "meta": data.get("meta", {}),
                "stats": data.get("stats", {}),
            })
        except Exception:
            continue
    return jsonify(files)


@app.route("/api/saved/<path:filename>")
def get_saved(filename):
    filename = os.path.basename(filename)
    path = os.path.join(DATA_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    with open(path, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/saved/<path:filename>", methods=["DELETE"])
def delete_saved(filename):
    filename = os.path.basename(filename)
    path = os.path.join(DATA_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
