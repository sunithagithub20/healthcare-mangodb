from pymongo import MongoClient
from datetime import datetime, timedelta
import certifi
import re

# Atlas MongoDB client
MONGO_URI = "mongodb+srv://lakshmisunitha20:703686suni@cluster0.5ucyemr.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client['healthcare_db']

users_collection = db['users']
medications_collection = db['medications']
dose_logs_collection = db['dose_logs']
alert_history_collection = db['alert_history']

# --- USERS ---
def validate_phone_number(phone):
    # Check if phone is exactly 10 digits and does not start with 0
    pattern = r'^[1-9][0-9]{9}$'
    return bool(re.match(pattern, phone))

def create_user(user_data):
    if users_collection.find_one({"username": user_data['username']}):
        return False, "Username already exists"
    
    # Validate phone numbers if they exist in user_data
    if 'caregiver_contact' in user_data and user_data['caregiver_contact']:
        if not validate_phone_number(user_data['caregiver_contact']):
            return False, "Invalid Caregiver Contact number. Must be 10 digits and not start with 0."
            
    if 'phone_number' in user_data and user_data['phone_number']:
        if not validate_phone_number(user_data['phone_number']):
            return False, "Invalid Phone Number. Must be 10 digits and not start with 0."

    user_data['created_at'] = datetime.now()
    users_collection.insert_one(user_data)
    return True, "User created successfully"

def authenticate_user(username, password):
    user = users_collection.find_one({"username": username, "password": password})
    return user

def get_caregivers():
    return list(users_collection.find({"role": "caregiver"}))

def get_patients_for_caregiver(caregiver_username):
    return list(users_collection.find({"role": "patient", "assigned_caregiver": caregiver_username}))

def get_user(username):
    return users_collection.find_one({"username": username})

# --- MEDICATIONS ---
def add_medication(med_data):
    medications_collection.insert_one(med_data)

def get_patient_medications(patient_username):
    return list(medications_collection.find({"patient_username": patient_username}))

# --- DOSE LOGS ---
def log_dose(patient_username, medication_name, scheduled_time, status):
    dose_data = {
        "patient_username": patient_username,
        "medication_name": medication_name,
        "scheduled_time": scheduled_time,
        "actual_time_taken": datetime.now() if status == "Taken" else None,
        "timestamp": datetime.now(),
        "status": status # 'Taken', 'Missed'
    }
    dose_logs_collection.insert_one(dose_data)
    
    if status == "Missed":
        user = get_user(patient_username)
        contact = user.get('caregiver_contact', 'None')
        log_alert(patient_username, contact, f"Patient explicitly marked {medication_name} as Missed")
        
    return True

def get_patient_dose_logs(patient_username):
    return list(dose_logs_collection.find({"patient_username": patient_username}).sort("timestamp", -1))
    
def get_all_dose_logs(patient_usernames=None):
    if patient_usernames is not None:
        return list(dose_logs_collection.find({"patient_username": {"$in": patient_usernames}}).sort("timestamp", -1))
    return list(dose_logs_collection.find().sort("timestamp", -1))

# --- ALERT HISTORY ---
def log_alert(patient_username, caregiver_contact, alert_msg):
    alert_data = {
        "patient_username": patient_username,
        "caregiver_contact": caregiver_contact,
        "message": alert_msg,
        "timestamp": datetime.now(),
        "status": "Sent"
    }
    alert_history_collection.insert_one(alert_data)

def get_alert_history(patient_usernames=None):
    if patient_usernames is not None:
        return list(alert_history_collection.find({"patient_username": {"$in": patient_usernames}}).sort("timestamp", -1))
    return list(alert_history_collection.find().sort("timestamp", -1))

def check_missed_doses():
    # Complex checker logic:
    # We find all patients, look up their scheduled medications.
    # If they haven't logged a dose today for a medication, we flag it.
    patients = users_collection.find({"role": "patient"})
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    missed_alerts = []
    
    for patient in patients:
        meds = get_patient_medications(patient['username'])
        for med in meds:
            # check if any action was logged today (Taken, Missed, or already Alerted)
            logged_today = dose_logs_collection.find_one({
                "patient_username": patient['username'],
                "medication_name": med['drug_name'],
                "status": {"$in": ["Taken", "Missed", "Missed Alerts Sent Today"]},
                "timestamp": {"$gte": today_start}
            })
            
            if not logged_today:
                caregiver_contact = patient.get('caregiver_contact', 'None')
                missed_alerts.append({
                    "patient": patient['username'],
                    "medication_name": med['drug_name'],
                    "caregiver_contact": caregiver_contact
                })
                # Log it so we don't alert again today
                dose_logs_collection.insert_one({
                    "patient_username": patient['username'],
                    "medication_name": med['drug_name'],
                    "status": "Missed Alerts Sent Today",
                    "timestamp": datetime.now()
                })

    return missed_alerts

# --- HEALTH VITALS ---
vitals_collection = db['health_vitals']

def log_vitals(patient_username, vitals_data):
    vitals_data['patient_username'] = patient_username
    vitals_data['timestamp'] = datetime.now()
    
    # Automatic Health Alert Logic
    alert_triggered = False
    reasons = []
    
    # 1. Check Blood Pressure
    bp = vitals_data.get('bp', '')
    if '/' in bp:
        try:
            sys, dia = map(int, bp.split('/'))
            if sys > 140 or dia > 90:
                alert_triggered = True
                reasons.append(f"High BP ({bp})")
        except ValueError:
            pass
            
    # 2. Check Heart Rate
    hr = vitals_data.get('hr')
    if hr:
        try:
            hr_val = int(hr)
            if hr_val > 120 or hr_val < 50:
                alert_triggered = True
                reasons.append(f"Abnormal HR ({hr_val} BPM)")
        except ValueError:
            pass
            
    # 3. Check Glucose
    glucose = vitals_data.get('glucose')
    if glucose:
        try:
            gl_val = int(glucose)
            if gl_val > 200 or gl_val < 70:
                alert_triggered = True
                reasons.append(f"Abnormal Glucose ({gl_val} mg/dL)")
        except ValueError:
            pass
            
    if alert_triggered:
        user = get_user(patient_username)
        contact = user.get('caregiver_contact', 'None')
        log_alert(patient_username, contact, f"Vital Warning: {', '.join(reasons)}")
        vitals_data['status'] = 'Warning'
    else:
        vitals_data['status'] = 'Stable'

    vitals_collection.insert_one(vitals_data)
    return True

def get_patient_vitals(patient_username, limit=10):
    return list(vitals_collection.find({"patient_username": patient_username}).sort("timestamp", -1).limit(limit))

def get_latest_vitals_all_patients():
    # Return a mapping of patient_username to their latest vitals
    pipeline = [
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$patient_username",
            "latest_vitals": {"$first": "$$ROOT"}
        }}
    ]
    results = list(vitals_collection.aggregate(pipeline))
    return {r['_id']: r['latest_vitals'] for r in results}
