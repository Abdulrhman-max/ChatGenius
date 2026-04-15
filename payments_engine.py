"""
Payments Engine - Simulated payment processing
Creates payment requests and simulates payment flow without real payment gateway.
"""
import secrets
import os
from datetime import datetime

BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")


def create_payment_request(admin_id, patient_id, amount, description, currency="USD", 
                           payment_method="card", reference_id=None, patient_email=None):
    """
    Create a new payment request.
    Returns payment dict with checkout URL.
    """
    import database as db
    
    token = secrets.token_urlsafe(32)
    payment_id = db.create_payment_request(
        admin_id, patient_id, amount, description, currency, payment_method, token, reference_id, patient_email
    )
    
    checkout_url = f"{BASE_URL}/payment.html?token={token}"
    
    return {
        "payment_id": payment_id,
        "token": token,
        "amount": amount,
        "currency": currency,
        "status": "pending",
        "checkout_url": checkout_url,
        "description": description
    }


def get_payment_status(payment_id):
    """Get payment status by ID."""
    import database as db
    return db.get_payment(payment_id)


def get_payment_by_token(token):
    """Get payment by token."""
    import database as db
    return db.get_payment_by_token(token)


def simulate_payment(token, payment_data=None):
    """
    Simulate a successful payment.
    In production, this would be replaced with actual payment gateway integration.
    """
    import database as db
    
    payment = db.get_payment_by_token(token)
    if not payment:
        return {"error": "Payment not found", "success": False}
    
    if payment["status"] != "pending":
        return {"error": "Payment already processed", "success": False, "status": payment["status"]}
    
    db.update_payment_status(token, "paid", payment_data)
    
    return {
        "success": True,
        "payment_id": payment["id"],
        "status": "paid",
        "amount": payment["amount"],
        "message": "Payment simulated successfully"
    }


def cancel_payment(token):
    """Cancel a pending payment."""
    import database as db
    
    payment = db.get_payment_by_token(token)
    if not payment:
        return {"error": "Payment not found", "success": False}
    
    if payment["status"] == "paid":
        return {"error": "Cannot cancel paid payment", "success": False}
    
    db.update_payment_status(token, "cancelled")
    
    return {"success": True, "status": "cancelled"}


def get_payments_for_patient(admin_id, patient_id):
    """Get all payments for a patient."""
    import database as db
    return db.get_payments_for_patient(admin_id, patient_id)


def get_payment_stats(admin_id, date_from=None, date_to=None):
    """Get payment statistics for an admin."""
    import database as db
    
    payments = db.get_payments(admin_id, date_from, date_to)
    
    total = sum(p.get("amount", 0) for p in payments if p.get("status") == "paid")
    pending = sum(p.get("amount", 0) for p in payments if p.get("status") == "pending")
    count_paid = len([p for p in payments if p.get("status") == "paid"])
    count_pending = len([p for p in payments if p.get("status") == "pending"])
    count_cancelled = len([p for p in payments if p.get("status") == "cancelled"])
    
    return {
        "total_collected": total,
        "total_pending": pending,
        "paid_count": count_paid,
        "pending_count": count_pending,
        "cancelled_count": count_cancelled,
        "currency": payments[0].get("currency", "USD") if payments else "USD"
    }


def refund_payment(token):
    """Simulate a refund."""
    import database as db
    
    payment = db.get_payment_by_token(token)
    if not payment:
        return {"error": "Payment not found", "success": False}
    
    if payment["status"] != "paid":
        return {"error": "Can only refund paid payments", "success": False}
    
    db.update_payment_status(token, "refunded")
    
    return {"success": True, "status": "refunded"}


def generate_invoice(payment_id):
    """Generate invoice data for a payment."""
    import database as db
    
    payment = db.get_payment(payment_id)
    if not payment:
        return None
    
    return {
        "invoice_number": f"INV-{payment['id']:06d}",
        "date": payment.get("created_at", datetime.now().isoformat()),
        "patient": payment.get("patient_name", "Patient"),
        "email": payment.get("patient_email", ""),
        "description": payment.get("description", "Service"),
        "amount": payment.get("amount", 0),
        "currency": payment.get("currency", "USD"),
        "status": payment.get("status", "pending"),
        "paid_at": payment.get("paid_at")
    }
