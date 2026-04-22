import boto3
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime
import os

# AWS Configuration
# In EC2, boto3 will automatically use the IAM Role attached to the instance.
# No need for hardcoded keys!
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

# Table Names
USERS_TABLE = 'HealthcareUsers'
MEDS_TABLE = 'HealthcareMedications'
LOGS_TABLE = 'HealthcareDoseLogs'
ALERTS_TABLE = 'HealthcareAlertHistory'
VITALS_TABLE = 'HealthcareVitals'

# Helper to get table objects
def get_table(name):
    return dynamodb.Table(name)

# --- AUTH & USERS ---
def create_user(user_data):
    table = get_table(USERS_TABLE)
    
    # Validation
    if 'username' not in user_data or 'email' not in user_data:
        return False, "Username and Email are required."
    
    # Check if user already exists (using email as Partition Key)
    existing = table.get_item(Key={'email': user_data['email']})
    if 'Item' in existing:
        return False, "User with this email already exists."
    
    # Store user data
    try:
        table.put_item(Item=user_data)
        return True, "User created successfully."
    except Exception as e:
        return False, str(e)

def get_user_by_email(email):
    table = get_table(USERS_TABLE)
    response = table.get_item(Key={'email': email})
    return response.get('Item')

def get_user(username):
    # In DynamoDB with email as PK, getting by username requires a Scan or GSI.
    # To keep it simple for the user's "Partition Key as email" request, 
    # we will use email as the primary identifier.
    table = get_table(USERS_TABLE)
    response = table.scan(FilterExpression=Attr('username').eq(username))
    items = response.get('Items', [])
    return items[0] if items else None

def get_caregivers():
    table = get_table(USERS_TABLE)
    response = table.scan(FilterExpression=Attr('role').eq('caregiver'))
    return response.get('Items', [])

def get_patients_for_caregiver(caregiver_username):
    table = get_table(USERS_TABLE)
    response = table.scan(FilterExpression=Attr('role').eq('patient') & Attr('assigned_caregiver').eq(caregiver_username))
    return response.get('Items', [])

# --- MEDICATIONS ---
def add_medication(med_data):
    table = get_table(MEDS_TABLE)
    # Using patient_username as PK and drug_name as SK
    try:
        table.put_item(Item=med_data)
        return True
    except:
        return False

def get_patient_medications(patient_username):
    table = get_table(MEDS_TABLE)
    response = table.query(KeyConditionExpression=Key('patient_username').eq(patient_username))
    return response.get('Items', [])

# --- DOSE LOGS ---
def log_dose(patient_username, medication_name, scheduled_time, status):
    table = get_table(LOGS_TABLE)
    timestamp = datetime.now().isoformat()
    
    dose_data = {
        "patient_username": patient_username,
        "medication_name": medication_name,
        "scheduled_time": scheduled_time,
        "status": status,
        "timestamp": timestamp
    }
    
    try:
        table.put_item(Item=dose_data)
        
        # Immediate alert for manual Missed status
        if status == "Missed":
            user = get_user(patient_username)
            contact = user.get('caregiver_contact', 'N/A')
            log_alert(patient_username, contact, f"Patient explicitly marked {medication_name} as Missed")
            
        return True
    except:
        return False

def get_patient_dose_logs(patient_username):
    table = get_table(LOGS_TABLE)
    response = table.query(KeyConditionExpression=Key('patient_username').eq(patient_username))
    # Sort by timestamp (Query returns items sorted by Sort Key by default)
    return sorted(response.get('Items', []), key=lambda x: x['timestamp'], reverse=True)

def get_all_dose_logs(patient_usernames=None):
    table = get_table(LOGS_TABLE)
    if patient_usernames:
        all_items = []
        for uname in patient_usernames:
            response = table.query(KeyConditionExpression=Key('patient_username').eq(uname))
            all_items.extend(response.get('Items', []))
        return sorted(all_items, key=lambda x: x['timestamp'], reverse=True)
    
    response = table.scan()
    return sorted(response.get('Items', []), key=lambda x: x['timestamp'], reverse=True)

# --- ALERT HISTORY ---
def log_alert(patient_username, caregiver_contact, alert_msg):
    table = get_table(ALERTS_TABLE)
    timestamp = datetime.now().isoformat()
    
    alert_data = {
        "patient_username": patient_username,
        "caregiver_contact": caregiver_contact,
        "message": alert_msg,
        "timestamp": timestamp,
        "status": "Sent"
    }
    try:
        table.put_item(Item=alert_data)
    except:
        pass

def get_alert_history(patient_usernames=None):
    table = get_table(ALERTS_TABLE)
    if patient_usernames:
        all_items = []
        for uname in patient_usernames:
            response = table.query(KeyConditionExpression=Key('patient_username').eq(uname))
            all_items.extend(response.get('Items', []))
        return sorted(all_items, key=lambda x: x['timestamp'], reverse=True)
    
    response = table.scan()
    return sorted(response.get('Items', []), key=lambda x: x['timestamp'], reverse=True)

# --- BACKGROUND MONITORING ---
def check_missed_doses():
    patients_table = get_table(USERS_TABLE)
    patients = patients_table.scan(FilterExpression=Attr('role').eq('patient')).get('Items', [])
    
    today_start = datetime.now().strftime('%Y-%m-%d')
    missed_alerts = []
    
    for patient in patients:
        meds = get_patient_medications(patient['username'])
        for med in meds:
            # Check for any action today in logs
            logs_table = get_table(LOGS_TABLE)
            # This is a bit complex in DynamoDB without GSI, but we use scan with filter for simplicity
            response = logs_table.scan(
                FilterExpression=Attr('patient_username').eq(patient['username']) & 
                                 Attr('medication_name').eq(med['drug_name']) &
                                 Attr('timestamp').begins_with(today_start) &
                                 Attr('status').is_in(['Taken', 'Missed', 'Missed Alerts Sent Today'])
            )
            
            if not response.get('Items'):
                # Trigger alert
                caregiver_contact = patient.get('caregiver_contact', 'N/A')
                missed_alerts.append({
                    "patient": patient['username'],
                    "medication_name": med['drug_name'],
                    "caregiver_contact": caregiver_contact
                })
                # Log the alert to prevent repeat
                log_dose(patient['username'], med['drug_name'], "Auto-Check", "Missed Alerts Sent Today")
                
    return missed_alerts

# --- VITALS ---
def log_vitals(patient_username, vitals_data):
    table = get_table(VITALS_TABLE)
    vitals_data['patient_username'] = patient_username
    vitals_data['timestamp'] = datetime.now().isoformat()
    try:
        table.put_item(Item=vitals_data)
        return True
    except:
        return False

def get_patient_vitals(patient_username):
    table = get_table(VITALS_TABLE)
    response = table.query(KeyConditionExpression=Key('patient_username').eq(patient_username))
    return sorted(response.get('Items', []), key=lambda x: x['timestamp'], reverse=True)

def get_latest_vitals_all_patients():
    table = get_table(VITALS_TABLE)
    response = table.scan() # Simple scan for latest
    items = response.get('Items', [])
    
    latest_vitals = {}
    for item in items:
        p = item['patient_username']
        if p not in latest_vitals or item['timestamp'] > latest_vitals[p]['timestamp']:
            latest_vitals[p] = item
            
    return latest_vitals
