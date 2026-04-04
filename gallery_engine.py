"""
Before & After Gallery Engine for ChatGenius.
Manages clinic treatment photos shown in chatbot as swipeable carousels.
"""
import os
import logging
import uuid
from datetime import datetime
from PIL import Image
from io import BytesIO

logger = logging.getLogger("gallery")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads", "gallery")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PHOTOS_PER_TREATMENT = 20
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
COMPRESS_MAX_DIMENSION = 1200  # Max width/height after compression
COMPRESS_QUALITY = 85


def init():
    """Ensure upload directory exists."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def upload_image(admin_id, treatment_type, image_file, image_type="before", caption=""):
    """
    Upload a gallery image.
    image_file: FileStorage object from Flask request.files
    image_type: 'before' or 'after'
    Returns: {"id": 5, "image_url": "/uploads/gallery/xxx.jpg"} or {"error": "..."}
    """
    import database as db
    init()

    # Validate extension
    filename = image_file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"error": f"Only JPG and PNG files are accepted. Got: {ext}"}

    # Check count limit
    conn = db.get_db()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM gallery WHERE admin_id=? AND treatment_type=?",
        (admin_id, treatment_type)
    ).fetchone()["c"]

    if count >= MAX_PHOTOS_PER_TREATMENT:
        conn.close()
        return {"error": f"Maximum {MAX_PHOTOS_PER_TREATMENT} photos per treatment type."}

    # Read and compress image
    image_data = image_file.read()
    if len(image_data) > MAX_FILE_SIZE:
        # Compress
        image_data = _compress_image(image_data, ext)
    elif len(image_data) > MAX_FILE_SIZE:
        conn.close()
        return {"error": "File is too large even after compression."}

    # Auto-compress all images for consistency
    try:
        image_data = _compress_image(image_data, ext)
    except Exception as e:
        logger.warning(f"Compression failed, using original: {e}")

    # Generate unique filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)

    with open(filepath, "wb") as f:
        f.write(image_data)

    # Get next sort order
    max_order = conn.execute(
        "SELECT MAX(sort_order) as m FROM gallery WHERE admin_id=? AND treatment_type=?",
        (admin_id, treatment_type)
    ).fetchone()["m"]
    sort_order = (max_order or 0) + 1

    # Generate pair_id for before/after matching
    pair_id = uuid.uuid4().hex[:8]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    image_url = f"/uploads/gallery/{unique_name}"

    conn.execute(
        """INSERT INTO gallery
           (admin_id, treatment_type, image_url, image_type, pair_id, caption, sort_order, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (admin_id, treatment_type, image_url, image_type, pair_id, caption, sort_order, now)
    )
    conn.commit()
    image_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    logger.info(f"Gallery image uploaded: {treatment_type}/{image_type} for admin #{admin_id}")
    return {"id": image_id, "image_url": image_url}


def _compress_image(image_data, ext):
    """Compress image to max dimensions and quality."""
    try:
        img = Image.open(BytesIO(image_data))

        # Resize if too large
        if img.width > COMPRESS_MAX_DIMENSION or img.height > COMPRESS_MAX_DIMENSION:
            img.thumbnail((COMPRESS_MAX_DIMENSION, COMPRESS_MAX_DIMENSION), Image.LANCZOS)

        # Save compressed
        output = BytesIO()
        if ext in ('.jpg', '.jpeg'):
            img = img.convert('RGB')
            img.save(output, format='JPEG', quality=COMPRESS_QUALITY, optimize=True)
        else:
            img.save(output, format='PNG', optimize=True)

        return output.getvalue()
    except Exception as e:
        logger.error(f"Image compression failed: {e}")
        return image_data


def delete_image(image_id, admin_id):
    """Delete a gallery image (file + DB record)."""
    import database as db
    conn = db.get_db()

    image = conn.execute(
        "SELECT * FROM gallery WHERE id=? AND admin_id=?", (image_id, admin_id)
    ).fetchone()

    if not image:
        conn.close()
        return {"error": "Image not found"}

    image = dict(image)

    # Delete file
    filename = os.path.basename(image["image_url"])
    filepath = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    # Delete DB record
    conn.execute("DELETE FROM gallery WHERE id=?", (image_id,))
    conn.commit()
    conn.close()

    logger.info(f"Gallery image #{image_id} deleted")
    return {"success": True}


def get_gallery(admin_id, treatment_type=None):
    """Get all gallery images for admin, optionally filtered by treatment."""
    import database as db
    conn = db.get_db()

    if treatment_type:
        images = conn.execute(
            "SELECT * FROM gallery WHERE admin_id=? AND treatment_type=? ORDER BY sort_order",
            (admin_id, treatment_type)
        ).fetchall()
    else:
        images = conn.execute(
            "SELECT * FROM gallery WHERE admin_id=? ORDER BY treatment_type, sort_order",
            (admin_id,)
        ).fetchall()

    conn.close()
    return [dict(img) for img in images]


def get_public_gallery(admin_id, treatment_type):
    """Get gallery images for chatbot display (public, no auth required)."""
    import database as db
    conn = db.get_db()

    images = conn.execute(
        "SELECT id, image_url, image_type, caption, sort_order FROM gallery WHERE admin_id=? AND treatment_type=? ORDER BY sort_order",
        (admin_id, treatment_type)
    ).fetchall()
    conn.close()

    return [dict(img) for img in images]


def get_treatment_types(admin_id):
    """Get list of treatment types that have gallery images."""
    import database as db
    conn = db.get_db()
    types = conn.execute(
        "SELECT DISTINCT treatment_type, COUNT(*) as count FROM gallery WHERE admin_id=? GROUP BY treatment_type",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [{"treatment_type": t["treatment_type"], "count": t["count"]} for t in types]


def get_chatbot_gallery(admin_id, message):
    """
    Check if a chatbot message is asking about a treatment that has gallery images.
    Returns gallery data for carousel display, or None.
    """
    import database as db

    lower = message.lower()
    treatment_keywords = {
        'whitening': ['whitening', 'whiten', 'bleaching', 'تبييض'],
        'braces': ['braces', 'orthodontic', 'تقويم'],
        'implant': ['implant', 'زراعة'],
        'veneer': ['veneer', 'veneers', 'قشور'],
        'crown': ['crown', 'تاج'],
        'cleaning': ['cleaning', 'تنظيف'],
        'filling': ['filling', 'حشوة'],
        'root canal': ['root canal', 'علاج عصب'],
    }

    matched_treatment = None
    for treatment, keywords in treatment_keywords.items():
        for kw in keywords:
            if kw in lower:
                matched_treatment = treatment
                break
        if matched_treatment:
            break

    if not matched_treatment:
        return None

    # Check if we have images for this treatment
    conn = db.get_db()
    images = conn.execute(
        "SELECT id, image_url, image_type, caption FROM gallery WHERE admin_id=? AND LOWER(treatment_type) LIKE ? ORDER BY sort_order",
        (admin_id, f"%{matched_treatment}%")
    ).fetchall()
    conn.close()

    if not images:
        return None

    return {
        "treatment_type": matched_treatment,
        "images": [dict(img) for img in images],
        "total": len(images)
    }
