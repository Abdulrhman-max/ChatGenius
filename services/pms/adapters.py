"""
PMS (Practice Management System) Integration - Base Adapter
=========================================================

This module provides an abstraction layer for integrating with various
dental Practice Management Systems and healthcare EMR/EHR platforms.

Current Adapters:
- MockAdapter: Local mock PMS for development/testing
- DentrixAdapter: Dentrix dental PMS integration
- EaglesoftAdapter: Eaglesoft dental PMS integration
- OpenDentalAdapter: Open Dental API integration
- EpicAdapter: Epic EHR integration (healthcare)
- CernerAdapter: Cerner/Oracle Health EHR integration
- AthenaHealthAdapter: Athenahealth EHR integration
- ZocdocAdapter: Zocdoc scheduling platform integration

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
import logging

logger = logging.getLogger(__name__)


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

    # ─── Extended Methods (with default implementations) ─────────

    def sync_patients(self) -> Dict[str, Any]:
        """Sync only patients from the external system."""
        return {"status": "not_implemented", "adapter": self.__class__.__name__}

    def sync_appointments(self) -> Dict[str, Any]:
        """Sync only appointments from the external system."""
        return {"status": "not_implemented", "adapter": self.__class__.__name__}

    def get_providers(self) -> List[Dict]:
        """Get list of providers/doctors. Alias for get_doctors()."""
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        """Get schedule for a provider on a specific date."""
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        return {"status": "not_implemented"}


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
            conn.execute(f"UPDATE pms_patients SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", values)
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
    Dentrix Integration Adapter

    Dentrix by Henry Schein uses a local API server (Dentrix Developer Program).
    API base: typically http://localhost:XXXX or via Dentrix Ascend cloud API.

    Authentication: OAuth 2.0 (Dentrix Ascend) or API key (Dentrix G-series local).

    To implement fully:
    1. Register as a Dentrix Developer Partner at developer.dentrix.com
    2. Obtain API credentials (client_id, client_secret)
    3. Configure the local Dentrix API server or Ascend cloud endpoint
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "https://api.dentrixascend.com/v1")
        self.api_key = config.get("api_key", "")
        self.clinic_id = config.get("clinic_id", "")
        self.organization_id = config.get("organization_id", "")

    def _headers(self) -> Dict[str, str]:
        """Build authorization headers for Dentrix API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Organization-Id": self.organization_id,
        }

    def connect(self) -> bool:
        """
        Establish connection to Dentrix.
        TODO: Implement OAuth token exchange for Dentrix Ascend
        TODO: For Dentrix G-series, validate local API server availability
        """
        try:
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Dentrix connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        """Disconnect from Dentrix API."""
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """
        Test Dentrix API connectivity.
        TODO: Make actual HTTP request to Dentrix health endpoint
        Endpoint: GET /v1/health or GET /v1/organizations/{org_id}
        """
        if not self.base_url or not self.api_key:
            return {
                "status": "error",
                "message": "Dentrix API URL and API key are required",
                "adapter": "dentrix"
            }
        # TODO: Implement actual HTTP health check
        # import requests
        # resp = requests.get(f"{self.base_url}/health", headers=self._headers(), timeout=10)
        return {
            "status": "pending_implementation",
            "message": "Dentrix adapter configured but not yet connected to live API",
            "adapter": "dentrix",
            "config": {"base_url": self.base_url, "has_api_key": bool(self.api_key)}
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """
        Fetch patients from Dentrix.
        TODO: GET /v1/patients?search={search}&limit={limit}
        Dentrix returns: PatientId, FirstName, LastName, DateOfBirth, Phone, Email
        """
        raise NotImplementedError("Dentrix get_patients: awaiting API credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """
        Fetch single patient from Dentrix.
        TODO: GET /v1/patients/{patient_id}
        """
        raise NotImplementedError("Dentrix get_patient: awaiting API credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """
        Create patient in Dentrix.
        TODO: POST /v1/patients
        Body: { FirstName, LastName, DateOfBirth, Phone, Email, Address }
        """
        raise NotImplementedError("Dentrix create_patient: awaiting API credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """
        Update patient in Dentrix.
        TODO: PUT /v1/patients/{patient_id}
        """
        raise NotImplementedError("Dentrix update_patient: awaiting API credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """
        Fetch appointments from Dentrix.
        TODO: GET /v1/appointments?dateFrom={date_from}&dateTo={date_to}&status={status}
        Dentrix returns: AppointmentId, PatientId, ProviderId, Date, StartTime, Duration, Status
        """
        raise NotImplementedError("Dentrix get_appointments: awaiting API credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """
        Fetch single appointment from Dentrix.
        TODO: GET /v1/appointments/{appointment_id}
        """
        raise NotImplementedError("Dentrix get_appointment: awaiting API credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        """
        Create appointment in Dentrix.
        TODO: POST /v1/appointments
        Body: { PatientId, ProviderId, Date, StartTime, Duration, ProcedureCode, Notes }
        """
        raise NotImplementedError("Dentrix create_appointment: awaiting API credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """
        Update appointment in Dentrix.
        TODO: PUT /v1/appointments/{appointment_id}
        """
        raise NotImplementedError("Dentrix update_appointment: awaiting API credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """
        Cancel appointment in Dentrix.
        TODO: DELETE /v1/appointments/{appointment_id}  or  PUT with status=cancelled
        """
        raise NotImplementedError("Dentrix cancel_appointment: awaiting API credentials")

    def get_doctors(self) -> List[Dict]:
        """
        Fetch providers from Dentrix.
        TODO: GET /v1/providers
        Dentrix returns: ProviderId, FirstName, LastName, Specialty, NPI
        """
        raise NotImplementedError("Dentrix get_doctors: awaiting API credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """
        Fetch provider schedule from Dentrix.
        TODO: GET /v1/providers/{doctor_id}/schedule?date={date}
        """
        raise NotImplementedError("Dentrix get_doctor_schedule: awaiting API credentials")

    def sync_all(self) -> Dict[str, Any]:
        """
        Full sync from Dentrix.
        TODO: Orchestrate patient + appointment + provider sync
        """
        raise NotImplementedError("Dentrix sync_all: awaiting API credentials")

    def sync_patients(self) -> Dict[str, Any]:
        """TODO: Fetch all patients from Dentrix and upsert into local DB."""
        raise NotImplementedError("Dentrix sync_patients: awaiting API credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        """TODO: Fetch all appointments from Dentrix and upsert into local DB."""
        raise NotImplementedError("Dentrix sync_appointments: awaiting API credentials")

    def get_providers(self) -> List[Dict]:
        """Alias for get_doctors()."""
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        """Get schedule for a Dentrix provider."""
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Dentrix get_schedule: provider_id and date required")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "dentrix"}


class EaglesoftAdapter(BasePMSAdapter):
    """
    Eaglesoft Integration Adapter

    Eaglesoft by Patterson Dental uses a local database connection
    (Firebird/Interbase) or the Patterson Fuse API.

    Authentication: API key via Patterson developer portal.

    To implement:
    1. Register at developer.pattersondental.com
    2. Obtain Fuse API credentials
    3. Configure the connection parameters
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "https://api.pattersondental.com/fuse/v1")
        self.api_key = config.get("api_key", "")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def connect(self) -> bool:
        """TODO: Validate Eaglesoft/Fuse API connectivity."""
        try:
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Eaglesoft connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """TODO: GET /fuse/v1/health"""
        if not self.base_url or not self.api_key:
            return {"status": "error", "message": "Eaglesoft API URL and key required", "adapter": "eaglesoft"}
        return {"status": "pending_implementation", "message": "Eaglesoft adapter configured", "adapter": "eaglesoft"}

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """TODO: GET /fuse/v1/patients?search={search}&limit={limit}"""
        raise NotImplementedError("Eaglesoft get_patients: awaiting API credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """TODO: GET /fuse/v1/patients/{patient_id}"""
        raise NotImplementedError("Eaglesoft get_patient: awaiting API credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """TODO: POST /fuse/v1/patients"""
        raise NotImplementedError("Eaglesoft create_patient: awaiting API credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """TODO: PUT /fuse/v1/patients/{patient_id}"""
        raise NotImplementedError("Eaglesoft update_patient: awaiting API credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """TODO: GET /fuse/v1/appointments?from={date_from}&to={date_to}"""
        raise NotImplementedError("Eaglesoft get_appointments: awaiting API credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        raise NotImplementedError("Eaglesoft get_appointment: awaiting API credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft create_appointment: awaiting API credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        raise NotImplementedError("Eaglesoft update_appointment: awaiting API credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        raise NotImplementedError("Eaglesoft cancel_appointment: awaiting API credentials")

    def get_doctors(self) -> List[Dict]:
        """TODO: GET /fuse/v1/providers"""
        raise NotImplementedError("Eaglesoft get_doctors: awaiting API credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        raise NotImplementedError("Eaglesoft get_doctor_schedule: awaiting API credentials")

    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Eaglesoft sync_all: awaiting API credentials")

    def sync_patients(self) -> Dict[str, Any]:
        raise NotImplementedError("Eaglesoft sync_patients: awaiting API credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        raise NotImplementedError("Eaglesoft sync_appointments: awaiting API credentials")

    def get_providers(self) -> List[Dict]:
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Eaglesoft get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "eaglesoft"}


class OpenDentalAdapter(BasePMSAdapter):
    """
    Open Dental Integration Adapter

    Open Dental provides a REST API (Open Dental API).
    Documentation: https://www.opendental.com/site/apiref.html

    Base URL: https://{server}/api/v1
    Authentication: API key in header (X-OPENDENTAL-PMPKEY)

    Key endpoints:
    - GET  /api/v1/patients          — List patients
    - GET  /api/v1/patients/{PatNum} — Get patient
    - POST /api/v1/patients          — Create patient
    - PUT  /api/v1/patients/{PatNum} — Update patient
    - GET  /api/v1/appointments      — List appointments
    - POST /api/v1/appointments      — Create appointment
    - PUT  /api/v1/appointments/{AptNum} — Update appointment
    - GET  /api/v1/providers         — List providers
    - GET  /api/v1/schedules         — List schedules
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.server = config.get("server", "")
        self.database = config.get("database", "")
        # Build base URL from server if api_url not provided
        if not self.base_url and self.server:
            self.base_url = f"https://{self.server}/api/v1"

    def _headers(self) -> Dict[str, str]:
        """Open Dental uses X-OPENDENTAL-PMPKEY header for authentication."""
        return {
            "X-OPENDENTAL-PMPKEY": self.api_key,
            "Content-Type": "application/json",
        }

    def connect(self) -> bool:
        """
        Connect to Open Dental API.
        TODO: Validate credentials by calling GET /api/v1/patients?limit=1
        """
        try:
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Open Dental connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """
        Test Open Dental API connectivity.
        TODO: GET /api/v1/patients?limit=1 to verify credentials
        """
        if not self.base_url or not self.api_key:
            return {"status": "error", "message": "Open Dental API URL and key required", "adapter": "opendental"}
        # TODO: Implement actual connection test
        # import requests
        # resp = requests.get(f"{self.base_url}/patients?Limit=1", headers=self._headers(), timeout=10)
        # if resp.status_code == 200:
        #     return {"status": "success", ...}
        return {
            "status": "pending_implementation",
            "message": "Open Dental adapter configured",
            "adapter": "opendental",
            "config": {"base_url": self.base_url, "has_api_key": bool(self.api_key)}
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """
        Fetch patients from Open Dental.
        TODO: GET /api/v1/patients?LName={search}&Limit={limit}
        Open Dental returns: PatNum, LName, FName, Birthdate, HmPhone, WirelessPhone, Email
        """
        raise NotImplementedError("Open Dental get_patients: awaiting API credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """
        Fetch single patient.
        TODO: GET /api/v1/patients/{PatNum}
        """
        raise NotImplementedError("Open Dental get_patient: awaiting API credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """
        Create patient in Open Dental.
        TODO: POST /api/v1/patients
        Body: { LName, FName, Birthdate, HmPhone, WirelessPhone, Email, Address }
        """
        raise NotImplementedError("Open Dental create_patient: awaiting API credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """
        Update patient in Open Dental.
        TODO: PUT /api/v1/patients/{PatNum}
        """
        raise NotImplementedError("Open Dental update_patient: awaiting API credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """
        Fetch appointments from Open Dental.
        TODO: GET /api/v1/appointments?DateStart={date_from}&DateEnd={date_to}
        Open Dental returns: AptNum, PatNum, ProvNum, AptDateTime, AptStatus, Note
        """
        raise NotImplementedError("Open Dental get_appointments: awaiting API credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """TODO: GET /api/v1/appointments/{AptNum}"""
        raise NotImplementedError("Open Dental get_appointment: awaiting API credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        """
        Create appointment in Open Dental.
        TODO: POST /api/v1/appointments
        Body: { PatNum, ProvNum, AptDateTime, Pattern, Note }
        """
        raise NotImplementedError("Open Dental create_appointment: awaiting API credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """TODO: PUT /api/v1/appointments/{AptNum}"""
        raise NotImplementedError("Open Dental update_appointment: awaiting API credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """TODO: PUT /api/v1/appointments/{AptNum} with AptStatus=Broken"""
        raise NotImplementedError("Open Dental cancel_appointment: awaiting API credentials")

    def get_doctors(self) -> List[Dict]:
        """
        Fetch providers from Open Dental.
        TODO: GET /api/v1/providers
        Returns: ProvNum, Abbr, FName, LName, Specialty, IsHidden
        """
        raise NotImplementedError("Open Dental get_doctors: awaiting API credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """
        Fetch provider schedule from Open Dental.
        TODO: GET /api/v1/schedules?ProvNum={doctor_id}&DateStart={date}&DateEnd={date}
        """
        raise NotImplementedError("Open Dental get_doctor_schedule: awaiting API credentials")

    def sync_all(self) -> Dict[str, Any]:
        """TODO: Orchestrate full sync from Open Dental."""
        raise NotImplementedError("Open Dental sync_all: awaiting API credentials")

    def sync_patients(self) -> Dict[str, Any]:
        """TODO: GET /api/v1/patients with pagination and upsert locally."""
        raise NotImplementedError("Open Dental sync_patients: awaiting API credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        """TODO: GET /api/v1/appointments with date range and upsert locally."""
        raise NotImplementedError("Open Dental sync_appointments: awaiting API credentials")

    def get_providers(self) -> List[Dict]:
        """TODO: GET /api/v1/providers"""
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        """TODO: GET /api/v1/schedules?ProvNum={provider_id}&DateStart={date}"""
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Open Dental get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "opendental"}


# ══════════════════════════════════════════════════════════════
#  Healthcare EMR/EHR Adapters
# ══════════════════════════════════════════════════════════════

class EpicAdapter(BasePMSAdapter):
    """
    Epic EHR Integration Adapter

    Epic uses FHIR R4 APIs (HL7 FHIR standard).
    Base URL: https://{epic_instance}/api/FHIR/R4

    Authentication: OAuth 2.0 (SMART on FHIR)
    - Authorization endpoint: /oauth2/authorize
    - Token endpoint: /oauth2/token

    Key FHIR Resources:
    - Patient:      GET /Patient, GET /Patient/{id}
    - Appointment:  GET /Appointment, POST /Appointment
    - Practitioner: GET /Practitioner
    - Schedule:     GET /Schedule
    - Slot:         GET /Slot
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "").rstrip("/")
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.api_key = config.get("api_key", "")
        self.access_token = ""
        self.token_expires_at = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token or self.api_key}",
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }

    def _ensure_token(self):
        """
        TODO: Implement SMART on FHIR OAuth 2.0 token refresh.
        POST /oauth2/token with client_credentials or authorization_code grant.
        """
        pass

    def connect(self) -> bool:
        """TODO: Authenticate via SMART on FHIR and obtain access token."""
        try:
            self._ensure_token()
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Epic connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.access_token = ""
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """
        Test Epic FHIR API connectivity.
        TODO: GET /metadata (FHIR CapabilityStatement)
        """
        if not self.base_url:
            return {"status": "error", "message": "Epic FHIR base URL is required", "adapter": "epic"}
        return {
            "status": "pending_implementation",
            "message": "Epic FHIR adapter configured. Awaiting SMART on FHIR credentials.",
            "adapter": "epic",
            "fhir_version": "R4"
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """
        TODO: GET /Patient?name={search}&_count={limit}
        Epic FHIR Patient resource includes: id, name, birthDate, telecom, address
        """
        raise NotImplementedError("Epic get_patients: awaiting SMART on FHIR credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """TODO: GET /Patient/{patient_id}"""
        raise NotImplementedError("Epic get_patient: awaiting SMART on FHIR credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """TODO: POST /Patient with FHIR Patient resource body"""
        raise NotImplementedError("Epic create_patient: awaiting SMART on FHIR credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """TODO: PUT /Patient/{patient_id}"""
        raise NotImplementedError("Epic update_patient: awaiting SMART on FHIR credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """
        TODO: GET /Appointment?date=ge{date_from}&date=le{date_to}&status={status}
        Epic FHIR Appointment includes: id, status, start, end, participant, description
        """
        raise NotImplementedError("Epic get_appointments: awaiting SMART on FHIR credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """TODO: GET /Appointment/{appointment_id}"""
        raise NotImplementedError("Epic get_appointment: awaiting SMART on FHIR credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        """TODO: POST /Appointment with FHIR Appointment resource"""
        raise NotImplementedError("Epic create_appointment: awaiting SMART on FHIR credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """TODO: PUT /Appointment/{appointment_id}"""
        raise NotImplementedError("Epic update_appointment: awaiting SMART on FHIR credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """TODO: PUT /Appointment/{appointment_id} with status=cancelled"""
        raise NotImplementedError("Epic cancel_appointment: awaiting SMART on FHIR credentials")

    def get_doctors(self) -> List[Dict]:
        """TODO: GET /Practitioner — returns id, name, qualification, telecom"""
        raise NotImplementedError("Epic get_doctors: awaiting SMART on FHIR credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """TODO: GET /Schedule?actor=Practitioner/{doctor_id}&date={date}"""
        raise NotImplementedError("Epic get_doctor_schedule: awaiting SMART on FHIR credentials")

    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Epic sync_all: awaiting SMART on FHIR credentials")

    def sync_patients(self) -> Dict[str, Any]:
        """TODO: Paginated FHIR Patient search and local upsert."""
        raise NotImplementedError("Epic sync_patients: awaiting credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        """TODO: Paginated FHIR Appointment search and local upsert."""
        raise NotImplementedError("Epic sync_appointments: awaiting credentials")

    def get_providers(self) -> List[Dict]:
        """TODO: GET /Practitioner"""
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        """TODO: GET /Schedule + GET /Slot for available slots."""
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Epic get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "epic"}


class CernerAdapter(BasePMSAdapter):
    """
    Cerner (Oracle Health) EHR Integration Adapter

    Cerner uses FHIR R4 APIs (similar to Epic).
    Base URL: https://fhir-{env}.cerner.com/{tenant_id}/r4

    Authentication: OAuth 2.0
    - Authorization: /tenants/{tenant_id}/protocols/oauth2/profiles/smart-v1/personas/provider/authorize
    - Token: /tenants/{tenant_id}/protocols/oauth2/profiles/smart-v1/token

    Key FHIR Resources:
    - Patient:      GET /Patient
    - Appointment:  GET /Appointment
    - Practitioner: GET /Practitioner
    - Schedule:     GET /Schedule
    - Slot:         GET /Slot
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "").rstrip("/")
        self.tenant_id = config.get("tenant_id", "")
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.api_key = config.get("api_key", "")
        self.access_token = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token or self.api_key}",
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }

    def connect(self) -> bool:
        """TODO: OAuth 2.0 token exchange for Cerner."""
        try:
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Cerner connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.access_token = ""
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """TODO: GET /metadata (FHIR CapabilityStatement)"""
        if not self.base_url:
            return {"status": "error", "message": "Cerner FHIR base URL is required", "adapter": "cerner"}
        return {
            "status": "pending_implementation",
            "message": "Cerner adapter configured. Awaiting OAuth credentials.",
            "adapter": "cerner",
            "fhir_version": "R4"
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """TODO: GET /Patient?name={search}&_count={limit}"""
        raise NotImplementedError("Cerner get_patients: awaiting OAuth credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """TODO: GET /Patient/{patient_id}"""
        raise NotImplementedError("Cerner get_patient: awaiting OAuth credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """TODO: POST /Patient"""
        raise NotImplementedError("Cerner create_patient: awaiting OAuth credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """TODO: PUT /Patient/{patient_id}"""
        raise NotImplementedError("Cerner update_patient: awaiting OAuth credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """TODO: GET /Appointment?date=ge{date_from}&date=le{date_to}"""
        raise NotImplementedError("Cerner get_appointments: awaiting OAuth credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        raise NotImplementedError("Cerner get_appointment: awaiting OAuth credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        raise NotImplementedError("Cerner create_appointment: awaiting OAuth credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        raise NotImplementedError("Cerner update_appointment: awaiting OAuth credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        raise NotImplementedError("Cerner cancel_appointment: awaiting OAuth credentials")

    def get_doctors(self) -> List[Dict]:
        """TODO: GET /Practitioner"""
        raise NotImplementedError("Cerner get_doctors: awaiting OAuth credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """TODO: GET /Schedule?actor=Practitioner/{doctor_id}"""
        raise NotImplementedError("Cerner get_doctor_schedule: awaiting OAuth credentials")

    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Cerner sync_all: awaiting OAuth credentials")

    def sync_patients(self) -> Dict[str, Any]:
        raise NotImplementedError("Cerner sync_patients: awaiting credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        raise NotImplementedError("Cerner sync_appointments: awaiting credentials")

    def get_providers(self) -> List[Dict]:
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Cerner get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "cerner"}


class AthenaHealthAdapter(BasePMSAdapter):
    """
    Athenahealth EHR Integration Adapter

    Athenahealth uses a proprietary REST API (athenaNet API / athenaClinicals).
    Base URL: https://api.athenahealth.com/v1/{practice_id}

    Authentication: OAuth 2.0 (client_credentials grant)
    - Token endpoint: https://api.athenahealth.com/oauth/token

    Key endpoints:
    - GET    /patients                 — Search patients
    - GET    /patients/{patientid}     — Get patient
    - POST   /patients                 — Create patient
    - PUT    /patients/{patientid}     — Update patient
    - GET    /appointments/booked      — Get booked appointments
    - POST   /appointments/{id}/book   — Book appointment
    - PUT    /appointments/{id}/cancel — Cancel appointment
    - GET    /providers                — List providers
    - GET    /providers/{id}/schedule  — Provider schedule
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.practice_id = config.get("practice_id", "")
        self.base_url = config.get("api_url", f"https://api.athenahealth.com/v1/{self.practice_id}").rstrip("/")
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.api_key = config.get("api_key", "")
        self.access_token = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token or self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _authenticate(self):
        """
        TODO: Obtain access token via client_credentials grant.
        POST https://api.athenahealth.com/oauth/token
        Body: grant_type=client_credentials&scope=athena/service/Athenanet.MDP.*
        """
        pass

    def connect(self) -> bool:
        """TODO: Authenticate and validate practice_id."""
        try:
            self._authenticate()
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Athenahealth connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.access_token = ""
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """TODO: GET /practiceinfo to validate credentials and practice_id."""
        if not self.practice_id:
            return {"status": "error", "message": "Athenahealth practice_id is required", "adapter": "athenahealth"}
        return {
            "status": "pending_implementation",
            "message": "Athenahealth adapter configured. Awaiting API credentials.",
            "adapter": "athenahealth",
            "practice_id": self.practice_id
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """TODO: GET /patients?lastname={search}&limit={limit}"""
        raise NotImplementedError("Athenahealth get_patients: awaiting API credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """TODO: GET /patients/{patientid}"""
        raise NotImplementedError("Athenahealth get_patient: awaiting API credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """TODO: POST /patients — Body: firstname, lastname, dob, email, mobilephone"""
        raise NotImplementedError("Athenahealth create_patient: awaiting API credentials")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        """TODO: PUT /patients/{patientid}"""
        raise NotImplementedError("Athenahealth update_patient: awaiting API credentials")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """TODO: GET /appointments/booked?startdate={date_from}&enddate={date_to}"""
        raise NotImplementedError("Athenahealth get_appointments: awaiting API credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """TODO: GET /appointments/{appointmentid}"""
        raise NotImplementedError("Athenahealth get_appointment: awaiting API credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        """TODO: POST /appointments/{appointmentid}/book"""
        raise NotImplementedError("Athenahealth create_appointment: awaiting API credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """TODO: PUT /appointments/{appointmentid}"""
        raise NotImplementedError("Athenahealth update_appointment: awaiting API credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """TODO: PUT /appointments/{appointmentid}/cancel"""
        raise NotImplementedError("Athenahealth cancel_appointment: awaiting API credentials")

    def get_doctors(self) -> List[Dict]:
        """TODO: GET /providers — returns providerid, firstname, lastname, specialty"""
        raise NotImplementedError("Athenahealth get_doctors: awaiting API credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """TODO: GET /appointments/open?providerid={doctor_id}&startdate={date}&enddate={date}"""
        raise NotImplementedError("Athenahealth get_doctor_schedule: awaiting API credentials")

    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Athenahealth sync_all: awaiting API credentials")

    def sync_patients(self) -> Dict[str, Any]:
        """TODO: Paginate GET /patients and upsert locally."""
        raise NotImplementedError("Athenahealth sync_patients: awaiting credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        """TODO: Paginate GET /appointments/booked and upsert locally."""
        raise NotImplementedError("Athenahealth sync_appointments: awaiting credentials")

    def get_providers(self) -> List[Dict]:
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Athenahealth get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "athenahealth"}


class ZocdocAdapter(BasePMSAdapter):
    """
    Zocdoc Integration Adapter

    Zocdoc provides a Provider API for managing appointments and availability.
    Base URL: https://api.zocdoc.com/directory/v2

    Authentication: OAuth 2.0 / API key

    Key endpoints:
    - GET  /providers                        — List providers
    - GET  /providers/{id}/availability      — Get availability slots
    - POST /providers/{id}/appointments      — Create appointment
    - GET  /appointments/{id}                — Get appointment
    - PUT  /appointments/{id}/cancel         — Cancel appointment
    - GET  /patients/{id}                    — Get patient info
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("api_url", "https://api.zocdoc.com/directory/v2").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.provider_id = config.get("provider_id", "")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def connect(self) -> bool:
        """TODO: Validate Zocdoc API credentials."""
        try:
            result = self.test_connection()
            self.is_connected = result.get("status") == "success"
            return self.is_connected
        except Exception as e:
            logger.error(f"Zocdoc connection failed: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    def test_connection(self) -> Dict[str, Any]:
        """TODO: GET /providers/{provider_id} to validate credentials."""
        if not self.api_key:
            return {"status": "error", "message": "Zocdoc API key is required", "adapter": "zocdoc"}
        return {
            "status": "pending_implementation",
            "message": "Zocdoc adapter configured. Awaiting API credentials.",
            "adapter": "zocdoc"
        }

    def get_patients(self, search: str = "", limit: int = 50) -> List[Dict]:
        """
        TODO: GET /patients?search={search}
        Note: Zocdoc patient data is limited to appointment-linked info.
        """
        raise NotImplementedError("Zocdoc get_patients: awaiting API credentials")

    def get_patient(self, patient_id: str) -> Optional[Dict]:
        """TODO: GET /patients/{patient_id}"""
        raise NotImplementedError("Zocdoc get_patient: awaiting API credentials")

    def create_patient(self, patient_data: Dict) -> Dict:
        """Zocdoc patients are created through the booking flow, not directly."""
        raise NotImplementedError("Zocdoc does not support direct patient creation")

    def update_patient(self, patient_id: str, patient_data: Dict) -> Dict:
        raise NotImplementedError("Zocdoc does not support direct patient updates")

    def get_appointments(self, date_from: str = None, date_to: str = None,
                         status: str = None) -> List[Dict]:
        """TODO: GET /providers/{provider_id}/appointments?start={date_from}&end={date_to}"""
        raise NotImplementedError("Zocdoc get_appointments: awaiting API credentials")

    def get_appointment(self, appointment_id: str) -> Optional[Dict]:
        """TODO: GET /appointments/{appointment_id}"""
        raise NotImplementedError("Zocdoc get_appointment: awaiting API credentials")

    def create_appointment(self, appointment_data: Dict) -> Dict:
        """TODO: POST /providers/{provider_id}/appointments"""
        raise NotImplementedError("Zocdoc create_appointment: awaiting API credentials")

    def update_appointment(self, appointment_id: str, data: Dict) -> Dict:
        """TODO: PUT /appointments/{appointment_id}"""
        raise NotImplementedError("Zocdoc update_appointment: awaiting API credentials")

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Dict:
        """TODO: PUT /appointments/{appointment_id}/cancel"""
        raise NotImplementedError("Zocdoc cancel_appointment: awaiting API credentials")

    def get_doctors(self) -> List[Dict]:
        """TODO: GET /providers — returns provider profiles with specialties."""
        raise NotImplementedError("Zocdoc get_doctors: awaiting API credentials")

    def get_doctor_schedule(self, doctor_id: str, date: str) -> Dict:
        """TODO: GET /providers/{doctor_id}/availability?date={date}"""
        raise NotImplementedError("Zocdoc get_doctor_schedule: awaiting API credentials")

    def sync_all(self) -> Dict[str, Any]:
        raise NotImplementedError("Zocdoc sync_all: awaiting API credentials")

    def sync_patients(self) -> Dict[str, Any]:
        raise NotImplementedError("Zocdoc sync_patients: awaiting credentials")

    def sync_appointments(self) -> Dict[str, Any]:
        raise NotImplementedError("Zocdoc sync_appointments: awaiting credentials")

    def get_providers(self) -> List[Dict]:
        return self.get_doctors()

    def get_schedule(self, provider_id: str = None, date: str = None) -> Dict:
        if provider_id and date:
            return self.get_doctor_schedule(provider_id, date)
        raise NotImplementedError("Zocdoc get_schedule requires provider_id and date")

    def get_sync_status(self) -> Dict:
        return {"status": "not_implemented", "adapter": "zocdoc"}


# Adapter registry - add new adapters here
ADAPTERS = {
    "mock": MockAdapter,
    "dentrix": DentrixAdapter,
    "eaglesoft": EaglesoftAdapter,
    "opendental": OpenDentalAdapter,
    "epic": EpicAdapter,
    "cerner": CernerAdapter,
    "athenahealth": AthenaHealthAdapter,
    "zocdoc": ZocdocAdapter,
}


def get_adapter(pms_type: str, config: Dict[str, Any]) -> BasePMSAdapter:
    """Factory function to get the appropriate adapter."""
    adapter_class = ADAPTERS.get(pms_type, MockAdapter)
    return adapter_class(config)
