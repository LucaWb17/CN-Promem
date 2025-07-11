# agents.py
from datetime import datetime, timedelta, date # Aggiunto date
from twilio.rest import Client
import os
import psycopg2
import psycopg2.extras # Aggiunto per DictCursor

# Carica le variabili dal file .env (se non già fatto globalmente in app.py all'avvio)
# Dalla struttura di app.py, load_dotenv() è già chiamato lì.
# Quindi le variabili d'ambiente dovrebbero essere disponibili.

class DatabaseAgent:
    def __init__(self, db_config):
        self.db_config = db_config

    def _get_db_connection(self):
        return psycopg2.connect(**self.db_config)

    def get_unsent_reminders(self):
        conn = self._get_db_connection()
        # Usa DictCursor per accedere ai campi per nome
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT id, phone_number, message, date, sent FROM reminders WHERE sent = FALSE")
        reminders = cursor.fetchall()
        cursor.close()
        conn.close()
        return reminders

    def mark_reminder_sent(self, reminder_id):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE reminders SET sent = TRUE WHERE id = %s", (reminder_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Errore durante l'aggiornamento del promemoria {reminder_id}: {e}")
            # È buona pratica rilanciare l'eccezione o gestirla in modo più specifico
            raise
        finally:
            cursor.close()
            conn.close()

class ReminderLogicAgent:
    def should_send_reminder(self, reminder_date_param): # Rinominato per chiarezza
        """
        Verifica se un promemoria deve essere inviato.
        La logica originale era: oggi + 3 giorni == data promemoria.
        """
        today = datetime.now().date()

        reminder_date_obj = None
        if isinstance(reminder_date_param, datetime):
            reminder_date_obj = reminder_date_param.date()
        elif isinstance(reminder_date_param, date): # Già un oggetto date
             reminder_date_obj = reminder_date_param
        else: # Se fosse una stringa (improbabile dal DB ma per sicurezza)
            try:
                reminder_date_obj = datetime.strptime(str(reminder_date_param), '%Y-%m-%d').date()
            except ValueError:
                print(f"Formato data non valido: {reminder_date_param}")
                return False

        return today + timedelta(days=3) == reminder_date_obj

class NotificationAgent:
    def __init__(self, account_sid, auth_token, phone_number):
        # Verifica che le credenziali siano presenti
        if not all([account_sid, auth_token, phone_number]):
            raise ValueError("Twilio credentials (account_sid, auth_token, phone_number) cannot be empty.")
        self.client = Client(account_sid, auth_token)
        self.phone_number = phone_number

    def send_sms(self, to_phone_number, message_body):
        try:
            message = self.client.messages.create(
                body=message_body,
                from_=self.phone_number,
                to=to_phone_number
            )
            print(f"SMS inviato a {to_phone_number} (SID: {message.sid}): {message_body}")
            return True
        except Exception as e:
            print(f"Errore durante l'invio dell'SMS a {to_phone_number}: {e}")
            return False

class OrchestratorAgent:
    def __init__(self, db_agent, reminder_logic_agent, notification_agent):
        self.db_agent = db_agent
        self.reminder_logic_agent = reminder_logic_agent
        self.notification_agent = notification_agent

    def process_reminders(self):
        print("Avvio processo di controllo promemoria tramite OrchestratorAgent...")
        reminders_processed_count = 0
        reminders_sent_count = 0

        try:
            unsent_reminders = self.db_agent.get_unsent_reminders()
        except Exception as e:
            print(f"Errore nel recuperare i promemoria dal database: {e}")
            return {"error": "Database error fetching reminders", "processed": 0, "sent": 0}

        if not unsent_reminders:
            print("Nessun promemoria non inviato trovato.")
            return {"message": "Nessun promemoria non inviato.", "processed": 0, "sent": 0}

        print(f"Trovati {len(unsent_reminders)} promemoria non inviati.")

        for reminder in unsent_reminders:
            reminders_processed_count += 1
            # reminder['date'] sarà un oggetto datetime.date da psycopg2 DictCursor
            if self.reminder_logic_agent.should_send_reminder(reminder['date']):
                # Formatta la data per il messaggio
                formatted_date = reminder['date'].strftime('%d/%m/%Y') if isinstance(reminder['date'], (datetime, date)) else reminder['date']

                personal_message = (
                    f"Ciao! Ti ricordiamo: {reminder['message']} (Data: {formatted_date})."
                )

                target_phone_number = str(reminder['phone_number']).strip()

                sms_sent = self.notification_agent.send_sms(target_phone_number, personal_message)

                if sms_sent:
                    try:
                        self.db_agent.mark_reminder_sent(reminder['id'])
                        reminders_sent_count += 1
                        print(f"Promemoria {reminder['id']} marcato come inviato.")
                    except Exception as e:
                        # Loggare l'errore ma continuare se possibile con altri promemoria
                        print(f"Fallimento nel marcare il promemoria {reminder['id']} come inviato dopo l'invio SMS: {e}")
                else:
                    print(f"Invio SMS fallito per promemoria {reminder['id']} a {target_phone_number}.")
            # else: # Debug opzionale
                # print(f"Promemoria {reminder['id']} (Data: {reminder['date']}) non soddisfa i criteri di invio.")


        summary = f"Controllo promemoria completato. Promemoria processati: {reminders_processed_count}. SMS inviati: {reminders_sent_count}."
        print(summary)
        return {"message": summary, "processed": reminders_processed_count, "sent": reminders_sent_count}
