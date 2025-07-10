from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime, timedelta
from twilio.rest import Client
import mysql.connector
import os
from dotenv import load_dotenv

# Carica le variabili dal file .env
load_dotenv()

# Configurazione Twilio
twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')
client = Client(twilio_account_sid, twilio_auth_token)

# Configurazione MySQL
db_config = {
    "host": os.getenv('DB_HOST'),
    "user": os.getenv('DB_USER'),
    "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_NAME')
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def send_sms(to, message):
    try:
        client.messages.create(body=message, from_=twilio_phone_number, to=to)
        print(f"SMS inviato a {to}: {message}")
        return True
    except Exception as e:
        print(f"Errore durante l'invio dell'SMS a {to}: {e}")
        return False

def check_reminder_date(reminder_date):
    today = datetime.now().date()
    reminder_date_obj = datetime.strptime(reminder_date, '%Y-%m-%d').date()
    return today + timedelta(days=3) == reminder_date_obj

def mark_reminder_sent(reminder_id):
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("UPDATE reminders SET sent = TRUE WHERE id = %s", (reminder_id,))
    db.commit()
    cursor.close()
    db.close()

def check_and_send_reminders():
    print("Esecuzione task di controllo promemoria.")
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, phone_number, message, date, sent FROM reminders WHERE sent = FALSE")
    reminders = cursor.fetchall()

    for reminder in reminders:
        if check_reminder_date(reminder['date']):  # Verifica se è il momento di inviare l'SMS
            personal_message = (
                f"Ciao! Ti ricordiamo: {reminder['message']} (Data: {reminder['date']})."
            )
            sms_sent = send_sms(reminder['phone_number'], personal_message)
            if sms_sent:
                mark_reminder_sent(reminder['id'])  # Segna il promemoria come inviato

    cursor.close()
    db.close()

# Configura APScheduler
scheduler = BlockingScheduler()
scheduler.add_job(check_and_send_reminders, 'interval', hours=24)

if __name__ == '__main__':
    print("Background Worker avviato.")
    scheduler.start()
