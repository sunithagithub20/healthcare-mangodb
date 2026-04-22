#!/bin/bash
# VitalGuard EC2 Setup Script

echo "Updating system..."
sudo yum update -y

echo "Installing Git..."
sudo yum install git -y

echo "Installing Python and Pip..."
sudo yum install python3 -y
sudo yum install python3-pip -y

echo "Cloning repository..."
# Replace with your actual repository URL
git clone https://github.com/sunithagithub20/healthcare-mangodb.git
cd healthcare-mangodb

echo "Installing dependencies..."
pip3 install -r requirements.txt

echo "Starting the application on port 5000..."
# Running in background with nohup so it keeps running after logout
nohup python3 app.py > app.log 2>&1 &

echo "Setup complete! Please ensure Security Group allows port 5000."
