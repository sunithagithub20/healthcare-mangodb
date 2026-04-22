from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import db_handler
import threading
import time

app = Flask(__name__)
app.secret_key = 'healthcare_super_secret_complex'

def simulated_sns_alert(patient, contact, med_name):
    msg = f"[LOCAL ALERT] SMS SIMULATION: Alerting Caregiver at {contact} - Patient {patient} missed their dose of {med_name}!"
    print(msg)
    db_handler.log_alert(patient, contact, f"Missed {med_name}")

def background_checker():
    # Loop to periodically check for missed doses
    while True:
        missed = db_handler.check_missed_doses()
        for m in missed:
            simulated_sns_alert(m['patient'], m['caregiver_contact'], m['medication_name'])
        time.sleep(60)

# Start background thread
thread = threading.Thread(target=background_checker, daemon=True)
thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = db_handler.authenticate_user(username, password)
        if user:
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'patient':
                return redirect(url_for('patient_dashboard'))
            else:
                return redirect(url_for('caregiver_dashboard'))
        else:
            return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_data = dict(request.form)
        
        # Automatically fetch caregiver contact to prevent mismatch
        if user_data.get('role') == 'patient' and user_data.get('assigned_caregiver'):
            cg = db_handler.get_user(user_data['assigned_caregiver'])
            if cg:
                user_data['caregiver_contact'] = cg.get('phone_number', 'N/A')
                
        success, message = db_handler.create_user(user_data)
        if success:
            return redirect(url_for('login'))
        else:
            caregivers = db_handler.get_caregivers()
            return render_template('register.html', error=message, caregivers=caregivers)
    
    caregivers = db_handler.get_caregivers()
    return render_template('register.html', caregivers=caregivers)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/patient_dashboard')
def patient_dashboard():
    if 'username' not in session or session['role'] != 'patient':
        return redirect(url_for('login'))
    
    patient = db_handler.get_user(session['username'])
    meds = db_handler.get_patient_medications(session['username'])
    recent_doses = db_handler.get_patient_dose_logs(session['username'])
    vitals = db_handler.get_patient_vitals(session['username'])
    
    # Prepare data for Chart.js
    chart_data = {
        "labels": [v['timestamp'].strftime('%m/%d %H:%M') for v in reversed(vitals)],
        "hr": [v.get('hr', 0) for v in reversed(vitals)],
        "glucose": [v.get('glucose', 0) for v in reversed(vitals)],
        "bp_sys": [],
        "bp_dia": []
    }
    
    for v in reversed(vitals):
        bp = v.get('bp', '')
        if '/' in bp:
            try:
                s, d = map(int, bp.split('/'))
                chart_data["bp_sys"].append(s)
                chart_data["bp_dia"].append(d)
            except:
                chart_data["bp_sys"].append(0)
                chart_data["bp_dia"].append(0)
        else:
            chart_data["bp_sys"].append(0)
            chart_data["bp_dia"].append(0)

    return render_template('patient_dashboard.html', 
                           patient=patient, 
                           meds=meds, 
                           recent_doses=recent_doses,
                           vitals=vitals,
                           chart_data=chart_data)

@app.route('/patient_vitals')
def patient_vitals():
    if 'username' not in session or session['role'] != 'patient':
        return redirect(url_for('login'))
    
    meds = db_handler.get_patient_medications(session['username'])
    return render_template('patient_vitals.html', meds=meds)

@app.route('/api/log_specific_dose', methods=['POST'])
def api_log_specific_dose():
    if 'username' not in session or session['role'] != 'patient':
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    data = request.json
    med_name = data.get('medication_name')
    status = data.get('status', 'Taken')
    
    if med_name:
        db_handler.log_dose(session['username'], med_name, "Scheduled", status)
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route('/api/log_vitals', methods=['POST'])
def api_log_vitals():
    if 'username' not in session or session['role'] != 'patient':
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    data = request.json
    db_handler.log_vitals(session['username'], data)
    return jsonify({"success": True})

@app.route('/caregiver_dashboard')
def caregiver_dashboard():
    if 'username' not in session or session['role'] != 'caregiver':
        return redirect(url_for('login'))
        
    patients = db_handler.get_patients_for_caregiver(session['username'])
    patient_usernames = [p['username'] for p in patients]
    
    all_doses = db_handler.get_all_dose_logs(patient_usernames)
    alert_history = db_handler.get_alert_history(patient_usernames)
    patient_vitals = db_handler.get_latest_vitals_all_patients()
    
    return render_template('caregiver_dashboard.html', 
                           username=session['username'], 
                           patients=patients,
                           all_doses=all_doses,
                           alert_history=alert_history,
                           patient_vitals=patient_vitals)

@app.route('/assign_meds', methods=['GET', 'POST'])
def assign_meds():
    if 'username' not in session or session['role'] != 'caregiver':
        return redirect(url_for('login'))

    if request.method == 'POST':
        med_data = {
            "patient_username": request.form['patient_username'],
            "drug_name": request.form['drug_name'],
            "dosage": request.form['dosage'],
            "frequency": request.form['frequency'],
            "instructions": request.form['instructions']
        }
        db_handler.add_medication(med_data)
        return redirect(url_for('caregiver_dashboard'))

    patients = db_handler.get_patients_for_caregiver(session['username'])
    all_doses = db_handler.get_all_dose_logs()
    return render_template('assign_meds.html', patients=patients, all_doses=all_doses)

if __name__ == '__main__':
    # Initialize some test users via dict to support new schema if they don't exist
    db_handler.create_user({
        'username':'john', 'password':'pass123', 'role':'patient', 
        'name':'John Doe', 'age': 45,
        'blood_group': 'O+', 'caregiver_contact': '555-0000'
    })
    db_handler.create_user({
        'username':'mary', 'password':'pass123', 'role':'caregiver',
        'name': 'Mary Smith', 'phone_number': '9123456789'
    })
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
