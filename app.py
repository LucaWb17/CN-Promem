from flask import Flask, request, render_template, redirect, flash, session, url_for, send_file, jsonify # Aggiunto jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import psycopg2.extras # Aggiunto per DictCursor in app.py se necessario

# Importa i nuovi agenti
from agents import DatabaseAgent, ReminderLogicAgent, NotificationAgent, OrchestratorAgent
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import csv
import io
from dotenv import load_dotenv
import os
from datetime import datetime

# Carica le variabili dal file .env
load_dotenv()

# Configurazione Flask
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')  # Usa la secret key dal file .env

# Configurazione Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Configurazione PostgreSQL
db_config = {
    "host": os.getenv('DB_HOST'),
    "user": os.getenv('DB_USER'),
    "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_NAME'),
    "port": os.getenv('DB_PORT', 5432)  # Porta di default per PostgreSQL
}
print(f"Configurazione DB caricata per: {os.getenv('DB_NAME')}")


# Inizializzazione degli Agenti
# Le configurazioni sono caricate da .env all'inizio di app.py

# Twilio config (già caricate da .env grazie a load_dotenv())
twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')

# Istanzia gli agenti una volta, così possono essere usati dall'app
db_agent = DatabaseAgent(db_config)
reminder_logic_agent = ReminderLogicAgent()

notification_agent = None
orchestrator_agent = None

try:
    if not all([twilio_account_sid, twilio_auth_token, twilio_phone_number]):
        print("ATTENZIONE: Una o più variabili d'ambiente TWILIO non sono impostate (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER). L'invio SMS sarà disabilitato.")
    else:
        notification_agent = NotificationAgent(
            account_sid=twilio_account_sid,
            auth_token=twilio_auth_token,
            phone_number=twilio_phone_number
        )
except ValueError as e: # Cattura il ValueError da NotificationAgent se le credenziali sono vuote dopo il check
    print(f"ERRORE: Impossibile inizializzare NotificationAgent: {e}")
    # notification_agent rimane None

if notification_agent:
    orchestrator_agent = OrchestratorAgent(db_agent, reminder_logic_agent, notification_agent)
else:
    print("ERRORE CRITICO: OrchestratorAgent non può essere inizializzato perché NotificationAgent non è disponibile.")
    # L'app funzionerà ma /trigger_reminders darà errore o sarà disabilitato.

# Funzione per connettersi a PostgreSQL (usata da parti di app.py, DatabaseAgent ha la sua)
def get_db_connection():
    return psycopg2.connect(**db_config)

# Test della connessione al database all'avvio
try:
    conn_test = get_db_connection()
    print("✅ Connessione al database PostgreSQL riuscita!")
    conn_test.close()
except Exception as e:
    print(f"❌ Errore durante la connessione al database PostgreSQL: {e}")


# Funzione per creare le tabelle se non esistono
def create_tables():
    print("Inizio creazione tabelle...")
    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL
            );
        """)
        print("Tabella 'users' creata o già esistente.")
    except Exception as e:
        print(f"Errore nella creazione della tabella 'users': {e}")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                phone_number VARCHAR(15) NOT NULL,
                message TEXT NOT NULL,
                date DATE NOT NULL,
                sent BOOLEAN DEFAULT FALSE
            );
        """)
        print("Tabella 'reminders' creata o già esistente.")
    except Exception as e:
        print(f"Errore nella creazione della tabella 'reminders': {e}")

    db.commit()
    cursor.close()
    db.close()
    print("Tabelle verificate/creazione completata.")

    print("Tabelle verificate/creazione completata.")

# Creazione utente di default
def create_default_user():
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", ("NicoCR",))
    user = cursor.fetchone()

    if not user:
        default_password = generate_password_hash("NicoCR@17")
        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", ("NicoCR", default_password))
        db.commit()
        print("Utente predefinito creato: NicoCR / NicoCR@17")
    else:
        print("Utente predefinito già esistente.")
    
    cursor.close()
    db.close()

# Modello utente per Flask-Login
class User(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

# Funzione per caricare l'utente
@login_manager.user_loader
def load_user(user_id):
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if user:
        return User(id_=user[0], username=user[1])
    return None

# Rotte dell'applicazione

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id, username, password FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user[2], password):
            user_obj = User(id_=user[0], username=user[1])
            login_user(user_obj)
            flash("Accesso effettuato con successo!", "success")
            return redirect(url_for('index'))
        else:
            flash("Credenziali errate. Riprova.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logout effettuato con successo.", "info")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)

@app.route('/upload_csv', methods=['GET', 'POST'])
@login_required
def upload_csv():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash("Nessun file selezionato", "danger")
            return redirect(request.url)

        file = request.files['csv_file']
        if file.filename == '':
            flash("Nessun file caricato", "danger")
            return redirect(request.url)

        if not file.filename.endswith('.csv'):
            flash("Il file deve essere in formato CSV", "danger")
            return redirect(request.url)

        try:
            stream = io.TextIOWrapper(file.stream, encoding='utf-8')
            reader = csv.DictReader(stream)

            required_fields = {'phone_number', 'date'}
            db = get_db_connection()
            cursor = db.cursor()

            for row_number, row in enumerate(reader, start=1):
                if not required_fields.issubset(row.keys()):
                    flash(f"Errore nel CSV: campi mancanti alla riga {row_number}.", "danger")
                    return redirect(request.url)

                phone_number = row['phone_number'].strip()
                reminder_date = row['date'].strip()
                message = row.get('message', '').strip()

                if not phone_number or not reminder_date:
                    flash(f"Dati mancanti alla riga {row_number}: phone_number o date.", "danger")
                    return redirect(request.url)

                try:
                    datetime.strptime(reminder_date, '%Y-%m-%d')
                except ValueError:
                    flash(f"Formato data non valido alla riga {row_number}: {reminder_date}.", "danger")
                    return redirect(request.url)

                if not message:
                    message = f"Ciao! CR Collaudi ti ricorda che il giorno {reminder_date} scade il collaudo. Non dimenticarlo!"

                cursor.execute("""
                    INSERT INTO reminders (phone_number, message, date)
                    VALUES (%s, %s, %s)
                """, (phone_number, message, reminder_date))

            db.commit()
            cursor.close()
            db.close()

            flash("File CSV caricato e promemoria salvati con successo!", "success")
            return redirect(url_for('index'))

        except Exception as e:
            flash(f"Errore durante il caricamento del file CSV: {e}", "danger")
            return redirect(request.url)

    return render_template('upload_csv.html')

@app.route('/download_csv')
@login_required
def download_csv():
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT phone_number, message, date FROM reminders")
    reminders = cursor.fetchall()
    cursor.close()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["phone_number", "message", "date"])
    for reminder in reminders:
        writer.writerow([reminder[0], reminder[1], reminder[2]])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="reminders.csv"
    )

# Rotte temporanee per configurare il database e creare l'utente predefinito
@app.route('/setup_db')
def setup_db():
    try:
        db = get_db_connection()
        cursor = db.cursor()

        # Creazione tabella `users`
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL
            );
        """)
        print("Tabella 'users' creata o già esistente.")

        # Creazione tabella `reminders`
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                phone_number VARCHAR(15) NOT NULL,
                message TEXT NOT NULL,
                date DATE NOT NULL,
                sent BOOLEAN DEFAULT FALSE
            );
        """)
        print("Tabella 'reminders' creata o già esistente.")

        db.commit()
        cursor.close()
        db.close()

        return "Tabelle create con successo!"
    except Exception as e:
        return f"Errore nella creazione delle tabelle: {e}"


@app.route('/create_default_user')
def create_default_user_route():
    try:
        db = get_db_connection()
        cursor = db.cursor()

        # Verifica se l'utente esiste
        cursor.execute("SELECT id FROM users WHERE username = %s", ("NicoCR",))
        user = cursor.fetchone()

        if not user:
            default_password = generate_password_hash("NicoCR@17")
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", ("NicoCR", default_password))
            db.commit()
            return "Utente predefinito creato con successo!"
        else:
            return "Utente predefinito già esistente."

    except Exception as e:
        return f"Errore nella creazione dell'utente predefinito: {e}"
    finally:
        cursor.close()
        db.close()

# Nuova rotta per attivare il processo dei promemoria
@app.route('/trigger_reminders', methods=['POST']) # Usare POST per azioni che modificano stato o eseguono task
@login_required # Proteggere l'endpoint
def trigger_reminders_route():
    if not orchestrator_agent:
        flash("Il sistema di promemoria non è correttamente configurato (NotificationAgent o OrchestratorAgent mancante). Controllare i log del server.", "danger")
        return redirect(url_for('index'))

    try:
        # Qui potresti aggiungere un controllo ulteriore, es. un token specifico se non vuoi solo @login_required
        # Oppure verificare se l'utente è un admin
        print(f"Richiesta di trigger promemoria da utente: {current_user.username} (ID: {current_user.id})")
        result = orchestrator_agent.process_reminders()

        flash(f"Processo promemoria eseguito: {result.get('message', 'Nessun dettaglio fornito dall orchestrator.')}", "info")
        # Per debug, potresti voler loggare 'result' completamente o ritornarlo come JSON se fosse una chiamata API
        print(f"Risultato da orchestrator_agent.process_reminders(): {result}")

    except Exception as e:
        print(f"Errore critico durante l'esecuzione di orchestrator_agent.process_reminders(): {e}")
        flash(f"Errore grave durante l'attivazione dei promemoria: {str(e)}", "danger")
        # Potresti voler loggare l'eccezione completa qui
        import traceback
        traceback.print_exc()

    return redirect(url_for('index')) # O a una pagina di admin/status dedicata


if __name__ == '__main__':
    create_tables()
    create_default_user()
    app.run(debug=True)
