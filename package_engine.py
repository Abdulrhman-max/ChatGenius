"""
Treatment Package Builder Engine for ChatGenius.
Handles creation, management, redemption, and analytics for treatment packages.
"""
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("package_engine")


def create_package(admin_id, name, description, treatments, package_price, validity_days=90):
    """
    Create a new treatment package.
    treatments is a list of dicts: [{"name": "Cleaning", "individual_price": 200}, ...]
    Returns the new package dict.
    """
    import database as db

    individual_total = sum(t.get("individual_price", 0) for t in treatments)
    savings = round(individual_total - package_price, 2)
    treatments_json = json.dumps(treatments)

    pkg_id = db.create_package_db(
        admin_id=admin_id,
        name=name,
        description=description,
        treatments_json=treatments_json,
        package_price=package_price,
        individual_total=individual_total,
        savings=savings,
        validity_days=validity_days,
    )

    logger.info(f"Package #{pkg_id} '{name}' created for admin #{admin_id}, savings={savings}")
    return {
        "id": pkg_id,
        "name": name,
        "description": description,
        "treatments": treatments,
        "package_price": package_price,
        "individual_total": individual_total,
        "savings": savings,
        "validity_days": validity_days,
    }


def get_packages(admin_id, active_only=True):
    """
    Returns all packages for an admin.
    Each package includes parsed treatments list.
    """
    import database as db

    packages = db.get_packages_db(admin_id, active_only=active_only)
    for p in packages:
        try:
            p["treatments"] = json.loads(p.get("treatments_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            p["treatments"] = []
    return packages


def update_package(package_id, admin_id, **kwargs):
    """
    Update a treatment package.
    Supported kwargs: name, description, treatments, package_price, validity_days, max_redemptions.
    """
    import database as db

    pkg = db.get_package_by_id(package_id)
    if not pkg:
        return {"error": "Package not found."}
    if pkg.get("admin_id") != admin_id:
        return {"error": "Unauthorized."}

    update_fields = {}
    if "name" in kwargs:
        update_fields["name"] = kwargs["name"]
    if "description" in kwargs:
        update_fields["description"] = kwargs["description"]
    if "validity_days" in kwargs:
        update_fields["validity_days"] = kwargs["validity_days"]
    if "max_redemptions" in kwargs:
        update_fields["max_redemptions"] = kwargs["max_redemptions"]

    if "treatments" in kwargs:
        treatments = kwargs["treatments"]
        update_fields["treatments_json"] = json.dumps(treatments)
        individual_total = sum(t.get("individual_price", 0) for t in treatments)
        update_fields["individual_total"] = individual_total
        price = kwargs.get("package_price", pkg.get("package_price", 0))
        update_fields["savings"] = round(individual_total - price, 2)

    if "package_price" in kwargs:
        update_fields["package_price"] = kwargs["package_price"]
        # Recalculate savings
        individual_total = update_fields.get("individual_total", pkg.get("individual_total", 0))
        update_fields["savings"] = round(individual_total - kwargs["package_price"], 2)

    if update_fields:
        db.update_package_db(package_id, **update_fields)

    logger.info(f"Package #{package_id} updated: {list(update_fields.keys())}")
    return {"success": True, "package_id": package_id}


def deactivate_package(package_id, admin_id):
    """
    Set a package as inactive.
    """
    import database as db

    pkg = db.get_package_by_id(package_id)
    if not pkg:
        return {"error": "Package not found."}
    if pkg.get("admin_id") != admin_id:
        return {"error": "Unauthorized."}

    db.update_package_db(package_id, is_active=0)
    logger.info(f"Package #{package_id} deactivated by admin #{admin_id}")
    return {"success": True}


def get_package_for_chatbot(admin_id, treatment_name):
    """
    Find a relevant active package that includes the given treatment.
    Returns the best matching package dict or None.
    """
    import database as db

    packages = db.get_packages_db(admin_id, active_only=True)
    best_match = None
    best_savings = 0

    for p in packages:
        try:
            treatments = json.loads(p.get("treatments_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            treatments = []

        for t in treatments:
            if t.get("name", "").lower() == treatment_name.lower():
                savings = p.get("savings", 0) or 0
                if savings > best_savings:
                    best_savings = savings
                    p["treatments"] = treatments
                    best_match = p
                break

    return best_match


def redeem_package_treatment(package_id, patient_id, booking_id, treatment_name):
    """
    Record a treatment redemption against a package.
    Returns redemption dict or error.
    """
    import database as db

    pkg = db.get_package_by_id(package_id)
    if not pkg:
        return {"error": "Package not found."}

    if not pkg.get("is_active"):
        return {"error": "Package is no longer active."}

    # Check package expiry based on validity_days
    validity_days = pkg.get("validity_days", 0)
    if validity_days and pkg.get("created_at"):
        try:
            created_at = datetime.strptime(pkg["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            expiry_date = created_at + timedelta(days=validity_days)
            if datetime.now() > expiry_date:
                return {"error": "Package has expired."}
        except (ValueError, TypeError):
            pass

    if pkg.get("max_redemptions") and pkg.get("max_redemptions") > 0:
        if pkg.get("current_redemptions", 0) >= pkg["max_redemptions"]:
            return {"error": "Package has reached maximum redemptions."}

    # Verify treatment is in the package
    try:
        treatments = json.loads(pkg.get("treatments_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        treatments = []

    treatment_found = any(
        t.get("name", "").lower() == treatment_name.lower() for t in treatments
    )
    if not treatment_found:
        return {"error": f"Treatment '{treatment_name}' is not part of this package."}

    redemption_id = db.redeem_package_db(package_id, patient_id, booking_id, treatment_name)
    logger.info(f"Package #{package_id} redeemed: {treatment_name} for patient #{patient_id}")

    return {
        "success": True,
        "redemption_id": redemption_id,
        "package_id": package_id,
        "treatment_name": treatment_name,
    }


def get_package_analytics(admin_id):
    """
    Returns analytics for all packages: views, purchases, revenue.
    """
    import database as db
    return db.get_package_analytics_db(admin_id)
