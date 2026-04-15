"""
PMS (Practice Management System) Integration - Base Adapter
=========================================================

This module provides an abstraction layer for integrating with various
dental Practice Management Systems.

Current Adapters:
- MockAdapter: Local mock PMS for development/testing
- DentrixAdapter: Stub for future Dentrix integration
- EaglesoftAdapter: Stub for future Eaglesoft integration
- OpenDentalAdapter: Stub for future Open Dental integration

To add a new PMS:
1. Create a new adapter class inheriting from BasePMSAdapter
2. Implement all required methods
3. Add the adapter to ADAPTERS dict
4. Update pms_engine.py to use the new adapter
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from datetime import datetime
import json


class BasePMSAdapter(ABC):
    """Abstract base class for PMS adapters."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize adapter with configuration.
        
        Args:
            config: Dictionary containing:
                - api_url: PMS API endpoint
                - api_key: Authentication key
                - clinic_id: Clinic identifier
                - ...
        """
        self.config = config
        self.is_connected = False
    
    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to PMS. Returns True if successful."""
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """Close connection to PMS. Returns True if successful."""
        pass
    
    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection. Returns status dict."""
        pass
    
    # ─── Patients ────────────────────────────────────────────────
    
    @abstractmethod
    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """Get list of patients. Search by name/email/phone."""
        pass
    
    @abstractmethod
    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """Get single patient by ID."""
        pass
    
    @abstractmethod
    def create_patient(self, patient_data: Dict) -> Dict:
        """Create new patient. Returns created patient with ID."""
        pass
    
    @abstractmethod
    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """Update existing patient."""
        pass
    
    # ─── Appointments ────────────────────────────────────────────
    
    @abstractmethod
    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """Get appointments within date range."""
        pass
    
    @abstractmethod
    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """Get single appointment by ID."""
        pass
    
    @abstractmethod
    def create_appointment(self, appointment_data: Dict) -> Dict:
        """Create new appointment. Returns created appointment."""
        pass
    
    @abstractmethod
    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """Update appointment status/details."""
        pass
    
    @abstractmethod
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """Cancel an appointment."""
        pass
    
    # ─── Doctors/Providers ───────────────────────────────────────
    
    @abstractmethod
    def get_doctors(self) -> List[Dict]:
        """Get list of doctors/providers."""
        pass
    
    @abstractmethod
    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """Get doctor's schedule for a specific date."""
        pass
    
    # ─── Sync ────────────────────────────────────────────────────
    
    @abstractmethod
    def sync_all(self) -> Dict[str, Any]:
        """Full sync: patients, appointments, schedules."""
        pass
    
    @abstractmethod
    def get_sync_status(self) -> Dict:
        """Get last sync timestamp and status."""
        pass


class MockAdapter(BasePMSAdapter):
    """
    Mock PMS Adapter for development and testing.
    Uses local database as backend.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.admin_id = config.get("admin_id", 1)
        self._connect_mock()
    
    def _connect_mock(self):
        """Initialize mock connection."""
        import database as db
        self.db = db
        self.is_connected = True
    
    def connect(self) -> bool:
        self._connect_mock()
        return True
    
    def disconnect(self) -> bool:
        self.is_connected = False
        return True
    
    def test_connection(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "message": "Mock PMS connected",
            "adapter": "mock",
            "timestamp": datetime.now().isoformat()
        }
    
    # ─── Patients ────────────────────────────────────────────────
    
    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        return self.db.get_pms_patients(self.admin_id, search)
    
    def get_patient(self, patient_id: str) -> Optional[Dict]:
        patients = self.get_patients()
        for p in patients:
            if str(p.get("id")) == str(patient_id):
                return p
        return None
    
    def create_patient(self, patient_data: Dict) -> Dict:
        return self.db.create_pms_patient(
            self.admin_id,
            name=patient_data.get("name", ""),
            email=patient_data.get("email", ""),
            phone=patient_data.get("phone", ""),
            date_of_birth=patient_data.get("date_of_birth", ""),
            address=patient_data.get("address", ""),
            insurance_provider=patient_data.get("insurance_provider", ""),
            notes=patient_data.get("notes", "")
        )
    
    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        conn = self.db.get_db()
        updates = {k: v for k, v in patient_data.items() 
                   if k in ["name", "email", "phone", "date_of_birth", "address", 
                           "insurance_provider", "insurance_number", "notes"]}
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            values = list(updates.values()) + [int(patient_id)]
            conn.execute(f"UPDATE pms_patients SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?", values)
            conn.commit()
        conn.close()
        return {"ok": True}
    
    # ─── Appointments ────────────────────────────────────────────
    
    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        return self.db.get_pms_appointments(self.admin_id, date_from, date_to, status)
    
    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        appointments = self.get_appointments()
        for a in appointments:
            if str(a.get("id")) == str(appointment_id):
                return a
        return None
    
    def create_appointment(self, appointment_data: Dict) -> Dict:
        return self.db.create_pms_appointment(
            self.admin_id,
            patient_id=appointment_data.get("patient_id"),
            patient_name=appointment_data.get("patient_name", ""),
            patient_phone=appointment_data.get("patient_phone", ""),
            patient_email=appointment_data.get("patient_email", ""),
            doctor_id=appointment_data.get("doctor_id"),
            doctor_name=appointment_data.get("doctor_name", ""),
            service=appointment_data.get("service", ""),
            date=appointment_data.get("date", ""),
            time=appointment_data.get("time", ""),
            notes=appointment_data.get("notes", "")
        )
    
    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        return self.db.update_pms_appointment(int(appointment_id), data)
    
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        return self.update_appointment(appointment_id, {"status": "cancelled", "notes": reason})
    
    # ─── Doctors ─────────────────────────────────────────────────
    
    def get_doctors(self) -> List[Dict]:
        return self.db.get_pms_doctors(self.admin_id)
    
    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        return self.db.get_pms_schedule(int(doctor_id), date) or {}
    
    # ─── Sync ────────────────────────────────────────────────────
    
    def sync_all(self) -> Dict[str, Any]:
        patients = self.get_patients()
        appointments = self.get_appointments()
        doctors = self.get_doctors()
        
        return {
            "status": "success",
            "records": {
                "patients": len(patients),
                "appointments": len(appointments),
                "doctors": len(doctors)
            },
            "timestamp": datetime.now().isoformat()
        }
    
    def get_sync_status(self) -> Dict:
        status = self.db.get_pms_status(self.admin_id)
        return {
            "last_sync": status.get("last_sync_at", ""),
            "connected": status.get("is_connected", 0) == 1,
            "pms_type": status.get("pms_type", "mock")
        }


class DentrixAdapter(BasePMSAdapter):
    """
    Dentrix Integration Adapter (STUB - Not Implemented)
    
    To implement:
    1. Get Dentrix API credentials
    2. Implement API calls to Dentrix web services
    3. Map Dentrix data models to our schema
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "")
        self.clinic_id = config.get("clinic_id", "")
    
    def connect(self) -> bool:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def disconnect(self) -> bool:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def test_connection(self) -> Dict[str, Any]:
        return {
            "status": "error",
            "message": "Dentrix adapter not yet implemented"
        }
    
    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_patient(self, patient_id: str) -> Optional[Dict]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def create_patient(self, patient_data: Dict) -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def create_appointment(self, appointment_data: Dict) -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_doctors(self) -> List[Dict]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Dentrix adapter not yet implemented")
    
    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "dentrix"}


class EaglesoftAdapter(BasePMSAdapter):
    """
    Eaglesoft Integration Adapter (STUB - Not Implemented)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "")
    
    def connect(self) -> bool:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def disconnect(self) -> bool:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def test_connection(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Eaglesoft adapter not yet implemented"}
    
    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_patient(self, patient_id: str) -> Optional[Dict]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def create_patient(self, patient_data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def create_appointment(self, appointment_data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_doctors(self) -> List[Dict]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Eaglesoft adapter not yet implemented")
    
    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "eaglesoft"}


class OpenDentalAdapter(BasePMSAdapter):
    """
    Open Dental Integration Adapter (STUB - Not Implemented)
    
    Open Dental has an API that can be accessed via:
    https://www.opendental.com/site/technical/apimethods.html
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "")
        self.server = config.get("server", "")
        self.database = config.get("database", "")
    
    def connect(self) -> bool:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def disconnect(self) -> bool:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def test_connection(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Open Dental adapter not yet implemented"}
    
    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_patient(self, patient_id: str) -> Optional[Dict]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def create_patient(self, patient_data: Dict) -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def create_appointment(self, appointment_data: Dict) -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_doctors(self) -> List[Dict]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Open Dental adapter not yet implemented")
    
    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "opendental"}


# Adapter registry - add new adapters here
ADAPTERS = {
    "mock": MockAdapter,
    "dentrix": DentrixAdapter,
    "eaglesoft": EaglesoftAdapter,
    "opendental": OpenDentalAdapter,
}


def get_adapter(pms_type: str, config: Dict[str, Any]) -> BasePMSAdapter:
    """Factory function to get the appropriate adapter."""
    adapter_class = ADAPTERS.get(pms_type, MockAdapter)
    return adapter_class(config)
