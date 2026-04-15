"""
Insurance Coverage Engine - Calculate procedure coverage estimates
Uses static rules to estimate coverage based on procedure and insurance type.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INSURANCE_RULES = {
    "delta_dental": {
        "name": "Delta Dental",
        "coverage": {"preventive": 100, "basic": 80, "major": 50, "cosmetic": 0, "orthodontics": 50, "emergency": 80},
        "annual_maximum": 2000, "deductible": 50, "waiting_period_months": 6
    },
    "cigna_dental": {
        "name": "Cigna Dental", 
        "coverage": {"preventive": 100, "basic": 80, "major": 50, "cosmetic": 0, "orthodontics": 40, "emergency": 80},
        "annual_maximum": 1500, "deductible": 50, "waiting_period_months": 3
    },
    "metlife_dental": {
        "name": "MetLife Dental",
        "coverage": {"preventive": 100, "basic": 70, "major": 50, "cosmetic": 0, "orthodontics": 50, "emergency": 70},
        "annual_maximum": 2500, "deductible": 25, "waiting_period_months": 6
    },
    "aetna_dental": {
        "name": "Aetna Dental",
        "coverage": {"preventive": 100, "basic": 80, "major": 50, "cosmetic": 0, "orthodontics": 50, "emergency": 80},
        "annual_maximum": 2000, "deductible": 50, "waiting_period_months": 6
    },
    "united_healthcare": {
        "name": "United Healthcare Dental",
        "coverage": {"preventive": 100, "basic": 80, "major": 50, "cosmetic": 0, "orthodontics": 50, "emergency": 80},
        "annual_maximum": 3000, "deductible": 50, "waiting_period_months": 3
    },
    "bupa_arabia": {
        "name": "Bupa Arabia",
        "coverage": {"preventive": 100, "basic": 90, "major": 70, "cosmetic": 10, "orthodontics": 50, "emergency": 90},
        "annual_maximum": 5000, "deductible": 0, "waiting_period_months": 0
    },
    "tawuniya": {
        "name": "Tawuniya Insurance",
        "coverage": {"preventive": 100, "basic": 85, "major": 60, "cosmetic": 5, "orthodontics": 40, "emergency": 85},
        "annual_maximum": 4000, "deductible": 25, "waiting_period_months": 3
    },
    "medgulf": {
        "name": "MedGulf",
        "coverage": {"preventive": 100, "basic": 80, "major": 60, "cosmetic": 0, "orthodontics": 45, "emergency": 80},
        "annual_maximum": 3500, "deductible": 50, "waiting_period_months": 6
    },
    "allianz": {
        "name": "Allianz Saudi Fransi",
        "coverage": {"preventive": 100, "basic": 85, "major": 65, "cosmetic": 10, "orthodontics": 50, "emergency": 85},
        "annual_maximum": 4000, "deductible": 0, "waiting_period_months": 0
    },
    "axa_cooperative": {
        "name": "AXA Cooperative Insurance",
        "coverage": {"preventive": 100, "basic": 80, "major": 60, "cosmetic": 5, "orthodontics": 45, "emergency": 80},
        "annual_maximum": 3000, "deductible": 25, "waiting_period_months": 3
    },
    "no_insurance": {
        "name": "No Insurance / Self-Pay",
        "coverage": {"preventive": 0, "basic": 0, "major": 0, "cosmetic": 0, "orthodontics": 0, "emergency": 0},
        "annual_maximum": 0, "deductible": 0, "waiting_period_months": 0
    }
}

PROCEDURE_CATEGORIES = {
    "preventive": ["cleaning", "checkup", "exam", "x-ray", "fluoride", "sealant", "prophylaxis", "exam"],
    "basic": ["filling", "extraction", "amalgam", "composite", "root canal", "endodontic", "filling"],
    "major": ["crown", "bridge", "implant", "denture", "periodontal", "surgery"],
    "cosmetic": ["whitening", "veneer", "bleaching", "bonding", "cosmetic"],
    "orthodontics": ["braces", "aligner", "retainer", "invisalign", "orthodontic"],
    "emergency": ["emergency", "urgent", "pain", "swelling", "trauma", "broken"]
}

AVERAGE_PRICES = {
    "cleaning": 80, "checkup": 60, "exam": 50, "x-ray": 50,
    "filling": 150, "extraction": 120, "extraction_wisdom": 250,
    "root canal": 800, "crown": 1000, "implant": 2500,
    "braces": 5000, "whitening": 400, "bridge": 1200,
    "denture": 1500, "emergency": 200
}


def categorize_procedure(procedure_name):
    """Categorize a procedure based on keywords."""
    procedure_lower = procedure_name.lower()
    for category, keywords in PROCEDURE_CATEGORIES.items():
        for keyword in keywords:
            if keyword in procedure_lower:
                return category
    return "basic"


def get_insurance_info(insurance_type):
    """Get details about an insurance type."""
    key = insurance_type.lower().replace(" ", "_").replace("-", "_")
    return INSURANCE_RULES.get(key, INSURANCE_RULES["no_insurance"])


def get_available_insurance_types():
    """Get list of all available insurance types."""
    return [
        {"key": key, "name": value["name"], "annual_maximum": value["annual_maximum"], "deductible": value["deductible"]}
        for key, value in INSURANCE_RULES.items()
    ]


def get_average_price(procedure_name):
    """Get average price for a procedure."""
    procedure_lower = procedure_name.lower()
    for key, price in AVERAGE_PRICES.items():
        if key in procedure_lower or procedure_lower in key:
            return price
    return 100


def calculate_coverage(insurance_type, procedure_name, procedure_price=None):
    """Calculate insurance coverage for a procedure."""
    insurance_info = get_insurance_info(insurance_type)
    category = categorize_procedure(procedure_name)
    coverage_pct = insurance_info["coverage"].get(category, 0)
    
    if procedure_price is None:
        procedure_price = get_average_price(procedure_name)
    
    insurance_payment = procedure_price * (coverage_pct / 100)
    patient_responsibility = procedure_price - insurance_payment
    
    return {
        "insurance_type": insurance_info["name"],
        "procedure": procedure_name,
        "category": category,
        "list_price": procedure_price,
        "coverage_percentage": coverage_pct,
        "insurance_payment": round(insurance_payment, 2),
        "patient_responsibility": round(patient_responsibility, 2),
        "annual_maximum": insurance_info["annual_maximum"],
        "deductible": insurance_info["deductible"],
        "waiting_period_months": insurance_info["waiting_period_months"]
    }


def estimate_total_cost(insurance_type, procedures):
    """Estimate total cost for multiple procedures."""
    subtotal = 0
    total_insurance = 0
    total_patient = 0
    details = []
    
    for proc in procedures:
        coverage = calculate_coverage(insurance_type, proc.get("name", ""), proc.get("price"))
        subtotal += coverage["list_price"]
        total_insurance += coverage["insurance_payment"]
        total_patient += coverage["patient_responsibility"]
        details.append(coverage)
    
    insurance_info = get_insurance_info(insurance_type)
    
    return {
        "procedures": details,
        "subtotal": round(subtotal, 2),
        "insurance_payment": round(total_insurance, 2),
        "patient_responsibility": round(total_patient, 2),
        "annual_maximum": insurance_info["annual_maximum"],
        "deductible": insurance_info["deductible"],
        "remaining_benefits": max(0, insurance_info["annual_maximum"] - total_insurance)
    }
