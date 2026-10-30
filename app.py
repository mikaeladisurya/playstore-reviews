"""
Play Store Review Scraper — backend
Run with: python app.py
Requires: flask, google-play-scraper
"""

import csv
import io
import json
import os
import re
import statistics
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory
from google_play_scraper import Sort, app as gp_app, reviews

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

MAX_COUNT = 5000
SORT_MAP = {
    "newest": Sort.NEWEST,
    "rating": Sort.RATING,
    "relevance": Sort.MOST_RELEVANT,
}
DEFAULT_LANG = "id"
DEFAULT_COUNTRY = "id"
CSV_COLUMNS = [
    "reviewId",
    "userName",
    "score",
    "thumbsUpCount",
    "at",
    "appVersion",
    "content",
    "replyContent",
    "repliedAt",
]

app = Flask(__name__, static_folder="static", static_url_path="")


def safe_filename(app_id: str, scores: list, count: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    score_tag = "all" if not scores else "-".join(str(s) for s in sorted(scores))
    clean_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", app_id)
    return f"{clean_id}__stars-{score_tag}__n{count}__{stamp}.json"


def extract_app_id(raw: str) -> str:
    """Accepts either a bare package id or a full Play Store URL."""
    raw = (raw or "").strip()
    m = re.search(r"[?&]id=([a-zA-Z0-9_.]+)", raw)
    if m:
        return m.group(1)
    return raw


def split_count(total: int, buckets: int) -> list:
    """Split total into buckets as evenly as possible, spreading the remainder first.

    1000 over 3 stars -> [334, 333, 333] (the old `total // buckets` gave 999).
    """
    if buckets <= 0:
        return []
    base, remainder = divmod(max(total, 0), buckets)
    return [base + (1 if i < remainder else 0) for i in range(buckets)]


def parse_scores(raw) -> list:
    """Validate the star filter: a list of ints 1-5 (empty/None means all stars)."""
    if raw in (None, "", []):
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("scores harus berupa daftar angka 1-5")
    parsed = set()
    for value in raw:
        try:
            star = int(value)
        except (TypeError, ValueError):
            raise ValueError("scores harus berupa daftar angka 1-5")
        if star < 1 or star > 5:
            raise ValueError("scores hanya boleh berisi angka 1 sampai 5")
        parsed.add(star)
    return sorted(parsed)


def normalize_review(r: dict) -> dict:
    """Keep only JSON-serializable fields we actually use."""
    return {
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
    }


def dedupe_reviews(items: list) -> list:
    """Drop reviews that show up twice (same review can appear under two star filters)."""
    seen = set()
    unique = []
    for r in items:
        key = r.get("reviewId")
        if not key:
            key = (r.get("userName"), r.get("at"), (r.get("content") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def build_stats(items: list) -> dict:
    scores = [r["score"] for r in items if r.get("score") is not None]
    return {
        "total": len(items),
        "average": round(statistics.mean(scores), 2) if scores else None,
        "distribution": {str(i): scores.count(i) for i in range(1, 6)},
    }


def load_record(filename: str):
    filename = os.path.basename(filename)
    path = os.path.join(DATA_DIR, filename)
    if not os.path.isfile(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        return filename, json.load(f)


def not_found_app_message(app_id: str) -> str:
    return f'App "{app_id}" tidak ditemukan di Play Store. Periksa package ID atau URL-nya.'


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/app-info")
def app_info():
    """Look up basic app metadata (name, icon, developer, overall rating)."""
    raw = request.args.get("app_id", "")
    app_id = extract_app_id(raw)
    if not app_id:
        return jsonify({"error": "app_id wajib diisi"}), 400
    lang = request.args.get("lang") or DEFAULT_LANG
    country = request.args.get("country") or DEFAULT_COUNTRY
    try:
        info = gp_app(app_id, lang=lang, country=country)
    except Exception as e:
        message = str(e)
        if "not found" in message.lower() or "404" in message:
            return jsonify({"error": not_found_app_message(app_id)}), 404
        return jsonify({"error": message}), 400
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


@app.route("/api/scrape", methods=["POST"])
def scrape():
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Body harus berupa objek JSON"}), 400

    app_id = extract_app_id(payload.get("app_id", ""))
    if not app_id:
        return jsonify({"error": "app_id wajib diisi"}), 400

    try:
        count = int(payload.get("count", 100))
    except (TypeError, ValueError):
        return jsonify({"error": "count harus berupa angka"}), 400
    count = max(1, min(count, MAX_COUNT))

    try:
        scores = parse_scores(payload.get("scores"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    lang = str(payload.get("lang") or DEFAULT_LANG)
    country = str(payload.get("country") or DEFAULT_COUNTRY)
    sort_key = payload.get("sort") or "newest"
    if sort_key not in SORT_MAP:
        return jsonify({"error": f'sort harus salah satu dari: {", ".join(SORT_MAP)}'}), 400
    sort_order = SORT_MAP[sort_key]

    warnings = []
    fetched = []
    per_star = {}

    try:
        if scores:
            # google-play-scraper only filters one score at a time,
            # so fetch per-star and merge to honor "which star(s)" selection.
            for star, wanted in zip(scores, split_count(count, len(scores))):
                if wanted <= 0:
                    continue
                result, _ = reviews(
                    app_id,
                    lang=lang,
                    country=country,
                    sort=sort_order,
                    count=wanted,
                    filter_score_with=star,
                )
                per_star[str(star)] = len(result)
                fetched.extend(result)
                if len(result) < wanted:
                    warnings.append(f"Bintang {star} hanya tersedia {len(result)} review (diminta {wanted}).")
        else:
            result, _ = reviews(
                app_id,
                lang=lang,
                country=country,
                sort=sort_order,
                count=count,
            )
            fetched.extend(result)
            if len(result) < count:
                warnings.append(f"Play Store hanya mengembalikan {len(result)} review (diminta {count}).")
    except Exception as e:
        message = str(e)
        if "not found" in message.lower() or "404" in message:
            return jsonify({"error": not_found_app_message(app_id)}), 404
        return jsonify({"error": message}), 500

    unique = dedupe_reviews(fetched)
    duplicates = len(fetched) - len(unique)
    if duplicates:
        warnings.append(f"{duplicates} review duplikat dihapus saat menggabungkan bintang.")

    cleaned = [normalize_review(r) for r in unique[:count]]
    stats = build_stats(cleaned)

    if not cleaned:
        # An unknown package id silently yields zero reviews, so verify the app
        # actually exists before telling the user there is simply no data.
        try:
            gp_app(app_id, lang=lang, country=country)
        except Exception as e:
            message = str(e)
            if "not found" in message.lower() or "404" in message:
                return jsonify({"error": not_found_app_message(app_id)}), 404

    filename = None
    if cleaned:
        filename = safe_filename(app_id, scores, len(cleaned))
    else:
        warnings.append("Tidak ada review yang dikembalikan. Coba longgarkan filter bintang atau tambah jumlah.")

    record = {
        "meta": {
            "appId": app_id,
            "requestedCount": count,
            "starsFilter": scores or "all",
            "perStar": per_star or None,
            "lang": lang,
            "country": country,
            "sort": sort_key,
            "scrapedAt": datetime.now().isoformat(timespec="seconds"),
            "filename": filename,
        },
        "stats": stats,
        "warnings": warnings,
        "saved": bool(filename),
        "reviews": cleaned,
    }

    if filename:
        with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    return jsonify(record)


@app.route("/api/saved")
def list_saved():
    files = []
    for fn in os.listdir(DATA_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            _, data = load_record(fn)
        except Exception:
            continue
        if data is None:
            continue
        files.append({
            "filename": fn,
            "meta": data.get("meta", {}),
            "stats": data.get("stats", {}),
        })
    files.sort(key=lambda f: f["meta"].get("scrapedAt") or "", reverse=True)
    return jsonify(files)


@app.route("/api/saved/<path:filename>")
def get_saved(filename):
    filename, data = load_record(filename)
    if data is None:
        return jsonify({"error": "File tidak ditemukan"}), 404
    return jsonify(data)


@app.route("/api/saved/<path:filename>/export")
def export_saved(filename):
    """Download one saved scrape as CSV (Excel-friendly) or JSON."""
    filename, data = load_record(filename)
    if data is None:
        return jsonify({"error": "File tidak ditemukan"}), 404

    fmt = (request.args.get("format") or "csv").lower()
    stem = os.path.splitext(filename)[0]

    if fmt == "json":
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        )
    if fmt != "csv":
        return jsonify({"error": "format harus csv atau json"}), 400

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for r in data.get("reviews", []):
        writer.writerow(["" if r.get(col) is None else r.get(col) for col in CSV_COLUMNS])

    # BOM so Excel on Windows reads the Indonesian text as UTF-8.
    body = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


@app.route("/api/saved/<path:filename>", methods=["DELETE"])
def delete_saved(filename):
    filename, data = load_record(filename)
    if data is None:
        return jsonify({"error": "File tidak ditemukan"}), 404
    os.remove(os.path.join(DATA_DIR, filename))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        port=int(os.environ.get("PORT", "5000")),
    )
